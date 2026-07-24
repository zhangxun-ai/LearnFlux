import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from threading import Barrier

import pytest

from video_transcript_api.transcriber.usage_repository import (
    NewASRAttempt,
    UsageEventRepository,
    UsageRepositoryError,
)


def make_attempt(**overrides):
    values = {
        "task_id": "task-1",
        "model": "paraformer-v2",
        "estimated_quantity": Decimal("12.500"),
        "unit_price": Decimal("0.0002"),
        "estimated_cost": Decimal("0.0025000"),
        "owner_key": "owner-hash",
        "sample_sha256": "sample-hash",
        "platform": "youtube",
        "media_id": "video-1",
        "output_name": "video-1.txt",
    }
    values.update(overrides)
    return NewASRAttempt(**values)


def test_initialization_is_idempotent_and_rejects_path_escape(tmp_path):
    db_path = tmp_path / "cache.sqlite3"
    UsageEventRepository(db_path)
    UsageEventRepository(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usage_events)")
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert {
        "id",
        "attempt_no",
        "idempotency_key",
        "task_id",
        "provider_task_id",
        "continuation_json",
        "postprocess_status",
    } <= columns
    assert journal_mode == "wal"

    repository = UsageEventRepository(db_path)
    with pytest.raises(UsageRepositoryError) as exc_info:
        repository.reserve_attempt(make_attempt(output_name="../escape.txt"))
    assert exc_info.value.code == "invalid_output_name"
    assert str(exc_info.value) == "invalid_output_name"


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("task_id", "missing_task_id"),
        ("platform", "missing_platform"),
        ("media_id", "missing_media_id"),
        ("sample_sha256", "missing_sample_sha256"),
    ],
)
def test_reservation_requires_recovery_identifiers(tmp_path, field, code):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")

    with pytest.raises(UsageRepositoryError) as exc_info:
        repository.reserve_attempt(make_attempt(**{field: " "}))

    assert exc_info.value.code == code
    assert str(exc_info.value) == code


def test_concurrent_reservation_returns_one_row_and_preserves_pricing(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    barrier = Barrier(2)

    def reserve_once():
        barrier.wait()
        return repository.reserve_attempt(make_attempt())

    with ThreadPoolExecutor(max_workers=2) as executor:
        events = list(executor.map(lambda _: reserve_once(), range(2)))

    expected_key = sha256(
        b"task-1:asr:1:aliyun:paraformer-v2"
    ).hexdigest()
    assert events[0].id == events[1].id
    assert events[0].attempt_no == 1
    assert events[0].idempotency_key == expected_key
    assert events[0].estimated_quantity == "12.5"
    assert events[0].unit_price == "0.0002"
    assert events[0].estimated_cost == "0.0025"

    replay = repository.reserve_attempt(
        make_attempt(
            model="changed-model",
            estimated_quantity=Decimal("999"),
            unit_price=Decimal("9"),
            estimated_cost=Decimal("8991"),
            sample_sha256="changed-sample",
        )
    )
    assert replay.id == events[0].id
    assert replay.model == "paraformer-v2"
    assert replay.estimated_quantity == "12.5"
    assert replay.sample_sha256 == "sample-hash"

    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 1


def test_new_paid_attempt_requires_an_explicit_terminal_predecessor(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    first = repository.reserve_attempt(make_attempt())
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

    with pytest.raises(UsageRepositoryError) as active_error:
        repository.reserve_attempt(make_attempt(), new_paid_attempt=True)
    assert active_error.value.code == "attempt_already_active"

    assert repository.claim_submission(first.id, "worker-1", now=now)
    assert not repository.record_remote_failure(
        first.id,
        "worker-2",
        now=now + timedelta(seconds=1),
        error_code="provider_failed",
    )
    assert repository.record_remote_failure(
        first.id,
        "worker-1",
        now=now + timedelta(seconds=1),
        error_code="provider_failed",
    )
    with pytest.raises(UsageRepositoryError) as retry_error:
        repository.reserve_attempt(make_attempt())
    assert retry_error.value.code == "new_paid_attempt_required"

    second = repository.reserve_attempt(make_attempt(), new_paid_attempt=True)
    assert second.attempt_no == 2
    assert second.id != first.id


def test_expired_submission_is_frozen_instead_of_resubmitted(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    event = repository.reserve_attempt(make_attempt())
    started = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

    assert repository.claim_submission(event.id, "worker-1", now=started) is True
    assert repository.claim_submission(event.id, "worker-2", now=started) is False

    heartbeat_at = started + timedelta(seconds=30)
    assert repository.heartbeat_lease(
        event.id, "worker-1", now=heartbeat_at
    ) is True
    assert repository.get_event(event.id).lease_expires_at == (
        heartbeat_at + timedelta(seconds=60)
    ).isoformat(timespec="microseconds")

    assert repository.claim_submission(
        event.id, "worker-2", now=started + timedelta(seconds=89)
    ) is False
    assert not repository.claim_submission(
        event.id, "worker-2", now=started + timedelta(seconds=91)
    )
    assert repository.freeze_claimed_submission_unknown(
        event.id,
        "worker-1",
        error_code="submission_timeout",
        now=started + timedelta(seconds=40),
    )
    frozen = repository.get_event(event.id)
    assert (frozen.remote_status, frozen.materialization_status) == (
        "submission_unknown",
        "not_applicable",
    )

    stale_event = repository.reserve_attempt(make_attempt(task_id="stale-task"))
    assert repository.claim_submission(stale_event.id, "worker-1", now=started)
    assert repository.freeze_submission_unknown(
        stale_event.id,
        error_code="submission_timeout",
        now=started + timedelta(seconds=91),
    )
    frozen = repository.get_event(stale_event.id)
    assert (frozen.remote_status, frozen.materialization_status) == (
        "submission_unknown",
        "not_applicable",
    )


def test_record_submitted_is_atomic_and_provider_task_id_is_private(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    event = repository.reserve_attempt(make_attempt())
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    assert repository.claim_submission(event.id, "worker-1", now=now)

    assert repository.record_submitted(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=1),
        provider_task_id="provider-secret-id",
    )
    public = repository.get_event(event.id)
    recovery = repository.get_recovery_event(event.id)

    assert public.remote_status == "submitted"
    assert not hasattr(public, "provider_task_id")
    assert "provider_task_id" not in public.serialize()
    assert recovery.provider_task_id == "provider-secret-id"
    assert "provider_task_id" not in recovery.serialize()
    assert recovery.lease_owner == "worker-1"
    assert recovery.lease_expires_at == (
        now + timedelta(seconds=60)
    ).isoformat(timespec="microseconds")
    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute(
            "SELECT remote_status, provider_task_id FROM usage_events WHERE id = ?",
            (event.id,),
        ).fetchone() == ("submitted", "provider-secret-id")

    expired = repository.reserve_attempt(make_attempt(task_id="expired-submit"))
    repository.claim_submission(expired.id, "worker-1", now=now)
    assert not repository.record_submitted(
        expired.id,
        "worker-1",
        now=now + timedelta(seconds=61),
        provider_task_id="must-not-be-written",
    )
    assert repository.get_recovery_event(expired.id).provider_task_id is None


def test_recovery_claim_is_single_owner_after_lease_expiry(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    invalid = repository.reserve_attempt(make_attempt(task_id="invalid-expiry"))
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    assert not repository.mark_result_expired(
        invalid.id, "worker-1", now=now
    )
    assert repository.get_event(invalid.id).remote_status == "reserved"

    event = repository.reserve_attempt(make_attempt())
    repository.claim_submission(event.id, "worker-1", now=now)
    repository.record_submitted(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=1),
        provider_task_id="recoverable-id",
    )

    recoverable = repository.list_recoverable_events()
    assert [item.id for item in recoverable] == [event.id]
    assert recoverable[0].provider_task_id == "recoverable-id"

    assert not repository.claim_recovery(
        event.id, "worker-2", now=now + timedelta(seconds=59)
    )
    barrier = Barrier(2)

    def claim_once(owner):
        barrier.wait()
        return repository.claim_recovery(
            event.id, owner, now=now + timedelta(seconds=61)
        )

    owners = ("worker-2", "worker-3")
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(claim_once, owners))

    assert claimed.count(True) == 1
    winner = owners[claimed.index(True)]
    assert repository.get_event(event.id).lease_owner == winner
    assert repository.mark_result_expired(
        event.id, winner, now=now + timedelta(seconds=62)
    )
    expired = repository.get_event(event.id)
    assert (
        expired.status,
        expired.remote_status,
        expired.materialization_status,
        expired.error_code,
        expired.lease_owner,
    ) == (
        "remote_result_expired",
        "result_expired",
        "failed",
        "result_expired",
        None,
    )


def test_unknown_submission_and_polling_take_distinct_recovery_paths(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

    no_remote_id = repository.reserve_attempt(make_attempt(task_id="task-no-id"))
    repository.claim_submission(no_remote_id.id, "worker-1", now=now)
    with pytest.raises(UsageRepositoryError) as unsafe_error:
        repository.freeze_submission_unknown(
            no_remote_id.id,
            error_code="raw connection reset details",
            now=now + timedelta(seconds=61),
        )
    assert unsafe_error.value.code == "invalid_error_code"
    assert not repository.freeze_submission_unknown(
        no_remote_id.id,
        error_code="submission_timeout",
        now=now + timedelta(seconds=59),
    )
    assert not repository.close_submission_unknown(no_remote_id.id)
    assert repository.get_event(no_remote_id.id).remote_status == "submitting"
    assert repository.freeze_submission_unknown(
        no_remote_id.id,
        error_code="submission_timeout",
        now=now + timedelta(seconds=61),
    )
    frozen = repository.get_event(no_remote_id.id)
    assert (frozen.status, frozen.materialization_status) == (
        "submission_unknown",
        "not_applicable",
    )
    with pytest.raises(UsageRepositoryError) as active_error:
        repository.reserve_attempt(
            make_attempt(task_id="task-no-id"), new_paid_attempt=True
        )
    assert active_error.value.code == "attempt_already_active"
    assert repository.close_submission_unknown(no_remote_id.id)
    closed = repository.get_event(no_remote_id.id)
    assert (
        closed.remote_status,
        closed.materialization_status,
        closed.error_code,
    ) == ("closed_unreconciled", "not_applicable", "closed_unreconciled")
    retry = repository.reserve_attempt(
        make_attempt(task_id="task-no-id"), new_paid_attempt=True
    )
    assert retry.attempt_no == 2

    submitted = repository.reserve_attempt(make_attempt(task_id="task-with-id"))
    repository.claim_submission(submitted.id, "worker-2", now=now)
    repository.record_submitted(
        submitted.id,
        "worker-2",
        now=now + timedelta(seconds=1),
        provider_task_id="recoverable-id",
    )
    assert repository.mark_polling_unknown(
        submitted.id,
        "worker-2",
        now=now + timedelta(seconds=2),
        error_code="polling_timeout",
    )
    polling = repository.get_event(submitted.id)
    assert (polling.status, polling.materialization_status) == (
        "polling_unknown",
        "pending",
    )
    assert repository.get_recovery_event(submitted.id).provider_task_id == "recoverable-id"
    assert polling.lease_owner is None


def test_remote_success_calculates_decimal_cost_and_materialization_recovers(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    event = repository.reserve_attempt(make_attempt())
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    repository.claim_submission(event.id, "worker-1", now=now)
    repository.record_submitted(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=1),
        provider_task_id="provider-task",
    )

    assert repository.record_remote_success(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=2),
        reported_quantity=Decimal("13"),
        elapsed_seconds=Decimal("7.500"),
    )
    succeeded = repository.get_event(event.id)
    assert succeeded.status == "remote_succeeded"
    assert succeeded.reported_quantity == "13"
    assert succeeded.calculated_cost == "0.0026"
    assert succeeded.error_code == "reported_usage_exceeds_reservation"
    assert succeeded.elapsed_seconds == "7.5"

    assert repository.record_materialization_failed(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=3),
        error_code="materialization_failed",
    )
    failed = repository.get_event(event.id)
    assert failed.status == "materialization_failed"
    assert (failed.reported_quantity, failed.calculated_cost) == ("13", "0.0026")

    assert failed.lease_owner is None
    assert repository.claim_recovery(
        event.id, "worker-2", now=now + timedelta(seconds=3)
    )
    assert repository.record_materialization_succeeded(
        event.id, "worker-2", now=now + timedelta(seconds=4)
    )
    recovered = repository.get_event(event.id)
    assert recovered.status == "succeeded"
    assert (recovered.reported_quantity, recovered.calculated_cost) == (
        "13",
        "0.0026",
    )
    assert recovered.error_code == "reported_usage_exceeds_reservation"
    assert recovered.postprocess_key == sha256(
        f"{event.id}:postprocess:v1".encode()
    ).hexdigest()
    assert recovered.postprocess_status == "pending"
    assert recovered.lease_owner is None

    expiring = repository.reserve_attempt(
        make_attempt(task_id="settled-result-expired")
    )
    assert repository.claim_submission(expiring.id, "worker-1", now=now)
    assert repository.record_submitted(
        expiring.id,
        "worker-1",
        now=now + timedelta(seconds=1),
        provider_task_id="expiring-task",
    )
    assert repository.record_remote_success(
        expiring.id,
        "worker-1",
        now=now + timedelta(seconds=2),
        reported_quantity=Decimal("3"),
        elapsed_seconds=Decimal("4"),
    )
    assert repository.record_materialization_failed(
        expiring.id,
        "worker-1",
        now=now + timedelta(seconds=3),
        error_code="materialization_failed",
    )
    assert repository.claim_recovery(
        expiring.id, "worker-2", now=now + timedelta(seconds=4)
    )
    assert repository.mark_result_expired(
        expiring.id, "worker-2", now=now + timedelta(seconds=5)
    )
    expired = repository.get_event(expiring.id)
    assert expired.status == "remote_result_expired"
    assert (expired.reported_quantity, expired.calculated_cost) == ("3", "0.0006")


def test_postprocess_outbox_claims_and_completes_once(tmp_path):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    event = repository.reserve_attempt(make_attempt())
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    repository.claim_submission(event.id, "worker-1", now=now)
    repository.record_submitted(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=1),
        provider_task_id="provider-task",
    )
    repository.record_remote_success(
        event.id,
        "worker-1",
        now=now + timedelta(seconds=2),
        reported_quantity=Decimal("1"),
        elapsed_seconds=Decimal("2"),
    )
    repository.record_materialization_succeeded(
        event.id, "worker-1", now=now + timedelta(seconds=3)
    )

    assert repository.claim_postprocess(event.id) is True
    assert repository.claim_postprocess(event.id) is False
    assert repository.complete_postprocess(event.id) is True
    assert repository.complete_postprocess(event.id) is False
    assert repository.get_event(event.id).postprocess_status == "completed"


def test_remote_capacity_survives_submit_lease_expiry_and_old_reserved_fails(
    tmp_path,
):
    repository = UsageEventRepository(tmp_path / "cache.sqlite3")
    startup_at = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    orphan = repository.reserve_attempt(make_attempt(task_id="old-reserved"))
    protected = repository.reserve_attempt(
        make_attempt(task_id="quote-backed-reserved")
    )
    active = repository.reserve_attempt(make_attempt(task_id="active-submit"))
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE usage_events SET created_at=? WHERE id IN (?, ?)",
            (
                (startup_at - timedelta(seconds=1)).isoformat(),
                orphan.id,
                protected.id,
            ),
        )
        connection.execute(
            "UPDATE usage_events SET created_at=? WHERE id=?",
            ((startup_at + timedelta(seconds=1)).isoformat(), active.id),
        )
    assert repository.claim_submission(active.id, "worker-1", now=startup_at)

    failed = repository.fail_orphan_reserved(
        created_before=startup_at,
        excluded_event_ids={protected.id},
    )

    assert [event.id for event in failed] == [orphan.id]
    assert repository.get_event(orphan.id).remote_status == "failed"
    assert repository.get_event(protected.id).remote_status == "reserved"
    assert repository.list_remote_capacity_attempt_ids() == [active.id]
    assert repository.next_submission_lease_expiry(
        now=startup_at
    ) == startup_at + timedelta(seconds=60)

    assert repository.freeze_stale_submissions(
        now=startup_at + timedelta(seconds=61)
    ) == 1
    assert repository.get_event(active.id).remote_status == "submission_unknown"
    assert repository.list_remote_capacity_attempt_ids() == [active.id]
