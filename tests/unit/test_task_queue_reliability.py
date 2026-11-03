"""Real scheduling and durable recovery contracts without external services."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import threading
from unittest.mock import MagicMock

import pytest

from video_transcript_api.api.services.task_recovery import (
    enqueue_recovered_tasks,
    prepare_task_recovery,
)
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.transcriber.control_store import SQLiteTranscriptionControlStore


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_out_of_order_failure_stays_with_its_task_and_waiting_work_is_bounded(monkeypatch, raises):
    from video_transcript_api.api.services import transcription as flow

    pending = asyncio.Queue(maxsize=2)
    pool = ThreadPoolExecutor(max_workers=2)
    cache = MagicMock()
    entered = {key: threading.Event() for key in ("a", "b", "c")}
    release = threading.Event()

    def process(task_id, *_args, **_kwargs):
        entered[task_id].set()
        release.wait(timeout=3)
        if task_id == "a" and raises:
            raise ValueError("a failed")
        return {"status": "failed" if task_id == "a" else "success", "message": "a failed"}

    monkeypatch.setattr(flow, "task_queue", pending)
    monkeypatch.setattr(flow, "executor", pool)
    monkeypatch.setattr(flow, "config", {"concurrent": {"max_workers": 2}})
    monkeypatch.setattr(flow, "cache_manager", cache)
    monkeypatch.setattr(flow, "_is_task_canceled", lambda _id: False)
    monkeypatch.setattr(flow, "_safe_update_progress", lambda *_a, **_kw: None)
    monkeypatch.setattr(flow, "process_transcription", process)
    monkeypatch.setattr(flow, "get_notification_router", MagicMock())
    for key in ("a", "b"):
        pending.put_nowait({"id": key, "url": "https://example.com/" + key})
    running = asyncio.create_task(flow.process_task_queue())
    try:
        assert await asyncio.to_thread(entered["a"].wait, 1)
        assert await asyncio.to_thread(entered["b"].wait, 1)
        pending.put_nowait({"id": "c", "url": "https://example.com/c"})
        await asyncio.sleep(0.02)
        assert not entered["c"].is_set()
        assert pending.qsize() == 1
        started = [call.args[0] for call in cache.update_task_status.call_args_list]
        assert started == ["a", "b"]
        release.set()
        await asyncio.wait_for(pending.join(), timeout=2)
        failed = [call.args[0] for call in cache.update_task_status.call_args_list
                  if call.args[1] == "failed"]
        assert failed == ["a"]
        assert entered["c"].is_set()
    finally:
        release.set()
        running.cancel()
        with suppress(asyncio.CancelledError):
            await running
        pool.shutdown(wait=True)


@pytest.fixture(params=["legacy", "control_store"])
def manager(tmp_path, request):
    store = SQLiteTranscriptionControlStore(tmp_path / "control.db") if request.param == "control_store" else None
    cache = CacheManager(str(tmp_path / "cache"), database=store.database if store else None)
    if store:
        cache.set_task_status_repository(store)
    yield cache
    cache.close()


def persist(cache, *, strategy="local", status="queued", owner="owner", **options):
    task_id = cache.create_task(url="https://example.com/" + strategy + status,
                                owner_user_id=owner)["task_id"]
    task = {"id": task_id, "url": "https://example.com/video", "transcription_strategy": strategy,
            "api_key": "must-not-persist", "user_info": {"api_key": "must-not-persist"},
            "notification_webhooks": {"feishu": "must-not-persist"}, **options}
    cache.save_task_request(task)
    cache.update_task_status(task_id, status)
    return task_id


def users(enabled=True):
    return MagicMock(get_user_by_id=MagicMock(return_value={
        "user_id": "owner", "enabled": enabled, "feishu_webhook": "current-owner-hook",
    }))


def test_recovery_preserves_safe_options_and_reuses_task_identity(manager):
    task_id = persist(manager, status="calibrating", preserve_source_file=True,
                      metadata_override={"title": "Original", "api_key": "must-not-persist"})
    with manager._get_cursor() as cursor:
        cursor.execute("SELECT payload_json FROM task_requests WHERE task_id=?", (task_id,))
        payload = cursor.fetchone()[0]
    assert "must-not-persist" not in payload
    result = prepare_task_recovery(manager, users())
    assert [task["id"] for task in result] == [task_id]
    assert result[0]["preserve_source_file"] is True
    assert result[0]["metadata_override"] == {"title": "Original"}
    assert result[0]["notification_webhooks"] == {"feishu": "current-owner-hook"}
    assert manager.get_task_by_id(task_id)["status"] == "queued"
    assert manager.recover_orphaned_tasks(protected_task_ids={task_id}) == 0


def test_paid_terminal_disabled_and_protected_work_are_not_replayed(manager):
    persist(manager, strategy="cloud")
    persist(manager, status="success")
    persist(manager, status="canceled")
    safe = persist(manager, status="processing")
    assert prepare_task_recovery(manager, users(False)) == []
    assert prepare_task_recovery(manager, users(), protected_task_ids={safe}) == []


def test_recovery_does_not_restore_retired_wechat_notifications(manager):
    persist(manager, notification_channel="wechat")
    user_manager = users()
    user_manager.get_user_by_id.return_value["wechat_webhook"] = "retired-owner-hook"
    recovered = prepare_task_recovery(manager, user_manager)
    assert len(recovered) == 1
    assert "wechat_webhook" not in recovered[0]
    assert recovered[0]["notification_webhooks"] == {"feishu": "current-owner-hook"}
    assert recovered[0]["notification_channel"] is None
    assert "retired-owner-hook" not in str(recovered[0])


def test_recovery_is_bounded_and_suppresses_request_override_notifications(manager):
    task_id = persist(manager, restore_notifications=False)
    for _ in range(3):
        result = prepare_task_recovery(manager, users())
        assert len(result) == 1
        assert result[0]["notification_webhooks"] == {}
    assert prepare_task_recovery(manager, users()) == []
    assert manager.recover_orphaned_tasks() == 1
    assert manager.get_task_by_id(task_id)["status"] == "failed"


def test_execution_intent_survives_a_real_cache_reopen(tmp_path):
    directory = str(tmp_path / "cache")
    first = CacheManager(directory)
    task_id = persist(first, status="processing", include_comments=True, comment_limit=20)
    first.close()
    second = CacheManager(directory)
    try:
        recovered = prepare_task_recovery(second, users())
        assert len(recovered) == 1
        assert recovered[0]["id"] == task_id
        assert recovered[0]["include_comments"] is True
        assert recovered[0]["comment_limit"] == 20
        assert second.get_task_by_id(task_id)["status"] == "queued"
    finally:
        second.close()


def test_local_recovery_resumes_verified_retained_media_before_download(monkeypatch):
    from types import SimpleNamespace
    from video_transcript_api.api.services import transcription as flow

    retry = MagicMock()
    retry.get.return_value = SimpleNamespace(
        media_ref="owned/audio.wav", media_sha256="hash", state="claimed"
    )
    resume = MagicMock()
    process = MagicMock()
    monkeypatch.setattr(flow, "_is_task_canceled", lambda _id: False)
    monkeypatch.setattr(flow, "cache_manager", MagicMock())
    monkeypatch.setattr(flow, "_safe_update_progress", MagicMock())
    monkeypatch.setattr(flow, "_retry_repository", lambda: retry)
    monkeypatch.setattr(flow, "_verified_retained_media", MagicMock())
    monkeypatch.setattr(flow, "claim_asr_retry", MagicMock())
    monkeypatch.setattr(flow, "resume_asr_retry", resume)
    monkeypatch.setattr(flow, "process_transcription", process)
    flow._execute_queued_task({"id": "a", "url": "https://example.com", "recovered": True})
    retry.release.assert_called_once_with("a")
    resume.assert_called_once_with("a", strategy="local")
    process.assert_not_called()


@pytest.mark.asyncio
async def test_recovered_requests_obey_the_same_queue_capacity():
    pending = asyncio.Queue(maxsize=1)
    feeder = asyncio.create_task(enqueue_recovered_tasks([{"id": "a"}, {"id": "b"}], pending))
    await asyncio.sleep(0)
    assert pending.qsize() == 1
    assert not feeder.done()
    assert pending.get_nowait()["id"] == "a"
    pending.task_done()
    await feeder
    assert pending.get_nowait()["id"] == "b"
