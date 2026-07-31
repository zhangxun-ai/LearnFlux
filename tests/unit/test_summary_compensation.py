"""Regression: bounded summary-only retries stay non-blocking.

All console output must be in English only.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.video_transcript_api.api.services import llm_ops
from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.utils.task_status import TaskStatus


def test_missing_summary_schedules_first_bounded_retry(tmp_path):
    cm = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_id = cm.create_task(url="https://example.com/v1")["task_id"]
    cm.update_task_status(task_id, TaskStatus.CALIBRATING)

    coordinator = MagicMock()
    coordinator.config.min_summary_threshold = 500
    coordinator.process.return_value = {
        "calibrated_text": "x" * 600,
        "summary_text": None,
        "stats": {},
        "models_used": {},
    }

    schedule_retry = MagicMock(return_value=60)
    with patch.object(llm_ops, "cache_manager", cm), patch.object(
        llm_ops, "llm_coordinator", coordinator
    ), patch.object(llm_ops, "llm_task_queue", MagicMock()), patch.object(
        llm_ops, "_save_llm_results", MagicMock()
    ), patch.object(llm_ops, "_send_notification", MagicMock()), patch.object(
        llm_ops, "get_notification_router", lambda: MagicMock()
    ), patch.object(
        llm_ops, "_generate_title_if_needed", lambda t, title, tr: title
    ), patch.object(
        llm_ops, "_prepare_llm_content", lambda t, tr, spk: "content"
    ), patch.object(
        llm_ops, "_schedule_summary_retry", schedule_retry, create=True
    ):
        llm_ops._handle_llm_task(
            {
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
                "source_type": "wechat_mp_article",
                "analysis_intent": "deep_learning",
            }
        )

    row = cm.get_task_by_id(task_id)
    assert row["status"] == "success"
    evidence = (row.get("progress") or {}).get("evidence") or {}
    assert evidence.get("summary_pending") is True
    assert evidence.get("summary_fallback_exhausted") is True
    assert evidence.get("summary_retry_in_seconds") == 60
    assert evidence.get("summary_retry_scheduled") is True
    assert evidence.get("summary_retry_attempt") == 1
    schedule_retry.assert_called_once()
    assert (row.get("progress") or {}).get("stage_label") == (
        "AI 解读失败（已切换备用模型）"
    )
    assert coordinator.process.call_args.kwargs["summary_profile"] == "deep_learning"
    cm.close()


def test_summary_retry_uses_cached_calibration_without_recalibrating(tmp_path):
    cm = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = cm.create_task(
        url="https://example.com/v2",
        platform="youtube",
        media_id="vid2",
    )
    task_id = task["task_id"]
    cm.save_cache(
        platform="youtube",
        url="https://example.com/v2",
        media_id="vid2",
        use_speaker_recognition=False,
        transcript_data="raw transcript",
        transcript_type="capswriter",
        title="Demo",
        author="Alice",
    )
    cm.save_llm_result(
        platform="youtube",
        media_id="vid2",
        use_speaker_recognition=False,
        llm_type="calibrated",
        content="calibrated transcript " * 40,
    )
    cm.update_task_status(
        task_id,
        TaskStatus.SUCCESS,
        platform="youtube",
        media_id="vid2",
        terminal_evidence={"summary_pending": True},
    )

    coordinator = MagicMock()
    coordinator.config.get_models.return_value = {
        "summary_model": "deepseek-v4-flash",
        "summary_reasoning_effort": "high",
    }
    coordinator.summary_processor.process.return_value = "recovered summary " * 8

    with patch.object(llm_ops, "cache_manager", cm), patch.object(
        llm_ops, "llm_coordinator", coordinator
    ), patch.object(llm_ops, "llm_task_queue", MagicMock()), patch.object(
        llm_ops, "get_notification_router", lambda: MagicMock()
    ):
        llm_ops._handle_llm_task(
            {
                "task_id": task_id,
                "url": "https://example.com/v2",
                "display_url": "https://example.com/v2",
                "platform": "youtube",
                "media_id": "vid2",
                "video_title": "Demo",
                "author": "Alice",
                "description": "",
                "transcript": "raw transcript",
                "use_speaker_recognition": False,
                "summary_only_retry": True,
                "summary_retry_attempt": 1,
                "skip_notification": True,
                "source_type": "wechat_mp_article",
                "analysis_intent": "deep_learning",
            }
        )

    coordinator.process.assert_not_called()
    assert coordinator.summary_processor.process.call_args.kwargs[
        "summary_profile"
    ] == "deep_learning"
    cache = cm.get_cache(
        "youtube",
        "vid2",
        use_speaker_recognition=False,
    )
    assert cache["llm_summary"].startswith("recovered summary")
    row = cm.get_task_by_id(task_id)
    evidence = (row.get("progress") or {}).get("evidence") or {}
    assert evidence.get("summary_pending") is False
    assert evidence.get("summary_retry_attempt") == 1
    cm.close()


def test_summary_retry_keeps_pending_when_summary_persistence_fails():
    cm = MagicMock()
    cm.get_cache.return_value = {"llm_calibrated": "calibrated " * 80}
    cm.get_task_by_id.return_value = {
        "progress": {"evidence": {"summary_pending": True}}
    }
    cm.save_llm_result.return_value = False

    coordinator = MagicMock()
    coordinator.config.get_models.return_value = {
        "summary_model": "deepseek-v4-flash",
        "summary_reasoning_effort": "high",
    }
    coordinator.summary_processor.process.return_value = "summary " * 20
    schedule_retry = MagicMock(return_value=300)

    with patch.object(llm_ops, "cache_manager", cm), patch.object(
        llm_ops, "llm_coordinator", coordinator
    ), patch.object(llm_ops, "_schedule_summary_retry", schedule_retry):
        llm_ops._handle_summary_only_retry(
            {
                "task_id": "task-1",
                "platform": "youtube",
                "media_id": "vid1",
                "video_title": "Demo",
                "summary_retry_attempt": 1,
            }
        )

    evidence = cm.update_task_status.call_args.kwargs["terminal_evidence"]
    assert evidence["summary_pending"] is True
    assert evidence["summary_retry_scheduled"] is True
    assert evidence["summary_retry_attempt"] == 2
    schedule_retry.assert_called_once()
