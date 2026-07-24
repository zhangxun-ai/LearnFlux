from __future__ import annotations

import hashlib
import sqlite3
import wave
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from video_transcript_api.transcriber.cloud_quote_repository import NewCloudQuote
from video_transcript_api.transcriber.cloud_runtime import (
    identify_quote_backed_reserved,
    resume_quote_backed_reserved_attempt,
)
from video_transcript_api.transcriber.control_store import (
    SQLiteTranscriptionControlStore,
)
from video_transcript_api.transcriber.usage_repository import NewASRAttempt


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)


def _write_quote_wav(temp_root, task_hash: str):
    path = temp_root / "cloud_quotes" / task_hash / "quote-restart" / "input.wav"
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 800)
    return path


def test_quote_backed_reserved_restart_reuses_one_attempt(tmp_path) -> None:
    temp_root = tmp_path / "temp"
    store = SQLiteTranscriptionControlStore(tmp_path / "control.db")
    task_id = "task-restart"
    media_path = _write_quote_wav(
        temp_root, hashlib.sha256(task_id.encode()).hexdigest()
    )
    media_hash = hashlib.sha256(media_path.read_bytes()).hexdigest()
    media_ref = media_path.relative_to(temp_root).as_posix()
    store.create_link_job(
        task_id=task_id,
        view_token="view-token",
        owner_user_id="user-1",
        source_url="https://example.com/video",
        strategy="cloud",
        payload={"version": 1, "url": "https://example.com/video"},
        now=NOW,
    )
    assert store.claim_next_job("worker-1", now=NOW) is not None
    store.create_quote_and_wait(
        NewCloudQuote(
            task_id=task_id,
            media_ref=media_ref,
            media_sha256=media_hash,
            duration_seconds=Decimal("0.1"),
            billable_seconds=1,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00022"),
            continuation_json='{"version":1}',
        ),
        token="confirmation-token",
        lease_owner="worker-1",
        now=NOW,
    )
    store.confirm_quote_and_handoff(
        task_id, "confirmation-token", Decimal("0.00022"), now=NOW
    )
    store.quote_repository.claim_queued(task_id, "dispatcher-1")
    event = store.reserve_attempt_and_consume_quote(
        NewASRAttempt(
            task_id=task_id,
            model="fun-asr-2025-11-07",
            estimated_quantity=Decimal("0.1"),
            unit_price=Decimal("0.00022"),
            estimated_cost=Decimal("0.000022"),
            owner_key="owner-hash",
            sample_sha256=media_hash,
            platform="generic",
            media_id="media-1",
            output_name="restart-output",
            continuation_json='{"version":1}',
        ),
        now=NOW,
    )
    with sqlite3.connect(store.database.path) as connection:
        connection.execute(
            "UPDATE usage_events SET created_at=? WHERE id=?",
            ((NOW - timedelta(seconds=1)).isoformat(), event.id),
        )

    identified = identify_quote_backed_reserved(store, temp_root, NOW)
    failed = store.usage_repository.fail_orphan_reserved(
        created_before=NOW,
        excluded_event_ids={item.event_id for item in identified.records},
    )

    assert failed == []
    assert [item.event_id for item in identified.records] == [event.id]
    assert media_path.parent in identified.media_roots

    calls = []

    class Provider:
        def submit_reserved_event(self, current_event, snapshot):
            calls.append((current_event, snapshot))
            return "submitted"

    result = resume_quote_backed_reserved_attempt(
        identified.records[0],
        store=store,
        temp_root=temp_root,
        provider=Provider(),
    )

    assert result == "submitted"
    assert len(calls) == 1
    assert calls[0][0].id == event.id
    assert calls[0][1].attempt_no == event.attempt_no
    assert calls[0][1].path.name == "input.wav"
    assert not media_path.exists()
    with sqlite3.connect(store.database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM usage_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 1
