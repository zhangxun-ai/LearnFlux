"""Tests for long-running task progress notifications."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.video_transcript_api.api.services.progress_notifications import (
    due_reminder_marker,
    send_due_progress_reminders,
)


class FakeCache:
    def __init__(self, tasks):
        self.tasks = tasks
        self.marked = []

    def list_active_tasks_for_progress_reminders(self):
        return self.tasks

    def mark_progress_reminder_sent(self, task_id, marker):
        self.marked.append((task_id, marker))


class FakeRouter:
    def __init__(self, channels=None, result=None):
        self.channels = channels or []
        self.result = result if result is not None else {"feishu": True}
        self.calls = []

    def send_text(self, content, channel_name=None, allow_fallback=True):
        self.calls.append(
            {
                "content": content,
                "channel_name": channel_name,
                "allow_fallback": allow_fallback,
            }
        )
        return self.result


def _task(created_at, sent=None):
    return {
        "task_id": "task-1",
        "view_token": "view-1",
        "title": "Demo",
        "url": "https://example.com/video",
        "status": "processing",
        "created_at": created_at,
        "progress_reminders": sent or [],
        "progress": {
            "stage_label": "正在转录音视频",
            "percent": 62,
            "basis": "funasr_server_progress",
            "confidence": "high",
        },
    }


def test_due_reminder_marker_uses_highest_unsent_threshold():
    now = datetime(2026, 6, 8, 10, 40, tzinfo=timezone.utc)
    task = _task(now - timedelta(minutes=35), sent=["10m"])

    marker = due_reminder_marker(task, now=now, thresholds_minutes=[10, 30, 60])

    assert marker == "30m"


def test_send_due_progress_reminders_targets_feishu_only_and_marks_sent():
    now = datetime(2026, 6, 8, 10, 40, tzinfo=timezone.utc)
    cache = FakeCache([_task(now - timedelta(minutes=35), sent=["10m"])])
    router = FakeRouter(channels=[SimpleNamespace(name="feishu")])

    sent_count = send_due_progress_reminders(
        cache_manager=cache,
        router=router,
        now=now,
        thresholds_minutes=[10, 30, 60],
    )

    assert sent_count == 1
    assert cache.marked == [("task-1", "30m")]
    assert router.calls[0]["channel_name"] == "feishu"
    assert router.calls[0]["allow_fallback"] is False
    assert "Demo" in router.calls[0]["content"]
    assert "正在转录音视频" in router.calls[0]["content"]


def test_send_due_progress_reminders_skips_when_feishu_not_configured():
    now = datetime(2026, 6, 8, 10, 40, tzinfo=timezone.utc)
    cache = FakeCache([_task(now - timedelta(minutes=35))])
    router = FakeRouter(channels=[])

    sent_count = send_due_progress_reminders(
        cache_manager=cache,
        router=router,
        now=now,
        thresholds_minutes=[10, 30, 60],
    )

    assert sent_count == 0
    assert cache.marked == []
    assert router.calls == []
