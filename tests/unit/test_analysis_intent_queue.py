"""Queue propagation tests for source type and analysis intent."""

import asyncio

import pytest

from video_transcript_api.api.services import transcription


class _OneItemQueue:
    def __init__(self, item):
        self.item = item
        self.reads = 0
        self.done = 0

    async def get(self):
        self.reads += 1
        if self.reads == 1:
            return self.item
        raise asyncio.CancelledError

    def task_done(self):
        self.done += 1


class _CompletedFuture:
    def result(self):
        return {"status": "success"}

    def add_done_callback(self, callback):
        callback(self)


class _CapturingExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return _CompletedFuture()


def test_process_task_queue_forwards_source_type_and_analysis_intent(monkeypatch):
    queue = _OneItemQueue(
        {
            "id": "task-1",
            "url": "https://mp.weixin.qq.com/s/example",
            "source_type": "wechat_mp_article",
            "analysis_intent": "deep_learning",
        }
    )
    executor = _CapturingExecutor()
    monkeypatch.setattr(transcription, "task_queue", queue)
    monkeypatch.setattr(transcription, "executor", executor)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(
        transcription.cache_manager,
        "update_task_status",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        transcription,
        "_safe_update_progress",
        lambda *args, **kwargs: True,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(transcription.process_task_queue())

    _, _, kwargs = executor.calls[0]
    assert kwargs["source_type"] == "wechat_mp_article"
    assert kwargs["analysis_intent"] == "deep_learning"
    assert queue.done == 1
