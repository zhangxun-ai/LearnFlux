from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from video_transcript_api.transcriber.cloud_quote_repository import (
    CloudQuoteConflict,
    CloudQuoteRepository,
    NewCloudQuote,
)
from video_transcript_api.transcriber.control_store import (
    ControlStoreConflict,
    SQLiteTranscriptionControlStore,
)
from video_transcript_api.transcriber.usage_repository import (
    NewASRAttempt,
    UsageEventRepository,
)


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
TOKEN = "opaque-confirmation-token"


def _store(tmp_path) -> SQLiteTranscriptionControlStore:
    return SQLiteTranscriptionControlStore(tmp_path / "control.db", lease_seconds=60)


def _leased_cloud_job(store: SQLiteTranscriptionControlStore, task_id: str = "task-1"):
    store.create_link_job(
        task_id=task_id,
        view_token="view-1",
        owner_user_id="user-1",
        source_url="https://example.com/video",
        strategy="cloud",
        payload={"version": 1, "url": "https://example.com/video"},
        now=NOW,
    )
    return store.claim_next_job("worker-1", now=NOW)


def _quote(task_id: str = "task-1") -> NewCloudQuote:
    return NewCloudQuote(
        task_id=task_id,
        media_ref="object://asr/opaque-media",
        media_sha256="a" * 64,
        duration_seconds=Decimal("61.25"),
        billable_seconds=62,
        model="fun-asr-2025-11-07",
        unit_price=Decimal("0.0003"),
        max_cost=Decimal("0.0186"),
        continuation_json='{"version":1}',
    )


def _attempt(task_id: str = "task-1") -> NewASRAttempt:
    return NewASRAttempt(
        task_id=task_id,
        model="fun-asr-2025-11-07",
        estimated_quantity=Decimal("62"),
        unit_price=Decimal("0.0003"),
        estimated_cost=Decimal("0.0186"),
        owner_key="owner-hash",
        sample_sha256="a" * 64,
        platform="generic",
        media_id="media-1",
        output_name="transcript.json",
        continuation_json='{"version":1}',
    )


def test_quote_creation_atomically_moves_job_to_waiting_confirmation(tmp_path) -> None:
    store = _store(tmp_path)
    assert _leased_cloud_job(store) is not None

    quote = store.create_quote_and_wait(
        _quote(), token=TOKEN, lease_owner="worker-1", now=NOW
    )

    job = store.get_job("task-1")
    assert quote.status == "pending"
    assert job is not None and job.status == "waiting_confirmation"
    assert job.lease_owner is None and job.lease_expires_at is None


def test_quote_creation_rolls_back_when_job_transition_fails(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ControlStoreConflict, match="job_not_leased"):
        store.create_quote_and_wait(
            _quote("missing-task"), token=TOKEN, lease_owner="worker-1", now=NOW
        )

    with pytest.raises(CloudQuoteConflict, match="quote_not_found"):
        CloudQuoteRepository(store.database).get("missing-task")


def test_confirmation_atomically_queues_quote_and_hands_job_to_provider(tmp_path) -> None:
    store = _store(tmp_path)
    assert _leased_cloud_job(store) is not None
    store.create_quote_and_wait(_quote(), token=TOKEN, lease_owner="worker-1", now=NOW)

    quote, created = store.confirm_quote_and_handoff(
        "task-1", TOKEN, Decimal("0.0186"), now=NOW
    )

    assert created is True
    assert quote.status == "confirmed_queued"
    assert store.get_job("task-1").status == "provider_handoff"


def test_attempt_reservation_atomically_consumes_quote_without_new_job(tmp_path) -> None:
    store = _store(tmp_path)
    assert _leased_cloud_job(store) is not None
    store.create_quote_and_wait(_quote(), token=TOKEN, lease_owner="worker-1", now=NOW)
    store.confirm_quote_and_handoff("task-1", TOKEN, Decimal("0.0186"), now=NOW)
    CloudQuoteRepository(store.database).claim_queued("task-1", "dispatcher-1")

    event = store.reserve_attempt_and_consume_quote(_attempt())
    repeated = store.reserve_attempt_and_consume_quote(_attempt())

    quote = CloudQuoteRepository(store.database).get("task-1")
    assert event.attempt_no == 1
    assert repeated.id == event.id
    assert repeated.attempt_no == event.attempt_no
    assert quote.status == "consumed" and quote.attempt_no == event.attempt_no
    assert store.get_job("task-1").status == "provider_handoff"
    connection = store.database.connect()
    try:
        job_count = connection.execute(
            "SELECT COUNT(*) AS total FROM transcription_jobs WHERE task_id=?",
            ("task-1",),
        ).fetchone()["total"]
        usage_count = connection.execute(
            "SELECT COUNT(*) AS total FROM usage_events WHERE task_id=?",
            ("task-1",),
        ).fetchone()["total"]
    finally:
        connection.close()
    assert job_count == 1
    assert usage_count == 1


def test_lists_only_old_quote_backed_reserved_attempts(tmp_path) -> None:
    store = _store(tmp_path)
    assert _leased_cloud_job(store) is not None
    store.create_quote_and_wait(_quote(), token=TOKEN, lease_owner="worker-1", now=NOW)
    store.confirm_quote_and_handoff("task-1", TOKEN, Decimal("0.0186"), now=NOW)
    CloudQuoteRepository(store.database).claim_queued("task-1", "dispatcher-1")
    event = store.reserve_attempt_and_consume_quote(_attempt(), now=NOW)
    connection = store.database.connect()
    try:
        connection.execute(
            "UPDATE usage_events SET created_at=? WHERE id=?",
            ((NOW - timedelta(seconds=1)).isoformat(), event.id),
        )
        connection.commit()
    finally:
        connection.close()

    records = store.list_quote_backed_reserved(created_before=NOW)

    assert len(records) == 1
    record = records[0]
    assert (record.event_id, record.task_id, record.attempt_no) == (
        event.id,
        "task-1",
        1,
    )
    assert record.media_ref == _quote().media_ref
    assert record.media_sha256 == "a" * 64
    assert record.duration_seconds == Decimal("61.25")
    assert record.max_cost == Decimal("0.0186")
    assert record.continuation_json == '{"version":1}'
