from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from video_transcript_api.transcriber.control_store import (
    ControlStoreConflict,
    SQLiteTranscriptionControlStore,
)
from video_transcript_api.cache.cache_manager import CacheManager


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)


def _store(tmp_path) -> SQLiteTranscriptionControlStore:
    return SQLiteTranscriptionControlStore(tmp_path / "control.db", lease_seconds=60)


def test_job_claim_heartbeat_expiry_and_terminal_stickiness(tmp_path) -> None:
    store = _store(tmp_path)
    created = store.create_link_job(
        task_id="task-1",
        view_token="view-1",
        owner_user_id="user-1",
        source_url="https://example.com/video",
        strategy="cloud",
        payload={"version": 1, "url": "https://example.com/video"},
        now=NOW,
    )

    first = store.claim_next_job("worker-a", now=NOW)
    assert first is not None and first.task_id == created.task_id
    assert store.claim_next_job("worker-b", now=NOW) is None
    assert store.heartbeat_job("task-1", "worker-a", now=NOW + timedelta(seconds=30))
    assert store.claim_next_job("worker-b", now=NOW + timedelta(seconds=80)) is None

    reclaimed = store.claim_next_job("worker-b", now=NOW + timedelta(seconds=91))
    assert reclaimed is not None and reclaimed.task_id == "task-1"
    assert reclaimed.attempt_count == 2
    assert store.complete_job("task-1", "worker-b", now=NOW + timedelta(seconds=92))
    assert store.claim_next_job("worker-c", now=NOW + timedelta(minutes=3)) is None
    assert store.get_job("task-1").status == "completed"


def test_upload_session_consumption_is_owner_scoped_and_idempotent(tmp_path) -> None:
    store = _store(tmp_path)
    session = store.create_upload_session(
        session_id="upload-1",
        owner_user_id="user-1",
        object_key="source/opaque-1",
        max_bytes=100,
        expires_at=NOW + timedelta(minutes=10),
        now=NOW,
    )

    with pytest.raises(ControlStoreConflict, match="upload_owner_mismatch"):
        store.consume_upload_session_and_create_job(
            session_id=session.id,
            owner_user_id="user-2",
            actual_bytes=10,
            task_id="task-wrong",
            view_token="view-wrong",
            strategy="cloud",
            payload={"version": 1},
            now=NOW,
        )

    first = store.consume_upload_session_and_create_job(
        session_id=session.id,
        owner_user_id="user-1",
        actual_bytes=10,
        task_id="task-2",
        view_token="view-2",
        strategy="cloud",
        payload={"version": 1, "filename": "lesson.mp4"},
        now=NOW,
    )
    second = store.consume_upload_session_and_create_job(
        session_id=session.id,
        owner_user_id="user-1",
        actual_bytes=10,
        task_id="ignored-retry-id",
        view_token="ignored-retry-view",
        strategy="cloud",
        payload={"version": 1, "filename": "lesson.mp4"},
        now=NOW + timedelta(seconds=1),
    )

    assert second.task_id == first.task_id == "task-2"
    assert store.get_upload_session(session.id).status == "consumed"
    assert store.get_task("task-2")["owner_user_id"] == "user-1"


def test_expired_or_oversized_upload_does_not_create_job(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_upload_session(
        session_id="expired",
        owner_user_id="user-1",
        object_key="source/opaque-2",
        max_bytes=5,
        expires_at=NOW + timedelta(seconds=1),
        now=NOW,
    )

    with pytest.raises(ControlStoreConflict, match="upload_session_expired"):
        store.consume_upload_session_and_create_job(
            session_id="expired",
            owner_user_id="user-1",
            actual_bytes=5,
            task_id="task-expired",
            view_token="view-expired",
            strategy="cloud",
            payload={"version": 1},
            now=NOW + timedelta(seconds=2),
        )
    assert store.get_job("task-expired") is None

    active = store.create_upload_session(
        session_id="oversized",
        owner_user_id="user-1",
        object_key="source/opaque-3",
        max_bytes=5,
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    with pytest.raises(ControlStoreConflict, match="upload_too_large"):
        store.consume_upload_session_and_create_job(
            session_id=active.id,
            owner_user_id="user-1",
            actual_bytes=6,
            task_id="task-oversized",
            view_token="view-oversized",
            strategy="cloud",
            payload={"version": 1},
            now=NOW,
        )
    assert store.get_job("task-oversized") is None


def test_durable_job_payload_rejects_local_paths(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ControlStoreConflict, match="invalid_job_payload"):
        store.create_link_job(
            task_id="task-local-path",
            view_token="view-local-path",
            owner_user_id="user-1",
            source_url="https://example.com/video",
            strategy="cloud",
            payload={"version": 1, "local_path": "/private/media.mp4"},
            now=NOW,
        )

    assert store.get_job("task-local-path") is None


def test_cache_manager_uses_explicit_task_store_without_changing_local_default(
    tmp_path,
) -> None:
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    store = _store(tmp_path)
    manager.set_task_status_repository(store)

    created = manager.create_task(
        url="https://example.com/delegated",
        platform="generic",
        media_id="delegated-1",
        owner_user_id="user-1",
    )
    manager.update_task_status(created["task_id"], "processing", title="Delegated")
    progress = manager.update_task_progress(
        created["task_id"],
        stage="acquiring_content",
        stage_label="Acquiring content",
        fraction=0.1,
    )

    task = manager.get_task_by_id(created["task_id"])
    task_by_view = manager.get_task_by_view_token(created["view_token"])
    assert task is not None
    assert task["status"] == "processing"
    assert task["title"] == "Delegated"
    assert task["owner_user_id"] == "user-1"
    assert progress["stage"] == "acquiring_content"
    assert task_by_view is not None
    assert task_by_view["task_id"] == created["task_id"]
    assert task_by_view["progress_json"]["stage"] == "acquiring_content"


def test_no_transcript_is_terminal_in_the_explicit_task_store(tmp_path) -> None:
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    manager.set_task_status_repository(_store(tmp_path))
    task = manager.create_task(
        url="local://collection-source/media-1/silent.mp4",
        platform="generic",
        media_id="media-1",
    )

    manager.update_task_status(
        task["task_id"], "no_transcript", error_message="未检测到可转录语音"
    )
    manager.update_task_progress(task["task_id"], stage="processing")

    stored = manager.get_task_by_id(task["task_id"])
    assert stored["status"] == "no_transcript"
    assert stored["progress_json"]["stage"] == "no_transcript"
