import hashlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_transcript_api.api.services import transcription
from video_transcript_api.transcriber.cloud_quote_repository import (
    CloudQuoteConflict,
    CloudQuoteRepository,
    NewCloudQuote,
)
from video_transcript_api.transcriber.media_preparer import PreparedASRMedia


def cloud_config():
    return {
        "cloud_asr": {
            "enabled": True,
            "provider": "aliyun",
            "model": "fun-asr-2025-11-07",
            "price_cny_per_second": "0.00022",
            "price_verified_at": "2026-08-23",
            "poll_interval_seconds": 1,
            "poll_timeout_seconds": 300,
        }
    }


def _prepared_media(
    temp_root: Path,
    *,
    task_hash: str = "a" * 64,
    candidate: str = "quote-candidate",
    duration_seconds: Decimal = Decimal("15.01"),
) -> PreparedASRMedia:
    media_path = temp_root / "cloud_quotes" / task_hash / candidate / "input.m4a"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"synthetic audio")
    return PreparedASRMedia(
        path=media_path,
        media_format="m4a",
        duration_seconds=duration_seconds,
        size_bytes=media_path.stat().st_size,
        sha256=hashlib.sha256(media_path.read_bytes()).hexdigest(),
        preparation="demuxed",
    )


def test_quote_uses_prepared_media_identity_without_second_probe(
    tmp_path, monkeypatch
):
    temp_root = tmp_path / "temp"
    prepared = _prepared_media(temp_root)
    monkeypatch.setattr(
        transcription.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("quote must not probe prepared media"),
    )

    quote = transcription._prepare_cloud_quote(
        task_id="task-preflight",
        prepared_media=prepared,
        continuation_json='{"version":1}',
        config=cloud_config(),
        db_path=tmp_path / "cache.db",
        temp_root=temp_root,
    )

    assert quote.duration_seconds == Decimal("15.01")
    assert quote.billable_seconds == 16
    assert quote.max_cost == Decimal("0.00352")
    assert quote.continuation_json == '{"version":1}'
    assert quote.media_ref.endswith("/input.m4a")
    assert quote.media_sha256 == prepared.sha256
    assert prepared.path.exists()
    assert CloudQuoteRepository(tmp_path / "cache.db").get("task-preflight").status == "pending"


def test_quote_keeps_long_video_for_batch_confirmation_even_above_legacy_task_cap(
    tmp_path,
):
    temp_root = tmp_path / "temp"
    prepared = _prepared_media(temp_root, duration_seconds=Decimal("5400"))

    quote = transcription._prepare_cloud_quote(
        task_id="task-long-video",
        prepared_media=prepared,
        continuation_json='{"version":1}',
        config=cloud_config(),
        db_path=tmp_path / "cache.db",
        temp_root=temp_root,
    )

    assert quote.billable_seconds == 5400
    assert quote.max_cost == Decimal("1.18800")

def test_quote_repository_failure_cleans_unowned_candidate(tmp_path, monkeypatch):
    temp_root = tmp_path / "temp"
    prepared = _prepared_media(temp_root)
    cleanup_calls = []

    class Preparer:
        def prepare(self, source_path, task_id):
            return prepared

        def cleanup(self, candidate):
            cleanup_calls.append(candidate)

    class FailingRepository:
        def __init__(self, db_path):
            pass

        def create(self, quote):
            raise RuntimeError("database unavailable")

        def get(self, task_id):
            raise CloudQuoteConflict("quote_not_found")

    monkeypatch.setattr(transcription, "_new_media_preparer", lambda: Preparer(), raising=False)
    monkeypatch.setattr(transcription, "CloudQuoteRepository", FailingRepository)
    monkeypatch.setattr(transcription, "get_config", cloud_config)
    monkeypatch.setattr(
        transcription,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )
    monkeypatch.setattr(
        transcription,
        "get_transcription_control_database",
        lambda cache: tmp_path / "cache.db",
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        transcription._pause_for_cloud_confirmation(
            task_id="task-preflight",
            media_path=str(tmp_path / "source.mp4"),
            continuation_json='{"version":1}',
        )

    assert cleanup_calls == [prepared]


def test_quote_commit_unknown_preserves_database_referenced_candidate(
    tmp_path, monkeypatch
):
    temp_root = tmp_path / "temp"
    prepared = _prepared_media(temp_root)
    db_path = tmp_path / "cache.db"
    cleanup_calls = []
    real_repository = CloudQuoteRepository

    class Preparer:
        def prepare(self, source_path, task_id):
            return prepared

        def cleanup(self, candidate):
            cleanup_calls.append(candidate)

    class CommitUnknownRepository:
        def __init__(self, database):
            self.delegate = real_repository(database)

        def create(self, quote):
            self.delegate.create(quote)
            raise RuntimeError("quote commit outcome unknown")

        def get(self, task_id):
            return self.delegate.get(task_id)

    monkeypatch.setattr(transcription, "_new_media_preparer", lambda: Preparer())
    monkeypatch.setattr(
        transcription, "CloudQuoteRepository", CommitUnknownRepository
    )
    monkeypatch.setattr(transcription, "get_config", cloud_config)
    monkeypatch.setattr(
        transcription,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )
    monkeypatch.setattr(
        transcription,
        "get_transcription_control_database",
        lambda cache: db_path,
    )

    with pytest.raises(RuntimeError, match="quote commit outcome unknown"):
        transcription._pause_for_cloud_confirmation(
            task_id="task-commit-unknown",
            media_path=str(tmp_path / "source.mp4"),
            continuation_json='{"version":1}',
        )

    persisted = real_repository(db_path).get("task-commit-unknown")
    assert persisted.media_ref == prepared.path.relative_to(temp_root).as_posix()
    assert cleanup_calls == []


def test_quote_conflict_keeps_only_database_referenced_media(
    tmp_path, monkeypatch
):
    temp_root = tmp_path / "temp"
    candidate = _prepared_media(temp_root, candidate="quote-new")
    existing = _prepared_media(temp_root, candidate="quote-existing")
    db_path = tmp_path / "cache.db"
    CloudQuoteRepository(db_path).create(
        NewCloudQuote(
            task_id="task-conflict",
            media_ref=existing.path.relative_to(temp_root).as_posix(),
            media_sha256=existing.sha256,
            duration_seconds=existing.duration_seconds,
            billable_seconds=16,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00352"),
            continuation_json='{"version":1}',
        )
    )
    cleanup_calls = []

    class Preparer:
        def prepare(self, source_path, task_id):
            return candidate

        def cleanup(self, prepared):
            cleanup_calls.append(prepared)

    class Cache:
        def get_task_by_id(self, task_id):
            return None

        def update_task_progress(self, *args, **kwargs):
            return None

        def update_task_status(self, *args, **kwargs):
            return None

    monkeypatch.setattr(transcription, "cache_manager", Cache())
    monkeypatch.setattr(transcription, "_new_media_preparer", lambda: Preparer(), raising=False)
    monkeypatch.setattr(transcription, "get_config", cloud_config)
    monkeypatch.setattr(
        transcription,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )
    monkeypatch.setattr(
        transcription,
        "get_transcription_control_database",
        lambda cache: db_path,
    )

    with pytest.raises(CloudQuoteConflict, match="quote_already_exists"):
        transcription._pause_for_cloud_confirmation(
            task_id="task-conflict",
            media_path=str(tmp_path / "source.mp4"),
            continuation_json='{"version":1}',
        )

    assert cleanup_calls == [candidate]


def test_cleanup_retained_media_rejects_symlinked_candidate_directory(
    tmp_path, monkeypatch
):
    temp_root = tmp_path / "temp"
    other_media = _prepared_media(
        temp_root,
        task_hash="f" * 64,
        candidate="quote-other",
    )
    linked_task_root = temp_root / "cloud_quotes" / ("e" * 64)
    linked_task_root.mkdir(parents=True)
    (linked_task_root / "quote-linked").symlink_to(
        other_media.path.parent,
        target_is_directory=True,
    )
    monkeypatch.setattr(
        transcription,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )

    transcription._cleanup_retained_quote_media(
        f"cloud_quotes/{'e' * 64}/quote-linked/input.m4a"
    )

    assert other_media.path.exists()


def test_missing_retained_media_fails_confirmed_task(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id="task-missing",
            media_ref=f"cloud_quotes/{'d' * 64}/quote-missing/input.m4a",
            media_sha256="0" * 64,
            duration_seconds=Decimal("15"),
            billable_seconds=15,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00330"),
            continuation_json='{"version":1}',
        ),
        token="quote-token",
    )
    repository.confirm_and_queue(
        "task-missing", "quote-token", Decimal("0.00330")
    )
    repository.claim_queued("task-missing", "claim-owner")
    updates = []

    class Cache:
        def __init__(self):
            self.db_path = db_path

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def update_task_status(self, *args, **kwargs):
            updates.append((args, kwargs))

    monkeypatch.setattr(transcription, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: str(tmp_path / "temp")),
    )

    with pytest.raises(ValueError, match="retained_media_missing"):
        transcription.resume_confirmed_cloud_quote(
            "task-missing",
            claim_owner="claim-owner",
            slot_owner="continuation-owner",
        )

    assert updates[-1][0][1] == "failed"
    assert updates[-1][1]["force"] is True
    assert repository.get("task-missing").status == "failed"


def test_missing_retained_media_does_not_consume_local_choice(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id="task-local-missing",
            media_ref=f"cloud_quotes/{'e' * 64}/quote-missing/input.m4a",
            media_sha256="0" * 64,
            duration_seconds=Decimal("15"),
            billable_seconds=15,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00330"),
            continuation_json='{"version":1}',
        )
    )

    class Cache:
        def __init__(self):
            self.db_path = db_path

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def update_task_status(self, *args, **kwargs):
            return None

    monkeypatch.setattr(transcription, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: str(tmp_path / "temp")),
    )

    with pytest.raises(ValueError, match="retained_media_missing"):
        transcription.resume_cloud_quote_locally(
            "task-local-missing", claim_owner="local-test"
        )

    assert repository.get("task-local-missing").status == "pending"


def test_duplicate_cloud_confirmation_is_idempotently_accepted(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.db"
    CloudQuoteRepository(db_path).create(
        NewCloudQuote(
            task_id="task-confirm",
            media_ref="cloud_quotes/task/input.m4a",
            media_sha256="0" * 64,
            duration_seconds=Decimal("15"),
            billable_seconds=15,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00330"),
        ),
        token="quote-token",
    )
    monkeypatch.setattr(
        transcription, "cache_manager", SimpleNamespace(db_path=db_path)
    )

    first_owner = transcription.claim_cloud_quote_confirmation(
        "task-confirm", "quote-token", Decimal("0.00330")
    )
    duplicate_owner = transcription.claim_cloud_quote_confirmation(
        "task-confirm", "quote-token", Decimal("0.00330")
    )

    assert first_owner
    assert duplicate_owner is False


def test_duplicate_cloud_confirmation_after_dispatch_is_idempotently_accepted(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id="task-confirm-dispatched",
            media_ref="cloud_quotes/task/input.m4a",
            media_sha256="0" * 64,
            duration_seconds=Decimal("15"),
            billable_seconds=15,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00330"),
        ),
        token="quote-token",
    )
    monkeypatch.setattr(
        transcription, "cache_manager", SimpleNamespace(db_path=db_path)
    )

    assert transcription.claim_cloud_quote_confirmation(
        "task-confirm-dispatched", "quote-token", Decimal("0.00330")
    )
    repository.claim_queued("task-confirm-dispatched", "dispatcher")
    repository.mark_consumed("task-confirm-dispatched", attempt_no=1)

    assert transcription.claim_cloud_quote_confirmation(
        "task-confirm-dispatched", "quote-token", Decimal("0.00330")
    ) is False


def test_unconfirmed_quote_still_rejects_a_wrong_confirmation_token(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "cache.db"
    CloudQuoteRepository(db_path).create(
        NewCloudQuote(
            task_id="task-confirm-wrong-token",
            media_ref="cloud_quotes/task/input.m4a",
            media_sha256="0" * 64,
            duration_seconds=Decimal("15"),
            billable_seconds=15,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00330"),
        ),
        token="correct-token",
    )
    monkeypatch.setattr(
        transcription, "cache_manager", SimpleNamespace(db_path=db_path)
    )

    with pytest.raises(CloudQuoteConflict, match="quote_token_mismatch"):
        transcription.claim_cloud_quote_confirmation(
            "task-confirm-wrong-token", "wrong-token", Decimal("0.00330")
        )
