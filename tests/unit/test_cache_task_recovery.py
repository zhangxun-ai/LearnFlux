"""Unit tests for CacheManager task-status guards and crash recovery.

Covers:
- update_task_status terminal-state stickiness (success/failed not clobbered)
- force=True explicit reset (recalibrate path)
- recover_orphaned_tasks() sweep on startup
- calibrating status round-trips

All console output must be in English only (no emoji, no Chinese).
"""

import pytest

from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.utils.task_status import TaskStatus


@pytest.fixture
def cm(tmp_path):
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    yield manager
    manager.close()


def _new_task(cm, url="https://example.com/v1"):
    return cm.create_task(url=url)["task_id"]


class TestCalibratingStatus:
    def test_calibrating_round_trips(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.CALIBRATING)
        assert cm.get_task_by_id(task_id)["status"] == "calibrating"


class TestErrorMessage:
    def test_error_message_persists_on_failed(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.FAILED, error_message="ASR timeout")
        assert cm.get_task_by_id(task_id)["error_message"] == "ASR timeout"


class TestTerminalStickiness:
    """success / failed / canceled are terminal and must not be overwritten by late writes."""

    def test_success_not_overwritten_by_processing(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.SUCCESS)
        # A slow/stale worker tries to regress the state.
        cm.update_task_status(task_id, TaskStatus.PROCESSING)
        assert cm.get_task_by_id(task_id)["status"] == "success"

    def test_success_not_overwritten_by_failed(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.SUCCESS)
        cm.update_task_status(task_id, TaskStatus.FAILED)
        assert cm.get_task_by_id(task_id)["status"] == "success"

    def test_failed_not_overwritten_by_success(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.FAILED)
        cm.update_task_status(task_id, TaskStatus.SUCCESS)
        assert cm.get_task_by_id(task_id)["status"] == "failed"

    def test_canceled_not_overwritten_by_processing(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.CANCELED)
        cm.update_task_status(task_id, TaskStatus.PROCESSING)
        assert cm.get_task_by_id(task_id)["status"] == "canceled"

    def test_non_terminal_transitions_allowed(self, cm):
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.PROCESSING)
        cm.update_task_status(task_id, TaskStatus.CALIBRATING)
        cm.update_task_status(task_id, TaskStatus.SUCCESS)
        assert cm.get_task_by_id(task_id)["status"] == "success"

    def test_force_overwrites_terminal(self, cm):
        """recalibrate explicitly resets a finished task back to processing."""
        task_id = _new_task(cm)
        cm.update_task_status(task_id, TaskStatus.SUCCESS)
        cm.update_task_status(task_id, TaskStatus.PROCESSING, force=True)
        assert cm.get_task_by_id(task_id)["status"] == "processing"


class TestRecoverOrphanedTasks:
    """On boot, in-flight tasks (lost with the in-memory queues) are failed."""

    def test_sweeps_non_terminal_to_failed(self, cm):
        queued = _new_task(cm, "https://example.com/q")
        processing = _new_task(cm, "https://example.com/p")
        calibrating = _new_task(cm, "https://example.com/c")
        cm.update_task_status(processing, TaskStatus.PROCESSING)
        cm.update_task_status(calibrating, TaskStatus.CALIBRATING)

        recovered = cm.recover_orphaned_tasks()

        assert recovered == 3
        assert cm.get_task_by_id(queued)["status"] == "failed"
        assert cm.get_task_by_id(processing)["status"] == "failed"
        assert cm.get_task_by_id(calibrating)["status"] == "failed"

    def test_terminal_tasks_untouched(self, cm):
        done = _new_task(cm, "https://example.com/done")
        failed = _new_task(cm, "https://example.com/failed")
        cm.update_task_status(done, TaskStatus.SUCCESS)
        cm.update_task_status(failed, TaskStatus.FAILED)

        recovered = cm.recover_orphaned_tasks()

        assert recovered == 0
        assert cm.get_task_by_id(done)["status"] == "success"
        assert cm.get_task_by_id(failed)["status"] == "failed"

    def test_sets_completed_at_on_recovered(self, cm):
        processing = _new_task(cm, "https://example.com/p2")
        cm.update_task_status(processing, TaskStatus.PROCESSING)
        cm.recover_orphaned_tasks()
        assert cm.get_task_by_id(processing)["completed_at"] is not None

    def test_protected_cloud_task_is_excluded_from_startup_and_stale_sweeps(self, cm):
        protected = _new_task(cm, "https://example.com/cloud")
        ordinary = _new_task(cm, "https://example.com/ordinary")
        cm.update_task_status(protected, TaskStatus.PROCESSING)
        cm.update_task_status(ordinary, TaskStatus.PROCESSING)

        assert cm.recover_orphaned_tasks(protected_task_ids={protected}) == 1
        assert cm.get_task_by_id(protected)["status"] == "processing"
        assert cm.get_task_by_id(ordinary)["status"] == "failed"

        self._set_last_heartbeat(cm, protected, "2026-07-12 08:00:00")
        assert cm.recover_stale_tasks(
            30,
            now="2026-07-12 10:00:00",
            protected_task_ids={protected},
        ) == 0

    @staticmethod
    def _set_last_heartbeat(cm, task_id, value):
        with cm._get_cursor() as cursor:
            cursor.execute(
                "UPDATE task_status SET last_heartbeat_at = ? WHERE task_id = ?",
                (value, task_id),
            )


class TestRecoverStaleTasks:
    """Runtime recovery for tasks that stop sending progress heartbeats."""

    def _set_last_heartbeat(self, cm, task_id, value):
        with cm._get_cursor() as cursor:
            cursor.execute(
                "UPDATE task_status SET last_heartbeat_at = ? WHERE task_id = ?",
                (value, task_id),
            )

    def test_recovers_non_terminal_tasks_with_stale_heartbeat(self, cm):
        processing = _new_task(cm, "https://example.com/stale-processing")
        fresh = _new_task(cm, "https://example.com/fresh-processing")
        done = _new_task(cm, "https://example.com/done-processing")
        cm.update_task_status(processing, TaskStatus.PROCESSING)
        cm.update_task_status(fresh, TaskStatus.PROCESSING)
        cm.update_task_status(done, TaskStatus.SUCCESS)
        self._set_last_heartbeat(cm, processing, "2026-07-12 08:00:00")
        self._set_last_heartbeat(cm, fresh, "2026-07-12 09:50:00")
        self._set_last_heartbeat(cm, done, "2026-07-12 08:00:00")

        recovered = cm.recover_stale_tasks(
            max_age_minutes=30,
            now="2026-07-12 10:00:00",
        )

        stale_info = cm.get_task_by_id(processing)
        assert recovered == 1
        assert stale_info["status"] == "failed"
        assert stale_info["completed_at"] is not None
        assert stale_info["error_message"] == "任务超过 30 分钟没有进度心跳，已自动标记失败"
        assert stale_info["progress"]["basis"] == "task_timeout"
        assert stale_info["progress"]["evidence"]["timeout_minutes"] == 30
        assert cm.get_task_by_id(fresh)["status"] == "processing"
        assert cm.get_task_by_id(done)["status"] == "success"

    def test_progress_update_refreshes_last_heartbeat(self, cm):
        task_id = _new_task(cm, "https://example.com/progress-refresh")
        self._set_last_heartbeat(cm, task_id, "2026-07-12 08:00:00")

        cm.update_task_progress(
            task_id,
            stage="downloading",
            stage_label="Downloading",
            fraction=0.2,
        )

        task_info = cm.get_task_by_id(task_id)
        assert task_info["last_heartbeat_at"] != "2026-07-12 08:00:00"
