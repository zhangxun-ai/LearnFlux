"""Integration tests: the LLM stage owns the terminal task status.

Regression coverage for the silent-failure bug: a NORMAL (non-recalibrate)
task's LLM completion/failure must write success/failed to the DB. Before the
fix, only calibrate_only tasks updated terminal status, so normal LLM failures
were silent and the task stayed stuck.

All console output must be in English only (no emoji, no Chinese).
"""

import pytest
from unittest.mock import patch, MagicMock

from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.utils.task_status import TaskStatus
from src.video_transcript_api.api.services import llm_ops


@pytest.fixture
def cm(tmp_path):
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    yield manager
    manager.close()


def _calibrating_task(cm):
    task_id = cm.create_task(url="https://example.com/v1")["task_id"]
    cm.update_task_status(task_id, TaskStatus.CALIBRATING)
    return task_id


def _llm_task(task_id):
    return {
        "task_id": task_id,
        "url": "https://example.com/v1",
        "display_url": "https://example.com/v1",
        "platform": "youtube",
        "media_id": "vid1",
        "video_title": "Demo",
        "author": "Alice",
        "description": "",
        "transcript": "hello world",
        "use_speaker_recognition": False,
        "is_generic": False,
        "wechat_webhook": None,
        "notification_channel": None,
        "notification_webhooks": {},
    }


def _patches(cm, coordinator, build_result_dict=None):
    """Patch llm_ops module globals to isolate the state-transition logic."""
    if build_result_dict is None:
        build_result_dict = lambda r: {}
    return [
        patch.object(llm_ops, "cache_manager", cm),
        patch.object(llm_ops, "llm_coordinator", coordinator),
        # _handle_llm_task calls llm_task_queue.task_done() in finally; isolate it.
        patch.object(llm_ops, "llm_task_queue", MagicMock()),
        patch.object(llm_ops, "_build_result_dict", build_result_dict),
        patch.object(llm_ops, "_save_llm_results", MagicMock()),
        patch.object(llm_ops, "_send_notification", MagicMock()),
        patch.object(llm_ops, "get_notification_router", lambda: MagicMock()),
        patch.object(llm_ops, "_generate_title_if_needed", lambda t, title, tr: title),
        patch.object(llm_ops, "_prepare_llm_content", lambda t, tr, spk: "content"),
    ]


class TestLlmTerminalWriteback:
    def test_normal_task_success_sets_db_success(self, cm):
        task_id = _calibrating_task(cm)
        coordinator = MagicMock()
        coordinator.process.return_value = MagicMock()

        ctxs = _patches(cm, coordinator)
        for c in ctxs:
            c.start()
        try:
            llm_ops._handle_llm_task(_llm_task(task_id))
        finally:
            for c in ctxs:
                c.stop()

        assert cm.get_task_by_id(task_id)["status"] == "success"

    def test_normal_task_llm_failure_sets_db_failed(self, cm):
        # R2: the bug — a normal task's LLM failure must surface as failed.
        task_id = _calibrating_task(cm)
        coordinator = MagicMock()
        coordinator.process.side_effect = RuntimeError("boom")

        ctxs = _patches(cm, coordinator)
        for c in ctxs:
            c.start()
        try:
            llm_ops._handle_llm_task(_llm_task(task_id))
        finally:
            for c in ctxs:
                c.stop()

        row = cm.get_task_by_id(task_id)
        assert row["status"] == "failed"
        assert "boom" in (row["error_message"] or "")

    def test_normal_task_missing_required_summary_sets_db_failed(self, cm):
        task_id = _calibrating_task(cm)
        coordinator = MagicMock()
        coordinator.config.min_summary_threshold = 500
        coordinator.process.return_value = {
            "calibrated_text": "x" * 600,
            "summary_text": None,
            "stats": {},
            "models_used": {},
        }

        ctxs = _patches(cm, coordinator, llm_ops._build_result_dict)
        for c in ctxs:
            c.start()
        try:
            llm_ops._handle_llm_task(_llm_task(task_id))
        finally:
            for c in ctxs:
                c.stop()

        row = cm.get_task_by_id(task_id)
        assert row["status"] == "failed"
        assert "summary generation returned empty" in (row["error_message"] or "")

    def test_recalibrate_regenerate_summary_forces_summary_backfill(self, cm):
        task_id = _calibrating_task(cm)
        coordinator = MagicMock()
        coordinator.process.return_value = {
            "calibrated_text": "calibrated",
            "summary_text": "fresh summary",
            "stats": {},
            "models_used": {},
        }
        save_results = MagicMock()
        task = {
            **_llm_task(task_id),
            "calibrate_only": True,
            "regenerate_summary": True,
        }

        with patch.object(llm_ops, "cache_manager", cm), patch.object(
            llm_ops, "llm_coordinator", coordinator
        ), patch.object(llm_ops, "llm_task_queue", MagicMock()), patch.object(
            llm_ops, "_save_llm_results", save_results
        ), patch.object(llm_ops, "_send_notification", MagicMock()), patch.object(
            llm_ops, "get_notification_router", lambda: MagicMock()
        ), patch.object(
            llm_ops, "_generate_title_if_needed", lambda t, title, tr: title
        ), patch.object(
            llm_ops, "_prepare_llm_content", lambda t, tr, spk: "content"
        ):
            llm_ops._handle_llm_task(task)

        assert coordinator.process.call_args.kwargs["skip_summary"] is False
        assert save_results.call_args.kwargs["summary_backfill"] is True
        assert cm.get_task_by_id(task_id)["status"] == "success"

    def test_document_fallback_quality_survives_progress_and_terminal_state(self, cm):
        task_id = _calibrating_task(cm)
        quality = {
            "mode": "fallback",
            "reasons": ["low_printable_ratio"],
            "metrics": {"printable_ratio": 0.9},
            "canonical_text": "must not persist",
        }
        coordinator = MagicMock()

        def process(**kwargs):
            kwargs["progress_callback"](1, 2)
            kwargs["progress_callback"](2, 2)
            return {
                "calibrated_text": "calibrated text",
                "summary_text": "summary text",
                "stats": {},
                "models_used": {},
            }

        coordinator.process.side_effect = process
        progress_updates = []
        original_update = cm.update_task_progress

        def track_progress(*args, **kwargs):
            result = original_update(*args, **kwargs)
            progress_updates.append(result)
            return result

        task = {**_llm_task(task_id), "document_quality": quality}
        ctxs = _patches(cm, coordinator, llm_ops._build_result_dict)
        ctxs.append(patch.object(cm, "update_task_progress", side_effect=track_progress))
        for context in ctxs:
            context.start()
        try:
            llm_ops._handle_llm_task(task)
        finally:
            for context in ctxs:
                context.stop()

        assert progress_updates
        for progress in progress_updates:
            document_quality = progress["evidence"]["document_quality"]
            assert set(document_quality) == {"mode", "reasons", "metrics"}
            assert "canonical_text" not in repr(progress["evidence"])
        calibration = [item for item in progress_updates if item["stage"] == "calibrating"]
        assert calibration[-1]["evidence"]["completed_segments"] == 2
        assert calibration[-1]["stage_label"] == "检测到提取质量问题，正在进行完整校对"
        terminal = cm.get_task_by_id(task_id)["progress"]
        assert terminal["evidence"]["analysis_mode"] == "document_fallback"
        assert terminal["evidence"]["quality"]["reasons"] == ["low_printable_ratio"]
        assert "canonical_text" not in repr(terminal["evidence"])
