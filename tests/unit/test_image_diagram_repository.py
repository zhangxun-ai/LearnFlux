"""Regression tests for paid image request fencing and persistent versions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import threading

import pytest

from video_transcript_api.image_diagrams.repository import ImageDiagramRepository
from video_transcript_api.transcriber.control_database import SQLiteControlDatabase


@pytest.fixture
def repo(tmp_path):
    return ImageDiagramRepository(tmp_path / "image-diagrams.db")


def create(repo, **overrides):
    values = {
        "owner_user_id": "owner-1", "view_token": "source-1",
        "request_key": "request-1", "recipe_key": "recipe-1",
        "source_hash": "hash-1", "request": {"style": "warm-guide"},
        "source": {"content": "Full private source text", "title": "Test source"},
    }
    values.update(overrides)
    return repo.create_or_get(**values)


def finish(repo, record, **overrides):
    claimed = repo.claim_next()
    assert claimed["id"] == record["id"]
    assert repo.update(claimed["id"], claimed["generation_token"],
                       status="succeeded", image_key="private-image.png", **overrides)
    return repo.get(record["id"])


def age(repo, job_id, *, timestamp="2000-01-01 00:00:00", **fields):
    fields["updated_at"] = timestamp
    with repo.database.transaction() as connection:
        connection.execute(
            "UPDATE image_diagram_jobs SET "
            + ", ".join(name + " = ?" for name in fields) + " WHERE id = ?",
            (*fields.values(), job_id),
        )


def test_deduplicates_requests_and_keeps_full_source_snapshot(repo):
    first = create(repo)
    second = create(repo)
    assert first == second
    assert first["status"] == "queued"
    assert first["source"]["content"] == "Full private source text"
    assert "source_json" not in first
    assert datetime.fromisoformat(first["created_at"]).utcoffset() == timedelta(0)


@pytest.mark.parametrize("changed", [
    {"owner_user_id": "different-owner"}, {"view_token": "different-source"},
    {"recipe_key": "different-recipe"}, {"source_hash": "different-source-hash"},
    {"request": {"style": "handdrawn"}},
])
def test_idempotency_key_cannot_be_reassigned(repo, changed):
    create(repo)
    with pytest.raises(ValueError, match="request_key_conflict"):
        create(repo, **changed)


def test_different_request_joins_active_source_without_second_paid_job(repo):
    first = create(repo)
    second = create(repo, request_key="new-key", recipe_key="another-recipe")
    assert first["id"] == second["id"]
    assert len(repo.list_for_source("owner-1", "source-1")) == 1


def test_parallel_create_only_creates_one_active_source_job(tmp_path):
    path = tmp_path / "parallel-create.db"
    initial = ImageDiagramRepository(path)
    barrier = threading.Barrier(6)

    def attempt(index):
        local_repo = ImageDiagramRepository(path)
        barrier.wait()
        return create(local_repo, request_key=f"request-{index}")["id"]

    with ThreadPoolExecutor(max_workers=6) as executor:
        ids = list(executor.map(attempt, range(6)))
    assert len(set(ids)) == 1
    assert len(initial.list_for_source("owner-1", "source-1")) == 1


def test_parallel_workers_claim_each_job_at_most_once(tmp_path):
    repo = ImageDiagramRepository(tmp_path / "claims.db")
    jobs = [create(repo, request_key=f"request-{i}", view_token=f"source-{i}")
            for i in range(8)]
    barrier = threading.Barrier(8)

    def attempt(_index):
        barrier.wait()
        return repo.claim_next()

    with ThreadPoolExecutor(max_workers=8) as executor:
        claimed = list(executor.map(attempt, range(8)))
    assert {item["id"] for item in claimed} == {item["id"] for item in jobs}
    assert len({item["generation_token"] for item in claimed}) == 8
    assert all(item["status"] == "planning" for item in claimed)
    assert repo.claim_next() is None


def test_versions_and_owner_isolation_preserve_success_after_failure(repo):
    first = finish(repo, create(repo))
    second = create(repo, request_key="revision-1", parent_id=first["id"])
    claim = repo.claim_next()
    assert repo.update(second["id"], claim["generation_token"],
                       status="failed", error_code="image_request_rejected")
    other = create(repo, owner_user_id="owner-2", request_key="other-key")
    assert [row["id"] for row in repo.list_for_source("owner-1", "source-1")] == [second["id"], first["id"]]
    assert [row["id"] for row in repo.list_for_source("owner-2", "source-1")] == [other["id"]]
    assert repo.find_reusable("owner-1", "source-1", "recipe-1")["id"] == first["id"]
    with pytest.raises(ValueError, match="invalid_image_diagram_parent"):
        create(repo, request_key="bad-parent", parent_id=other["id"])


def test_submission_boundary_and_completed_result_are_immutable(repo):
    record = create(repo)
    claim = repo.claim_next()
    token = claim["generation_token"]
    assert repo.update(record["id"], token, status="generating", stage="generating_image")
    submitted_at = repo.get(record["id"])["submitted_at"]
    assert submitted_at
    with pytest.raises(ValueError, match="submission_boundary_is_immutable"):
        repo.update(record["id"], token, submitted_at=None)
    assert repo.update(record["id"], token, status="reviewing", image_key="saved.png")
    assert repo.update(record["id"], token, status="succeeded", review={"status": "passed"})
    assert repo.update(record["id"], token, status="failed") is False
    assert repo.get(record["id"])["status"] == "succeeded"


def test_review_or_success_requires_a_saved_image(repo):
    record = create(repo)
    token = repo.claim_next()["generation_token"]
    with pytest.raises(ValueError, match="image_required"):
        repo.update(record["id"], token, status="succeeded")
    with pytest.raises(ValueError, match="invalid_image_diagram_update_fields"):
        repo.update(record["id"], token, owner_user_id="other")
    assert repo.update(record["id"], "", stage="planning") is False


def test_recovery_only_requeues_unsubmitted_planning_and_fences_old_worker(repo):
    record = create(repo)
    old_token = repo.claim_next()["generation_token"]
    age(repo, record["id"])
    assert repo.recover_interrupted() == 1
    assert repo.get(record["id"])["status"] == "queued"
    new_token = repo.claim_next()["generation_token"]
    assert new_token != old_token
    assert repo.update(record["id"], old_token, status="generating") is False
    assert repo.update(record["id"], new_token, stage="reading_source")


@pytest.mark.parametrize("state,submitted", [("generating", None), ("planning", "2020-01-01T00:00:00+00:00")])
def test_stale_submission_is_unknown_and_never_automatically_claimed(repo, state, submitted):
    record = create(repo)
    old_token = repo.claim_next()["generation_token"]
    age(repo, record["id"], status=state, submitted_at=submitted)
    assert repo.recover_interrupted() == 1
    recovered = repo.get(record["id"])
    assert recovered["status"] == "unknown"
    assert recovered["error_code"] == "image_outcome_unknown"
    assert repo.claim_next() is None
    assert repo.find_reusable("owner-1", "source-1", "recipe-1")["id"] == record["id"]
    assert repo.update(record["id"], old_token, image_key="late.png", status="succeeded") is False


def test_legacy_review_preserves_saved_image_without_running_or_fabricating_review(repo):
    record = create(repo)
    claim = repo.claim_next()
    assert repo.update(record["id"], claim["generation_token"],
                       status="reviewing", image_key="saved.png", usage={"image": {"output_tokens": 20}})
    assert repo.recover_interrupted() == 1
    recovered = repo.get(record["id"])
    assert recovered["status"] == "succeeded"
    assert recovered["image_key"] == "saved.png"
    assert recovered["review"] is None
    assert recovered["usage"] == {"image": {"output_tokens": 20}}
    assert repo.update(record["id"], claim["generation_token"], review={"status": "passed"}) is False
    # The old saved job no longer blocks an explicit new version of this source.
    assert create(repo, request_key="next-version")["status"] == "queued"


def test_recent_legacy_naive_utc_timestamp_does_not_become_stale(repo):
    record = create(repo)
    repo.claim_next()
    recent = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(tzinfo=None).isoformat(sep=" ")
    age(repo, record["id"], timestamp=recent)
    assert repo.recover_interrupted(stale_minutes=20) == 0
    assert repo.get(record["id"])["status"] == "planning"


def test_heartbeat_keeps_slow_work_alive_without_changing_stage_or_decoding_source(repo, monkeypatch):
    record = create(repo)
    token = repo.claim_next()["generation_token"]
    age(repo, record["id"])
    with monkeypatch.context() as patch:
        patch.setattr(repo, "_decode", lambda row: pytest.fail("Heartbeat must not read private snapshots"))
        assert not repo.heartbeat(record["id"], "obsolete-token")
        assert repo.heartbeat(record["id"], token)
    assert repo.recover_interrupted() == 0
    current = repo.get(record["id"])
    assert current["status"] == "planning"
    assert current["stage"] == "planning"
    assert repo.update(record["id"], token, status="failed")
    assert not repo.heartbeat(record["id"], token)


def test_constructor_does_not_create_postgres_schema():
    class PostgresDatabase:
        dialect = "postgres"

        def transaction(self):
            raise AssertionError("PostgreSQL DDL belongs to immutable migrations")

    ImageDiagramRepository(PostgresDatabase())


def test_postgres_migration_matches_sqlite_table_columns_and_indexes(tmp_path):
    migration = (Path(__file__).parents[2] / "src/video_transcript_api/persistence/migrations/postgres/0008_image_diagrams.sql").read_text()
    # The migration deliberately uses portable types and partial-index syntax.
    migration_db = SQLiteControlDatabase(tmp_path / "migration.db")
    with migration_db.transaction() as connection:
        connection.executescript(migration)
        migrated_columns = {row["name"] for row in connection.execute("PRAGMA table_info(image_diagram_jobs)")}
        migrated_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(image_diagram_jobs)")}
    repo = ImageDiagramRepository(tmp_path / "repository.db")
    with repo.database.transaction() as connection:
        runtime_columns = {row["name"] for row in connection.execute("PRAGMA table_info(image_diagram_jobs)")}
        runtime_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(image_diagram_jobs)")}
    assert migrated_columns == runtime_columns
    assert migrated_indexes == runtime_indexes


def test_daily_quota_counts_attempts_and_allows_deduplication_at_limit(repo):
    first = create(repo, max_daily_generations=1)
    assert create(repo, max_daily_generations=1)["id"] == first["id"]
    # A new click for an already active source joins it, without quota use.
    assert create(repo, request_key="new-click", max_daily_generations=1)["id"] == first["id"]
    with pytest.raises(ValueError, match="^image_diagram_daily_limit$"):
        create(repo, request_key="second-source", view_token="source-2", max_daily_generations=1)
    claimed = repo.claim_next()
    repo.update(first["id"], claimed["generation_token"], status="failed", error_code="planning_failed")
    # Conservative accounting still counts failed work.
    with pytest.raises(ValueError, match="^image_diagram_daily_limit$"):
        create(repo, request_key="failed-retry", max_daily_generations=1)
    assert create(repo, max_daily_generations=1)["id"] == first["id"]


def test_daily_quota_isolated_between_owners_and_uses_utc_boundary(repo):
    first = create(repo, max_daily_generations=1)
    claim = repo.claim_next()
    repo.update(first["id"], claim["generation_token"], status="failed")
    with repo.database.transaction() as connection:
        # Beijing 2026-10-31 starts at 2026-10-30 16:00 UTC.
        connection.execute(
            "UPDATE image_diagram_jobs SET created_at = ? WHERE id = ?",
            ("2026-10-30T15:59:59.000000+00:00", first["id"]),
        )
    assert create(repo, request_key="new-day", max_daily_generations=1,
                  day_start="2026-10-31T00:00:00+08:00")["id"] != first["id"]
    assert create(repo, owner_user_id="owner-2", request_key="owner-2-key",
                  max_daily_generations=1)["owner_user_id"] == "owner-2"


def test_daily_quota_boundary_is_inclusive(repo):
    first = create(repo)
    claim = repo.claim_next()
    repo.update(first["id"], claim["generation_token"], status="failed")
    with repo.database.transaction() as connection:
        connection.execute(
            "UPDATE image_diagram_jobs SET created_at = ? WHERE id = ?",
            ("2026-10-30T16:00:00.000000+00:00", first["id"]),
        )
    with pytest.raises(ValueError, match="^image_diagram_daily_limit$"):
        create(repo, request_key="at-boundary", max_daily_generations=1,
               day_start="2026-10-31T00:00:00+08:00")


def test_concurrent_sources_cannot_exceed_daily_quota(tmp_path):
    repo = ImageDiagramRepository(tmp_path / "quota.db")
    barrier = threading.Barrier(6)

    def attempt(index):
        barrier.wait()
        try:
            return create(repo, view_token=f"source-{index}", request_key=f"key-{index}",
                          max_daily_generations=2)["id"]
        except ValueError as exc:
            assert str(exc) == "image_diagram_daily_limit"
            return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(attempt, range(6)))
    assert sum(item is not None for item in results) == 2


def test_get_identity_does_not_select_or_decode_private_snapshots(repo, monkeypatch):
    from contextlib import contextmanager

    record = create(repo)
    with repo.database.transaction() as connection:
        connection.execute("UPDATE image_diagram_jobs SET source_json = ? WHERE id = ?",
                           ("intentionally invalid private JSON", record["id"]))
    statements = []
    original_transaction = repo.database.transaction

    @contextmanager
    def recording_transaction():
        with original_transaction() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repo.database, "transaction", recording_transaction)
    assert repo.get_identity(record["id"]) == {
        "id": record["id"], "owner_user_id": "owner-1", "view_token": "source-1",
    }
    selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "SELECT id, owner_user_id, view_token" in selects[0]
    assert "source_json" not in selects[0]
    assert "*" not in selects[0]
    assert repo.get_identity("missing-job") is None


@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_get_by_request_key_preserves_terminal_idempotent_outcome(repo, status):
    record = create(repo)
    claim = repo.claim_next()
    repo.update(record["id"], claim["generation_token"], status=status,
                error_code="test_terminal_outcome")
    result = repo.get_by_request_key("request-1")
    assert result["id"] == record["id"]
    assert result["status"] == status
    assert result["source"]["content"] == "Full private source text"
    assert repo.get_by_request_key("missing-key") is None


def test_metadata_claim_does_not_load_private_snapshots_before_worker_authorization(repo, monkeypatch):
    from contextlib import contextmanager

    record = create(repo)
    with repo.database.transaction() as connection:
        connection.execute("UPDATE image_diagram_jobs SET source_json = ?, request_json = ? WHERE id = ?",
                           ("private invalid JSON", "private invalid JSON", record["id"]))
    statements = []
    original_transaction = repo.database.transaction

    @contextmanager
    def recording_transaction():
        with original_transaction() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repo.database, "transaction", recording_transaction)
    claimed = repo.claim_next(metadata_only=True)
    assert claimed["id"] == record["id"]
    assert claimed["status"] == "planning"
    assert claimed["generation_token"]
    assert not {"source", "request", "source_json", "request_json"} & claimed.keys()
    selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2
    assert all("source_json" not in statement and "request_json" not in statement and "*" not in statement for statement in selects)
    assert repo.claim_next(metadata_only=True) is None


def test_recovery_does_not_load_private_snapshots(repo, monkeypatch):
    from contextlib import contextmanager

    record = create(repo)
    repo.claim_next()
    age(repo, record["id"])
    statements = []
    original_transaction = repo.database.transaction

    @contextmanager
    def recording_transaction():
        with original_transaction() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repo.database, "transaction", recording_transaction)
    assert repo.recover_interrupted() == 1
    selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "source_json" not in selects[0] and "*" not in selects[0]
