from __future__ import annotations

import os
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
    PostgresTranscriptionControlStore,
)
from video_transcript_api.transcriber.usage_repository import NewASRAttempt


pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def store():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("temporary PostgreSQL DSN not provided")
    control_store = PostgresTranscriptionControlStore(dsn, lease_seconds=60)
    control_store.clear_contract_tables()
    try:
        yield control_store
    finally:
        control_store.clear_contract_tables()
        control_store.close()


def test_postgres_job_claim_and_expired_lease_reuse_same_task(store) -> None:
    store.create_link_job(
        task_id="pg-task-1",
        view_token="pg-view-1",
        owner_user_id="pg-user",
        source_url="https://example.com/postgres-video",
        strategy="cloud",
        payload={"version": 1, "url": "https://example.com/postgres-video"},
        now=NOW,
    )
    store.update_task_progress(
        "pg-task-1", stage="acquiring_content", fraction=0.1
    )
    task = store.get_task_by_view_token("pg-view-1")
    assert task is not None
    assert task["progress_json"]["stage"] == "acquiring_content"

    assert store.claim_next_job("worker-a", now=NOW).task_id == "pg-task-1"
    assert store.claim_next_job("worker-b", now=NOW) is None
    reclaimed = store.claim_next_job("worker-b", now=NOW + timedelta(seconds=61))
    assert reclaimed.task_id == "pg-task-1"
    assert reclaimed.attempt_count == 2
    assert store.complete_job("pg-task-1", "worker-b", now=NOW + timedelta(seconds=62))
    assert store.claim_next_job("worker-c", now=NOW + timedelta(minutes=2)) is None


def test_postgres_upload_session_consumption_is_idempotent(store) -> None:
    session = store.create_upload_session(
        session_id="pg-upload-1",
        owner_user_id="pg-user",
        object_key="source/pg-opaque",
        max_bytes=100,
        expires_at=NOW + timedelta(minutes=5),
        now=NOW,
    )
    first = store.consume_upload_session_and_create_job(
        session_id=session.id,
        owner_user_id="pg-user",
        actual_bytes=20,
        task_id="pg-task-2",
        view_token="pg-view-2",
        strategy="cloud",
        payload={"version": 1, "filename": "lesson.mp4"},
        now=NOW,
    )
    second = store.consume_upload_session_and_create_job(
        session_id=session.id,
        owner_user_id="pg-user",
        actual_bytes=20,
        task_id="ignored",
        view_token="ignored",
        strategy="cloud",
        payload={"version": 1, "filename": "lesson.mp4"},
        now=NOW + timedelta(seconds=1),
    )
    assert second.task_id == first.task_id == "pg-task-2"


def test_postgres_quote_and_usage_handoffs_are_atomic(store) -> None:
    store.create_link_job(
        task_id="pg-task-3",
        view_token="pg-view-3",
        owner_user_id="pg-user",
        source_url="https://example.com/cloud",
        strategy="cloud",
        payload={"version": 1, "url": "https://example.com/cloud"},
        now=NOW,
    )
    store.claim_next_job("pg-worker", now=NOW)
    quote_input = NewCloudQuote(
        task_id="pg-task-3",
        media_ref="object://asr/pg-opaque",
        media_sha256="b" * 64,
        duration_seconds=Decimal("61.25"),
        billable_seconds=62,
        model="fun-asr-2025-11-07",
        unit_price=Decimal("0.0003"),
        max_cost=Decimal("0.0186"),
        continuation_json='{"version":1}',
    )
    store.create_quote_and_wait(
        quote_input, token="pg-token", lease_owner="pg-worker", now=NOW
    )
    quote, created = store.confirm_quote_and_handoff(
        "pg-task-3", "pg-token", Decimal("0.0186"), now=NOW
    )
    assert created is True and quote.status == "confirmed_queued"
    assert store.get_job("pg-task-3").status == "provider_handoff"

    CloudQuoteRepository(store.database).claim_queued("pg-task-3", "dispatcher")
    event = store.reserve_attempt_and_consume_quote(
        NewASRAttempt(
            task_id="pg-task-3",
            model="fun-asr-2025-11-07",
            estimated_quantity=Decimal("62"),
            unit_price=Decimal("0.0003"),
            estimated_cost=Decimal("0.0186"),
            owner_key="owner-hash",
            sample_sha256="b" * 64,
            platform="generic",
            media_id="pg-media",
            output_name="transcript.json",
            continuation_json='{"version":1}',
        ),
        now=NOW,
    )
    stored_quote = CloudQuoteRepository(store.database).get("pg-task-3")
    assert event.attempt_no == 1
    assert stored_quote.status == "consumed"
    assert stored_quote.attempt_no == event.attempt_no


def test_postgres_quote_insert_rolls_back_if_job_transition_fails(store) -> None:
    quote_input = NewCloudQuote(
        task_id="pg-missing-task",
        media_ref="object://asr/pg-missing",
        media_sha256="c" * 64,
        duration_seconds=Decimal("10"),
        billable_seconds=10,
        model="fun-asr-2025-11-07",
        unit_price=Decimal("0.0003"),
        max_cost=Decimal("0.003"),
    )
    with pytest.raises(ControlStoreConflict, match="job_not_leased"):
        store.create_quote_and_wait(
            quote_input,
            token="pg-rollback-token",
            lease_owner="pg-worker",
            now=NOW,
        )
    with pytest.raises(CloudQuoteConflict, match="quote_not_found"):
        CloudQuoteRepository(store.database).get("pg-missing-task")
