from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import asyncio
import queue

import pytest
from fastapi import BackgroundTasks, HTTPException

from video_transcript_api.api.routes import tasks
from video_transcript_api.api.services import transcription as flow
from video_transcript_api.api.services.post_asr import build_cloud_continuation
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.transcriber.asr_retry_repository import (
    ASRRetryConflict, ASRRetryRepository,
)
from video_transcript_api.transcriber.providers.local_whisper import LocalTranscriptionError


def continuation(task_id="task-1"):
    return build_cloud_continuation(
        task_id=task_id, url="https://weixin.qq.com/sph/example",
        display_url="https://weixin.qq.com/sph/example", platform="wechat_channels",
        media_id="video-1", video_title="Example", author="Author", description="",
        is_generic=False, include_comments=False, comment_limit=100,
    )


def test_retry_claim_is_atomic_and_expires(tmp_path):
    now = [datetime(2026, 10, 3, tzinfo=UTC)]
    repository = ASRRetryRepository(tmp_path / "retry.db", clock=lambda: now[0])
    repository.save("task-1", "audio.m4a", "a" * 64, continuation())
    def claim(_):
        try:
            repository.claim("task-1")
            return True
        except ASRRetryConflict:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(claim, range(8))) == 1
    repository.release("task-1")
    assert repository.claim("task-1").task_id == "task-1"
    now[0] += timedelta(hours=24)
    with pytest.raises(ASRRetryConflict, match="retry_media_expired"):
        repository.claim("task-1")


@pytest.fixture
def retained_task(tmp_path, monkeypatch):
    repository = ASRRetryRepository(tmp_path / "retry.db")
    updates = []
    progress = []
    manager = SimpleNamespace(get_temp_dir=lambda: tmp_path, untrack_file=lambda p: None)
    monkeypatch.setattr(flow, "get_temp_manager", lambda: manager)
    monkeypatch.setattr(flow, "_retry_repository", lambda: repository)
    monkeypatch.setattr(flow, "_is_task_canceled", lambda task: False)
    monkeypatch.setattr(flow, "_safe_update_progress", lambda *a, **kw: progress.append(kw))
    monkeypatch.setattr(flow, "cache_manager", SimpleNamespace(
        save_cache=lambda **kw: True,
        update_task_status=lambda *a, **kw: updates.append((a, kw)),
    ))
    media = tmp_path / "audio.m4a"
    media.write_bytes(b"task-owned audio")
    assert flow._retain_retry_media("task-1", media, continuation()) == media
    return SimpleNamespace(repository=repository, media=media, updates=updates, progress=progress)


def test_quote_failure_retains_media_independently_of_prices(retained_task, monkeypatch):
    flow._record_asr_failure("task-1", flow.CloudASRConfigError("cloud_asr_disabled"))
    assert retained_task.media.exists()
    assert retained_task.progress[-1]["evidence"]["retry_available"] is True
    assert "已保留音频" in retained_task.updates[-1][1]["error_message"]


def test_failed_task_persists_retry_evidence_in_real_cache(tmp_path, monkeypatch):
    """Terminal status must retain the evidence used by the retry buttons."""
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    try:
        task = manager.create_task(
            url="https://weixin.qq.com/sph/example", platform="wechat_channels",
            media_id="video-1",
        )
        task_id = task["task_id"]
        repository = ASRRetryRepository(manager.database)
        media = tmp_path / "audio.m4a"
        media.write_bytes(b"retained retry audio")
        monkeypatch.setattr(flow, "cache_manager", manager)
        monkeypatch.setattr(flow, "_retry_repository", lambda: repository)
        monkeypatch.setattr(flow, "get_temp_manager", lambda: SimpleNamespace(
            get_temp_dir=lambda: tmp_path, untrack_file=lambda path: None,
        ))
        monkeypatch.setattr(flow, "_is_task_canceled", lambda task: False)
        assert flow._retain_retry_media(task_id, media, continuation(task_id)) == media

        flow._record_asr_failure(
            task_id, LocalTranscriptionError("local_transcription_timeout")
        )

        persisted = manager.get_task_by_id(task_id)
        assert persisted["status"] == "failed"
        assert persisted["progress"]["evidence"]["retry_available"] is True
        assert "已保留音频" in persisted["error_message"]
        assert media.exists()
        assert repository.get(task_id).state == "ready"
    finally:
        manager.close()


def test_retry_rejects_changed_media(retained_task):
    retained_task.media.write_bytes(b"changed audio")
    with pytest.raises(ValueError, match="retained_media_changed"):
        flow.claim_asr_retry("task-1")
    assert retained_task.repository.get("task-1").state == "ready"


def test_retention_never_accepts_user_original_or_wrong_task(tmp_path, retained_task):
    external = tmp_path.parent / f"external-{tmp_path.name}.m4a"
    external.write_bytes(b"user original")
    assert flow._retain_retry_media("task-1", external, continuation()) is None
    assert flow._retain_retry_media("wrong-task", retained_task.media, continuation()) is None
    # The original stays untouched; pytest owns its temporary parent.
    assert external.read_bytes() == b"user original"


class ImmediateExecutor:
    def submit(self, fn, *args):
        fn(*args)
        return SimpleNamespace(result=lambda **kw: None)


def setup_local_retry(monkeypatch, *, result=None, error=None):
    called = []
    class LocalTranscriber:
        def __init__(self, **kwargs):
            assert kwargs["strategy"] == "local"
        def transcribe(self, path, name):
            called.append(path)
            if error:
                raise error
            return result
    monkeypatch.setattr(flow, "Transcriber", LocalTranscriber)
    monkeypatch.setattr(flow, "create_downloader", lambda *a: pytest.fail("retry must not download"))
    monkeypatch.setattr(flow, "_pause_for_cloud_confirmation", lambda **kw: pytest.fail("local must not submit cloud"))
    monkeypatch.setattr(flow, "get_local_asr_executor", lambda: ImmediateExecutor())
    monkeypatch.setattr(flow, "get_executor", lambda: ImmediateExecutor())
    monkeypatch.setattr(flow, "get_transcription_concurrency_controller", lambda: SimpleNamespace(
        acquire=lambda *a, **kw: True, release=lambda *a: None,
    ))
    monkeypatch.setattr(flow, "llm_task_queue", queue.Queue())
    return called


def test_local_retry_uses_same_media_and_cleans_after_success(retained_task, monkeypatch):
    called = setup_local_retry(monkeypatch, result={"transcript": "Valid transcript"})
    flow.claim_asr_retry("task-1")
    flow.resume_asr_retry("task-1", strategy="local")
    assert called == [str(retained_task.media)]
    assert not retained_task.media.exists()
    assert flow.llm_task_queue.get_nowait()["transcript"] == "Valid transcript"
    with pytest.raises(ASRRetryConflict, match="retry_media_unavailable"):
        retained_task.repository.get("task-1")


def test_local_retry_failure_keeps_media_for_another_attempt(retained_task, monkeypatch):
    setup_local_retry(monkeypatch, error=LocalTranscriptionError("local_transcription_timeout"))
    flow.claim_asr_retry("task-1")
    flow.resume_asr_retry("task-1", strategy="local")
    assert retained_task.media.exists()
    assert retained_task.repository.get("task-1").state == "ready"
    assert "处理时限" in retained_task.updates[-1][1]["error_message"]


@pytest.fixture
def retry_route(monkeypatch):
    task = {"task_id": "task-1", "owner_user_id": "user-1", "status": "failed"}
    monkeypatch.setattr(tasks.cache_manager, "get_task_by_id", lambda task_id: task)
    monkeypatch.setattr(tasks.cache_manager, "update_task_status", lambda task_id, status, **kw: task.update(status=status))
    monkeypatch.setattr(tasks, "get_transcription_control_database", lambda cache: None)
    monkeypatch.setattr(tasks, "UsageEventRepository", lambda db: SimpleNamespace(find_latest_event_by_task_id=lambda t: None))
    return task


def test_retry_route_queues_only_one_attempt(retry_route, monkeypatch):
    monkeypatch.setattr(tasks, "claim_asr_retry", lambda task: None)
    background = BackgroundTasks()
    user = {"user_id": "user-1"}
    result = asyncio.run(tasks.retry_asr_task("task-1", tasks.ASRRetryRequest(), background, user))
    assert result.code == 202
    assert len(background.tasks) == 1
    assert background.tasks[0].kwargs == {"strategy": "local"}
    with pytest.raises(HTTPException) as error:
        asyncio.run(tasks.retry_asr_task("task-1", tasks.ASRRetryRequest(), BackgroundTasks(), user))
    assert error.value.status_code == 409


@pytest.mark.parametrize("failure", ["false", "exception"])
def test_retry_route_releases_claim_when_status_write_fails(
    retained_task, retry_route, monkeypatch, failure,
):
    def update_status(task_id, status, **kwargs):
        if status == "processing":
            if failure == "exception":
                raise RuntimeError("Status persistence unavailable")
            return False
        retry_route["status"] = status

    monkeypatch.setattr(tasks, "claim_asr_retry", flow.claim_asr_retry)
    monkeypatch.setattr(tasks.cache_manager, "update_task_status", update_status)
    background = BackgroundTasks()

    with pytest.raises(HTTPException) as error:
        asyncio.run(tasks.retry_asr_task(
            "task-1", tasks.ASRRetryRequest(), background, {"user_id": "user-1"},
        ))

    assert error.value.status_code == 503
    assert background.tasks == []
    assert retained_task.repository.get("task-1").state == "ready"
    assert retry_route["status"] == "failed"
    assert flow.claim_asr_retry("task-1").task_id == "task-1"


def test_retry_route_enforces_ownership(retry_route):
    with pytest.raises(HTTPException) as error:
        asyncio.run(tasks.retry_asr_task("task-1", tasks.ASRRetryRequest(), BackgroundTasks(), {"user_id": "other"}))
    assert error.value.status_code == 403


@pytest.mark.parametrize("status", ["reserved", "submitting", "submission_unknown", "submitted", "polling_unknown", "succeeded"])
def test_retry_never_duplicates_a_cloud_submission(retry_route, monkeypatch, status):
    monkeypatch.setattr(tasks, "UsageEventRepository", lambda db: SimpleNamespace(
        find_latest_event_by_task_id=lambda t: SimpleNamespace(remote_status=status)
    ))
    monkeypatch.setattr(tasks, "claim_asr_retry", lambda task: pytest.fail("cloud recovery must keep original attempt"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(tasks.retry_asr_task("task-1", tasks.ASRRetryRequest(), BackgroundTasks(), {"user_id": "user-1"}))
    assert error.value.status_code == 409
