"""Cloud progress display uses durable state without starting another attempt."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.api.routes import views
from video_transcript_api.api.services import transcription
from video_transcript_api.transcriber.providers.aliyun_funasr import CloudProviderError


def active_view(task_status="processing"):
    return {
        "status": "processing", "task_status": task_status,
        "task_id": "task-1", "view_token": "demo", "title": "Lecture",
        "platform": "twitter", "media_id": "1_video_1", "url": "https://x.com/a/status/1/video/1",
        "created_at": "2026-10-29T14:51:04+00:00",
        "progress": {
            "stage": "awaiting_cloud_confirmation", "stage_label": "Old quote",
            "percent": 0, "evidence": {"cloud_quote": {"quote_token": "private"}},
        },
    }


def install_view(monkeypatch, *, task_status="processing", remote_status="submission_unknown"):
    data = active_view(task_status)
    cache = Mock()
    cache.get_view_data_by_token.side_effect = lambda _: deepcopy(data)
    monkeypatch.setattr(views, "cache_manager", cache)
    event = SimpleNamespace(remote_status=remote_status, updated_at="2026-10-29T22:18:31+00:00")
    repository = Mock()
    repository.find_latest_event_by_task_id.return_value = event
    monkeypatch.setattr(views, "get_usage_repository", lambda: repository)
    app = FastAPI()
    app.include_router(views.router)
    return TestClient(app), cache, repository


def test_unknown_submission_overrides_stale_quote_without_writing_task(monkeypatch):
    client, cache, repository = install_view(monkeypatch)
    body = client.get("/view/demo/progress").json()
    assert body["status"] == "processing"
    assert body["progress"]["stage"] == "cloud_submission_unknown"
    assert body["progress"]["percent"] is None
    assert "暂停自动重试" in body["progress"]["message"]
    assert body["progress"]["updated_at"].startswith("2026-10-29T22:18:31")
    assert "private" not in str(body)
    cache.update_task_status.assert_not_called()
    cache.update_task_progress.assert_not_called()
    repository.find_latest_event_by_task_id.assert_called_once_with("task-1")


def test_unknown_submission_page_explains_pause_and_elapsed_time(monkeypatch):
    client, _, _ = install_view(monkeypatch)
    html = client.get("/view/demo").text
    assert "需要核对云端提交结果" in html
    assert "已暂停自动重试以避免重复计费" in html
    assert "距任务创建" in html
    assert "Old quote" not in html
    assert 'id="progress-percent"' in html


def test_public_progress_preserves_confirmation_status_without_quote_secret(monkeypatch):
    client, _, repository = install_view(monkeypatch, task_status="awaiting_cloud_confirmation")
    body = client.get("/view/demo/progress").json()
    assert body["status"] == "awaiting_cloud_confirmation"
    assert "quote_token" not in body["progress"]["evidence"]["cloud_quote"]
    repository.find_latest_event_by_task_id.assert_not_called()
    html = client.get("/view/demo").text
    assert "等待确认云端费用" in html
    assert "确认预计费用后才会开始云端转录" in html


def test_confirmed_cloud_work_does_not_offer_the_old_quote_again(monkeypatch):
    client, _, _ = install_view(monkeypatch, remote_status="submitted")
    body = client.get("/view/demo/progress").json()
    assert body["progress"]["stage"] == "transcribing"
    assert "cloud_quote" not in body["progress"].get("evidence", {})


def test_confirmed_worker_replaces_quote_progress_and_explains_unknown(monkeypatch, tmp_path):
    quote = SimpleNamespace(
        status="confirming", lease_owner="claim", continuation_json="{}", max_cost=Decimal("1.63"),
    )
    repository = Mock()
    repository.get.return_value = quote
    monkeypatch.setattr(transcription, "CloudQuoteRepository", lambda _: repository)
    monkeypatch.setattr(transcription, "UsageEventRepository", lambda _: Mock())
    monkeypatch.setattr(transcription, "get_transcription_control_database", lambda _: tmp_path / "control.db")
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda _: False)
    monkeypatch.setattr(transcription, "cache_manager", Mock())
    monkeypatch.setattr(transcription, "_load_quote_prepared_media", lambda _: SimpleNamespace(path=tmp_path / "input.m4a"))
    monkeypatch.setattr(transcription, "load_cloud_continuation", lambda _: {"platform": "twitter", "media_id": "1_video_1"})
    progress = Mock()
    monkeypatch.setattr(transcription, "_safe_update_progress", progress)
    transcriber = Mock()
    def submit(*args, **kwargs):
        assert progress.call_args.kwargs["stage"] == "transcribing"
        assert progress.call_args.kwargs["basis"] == "cloud_confirmation_accepted"
        raise CloudProviderError("submission_unknown")
    transcriber.transcribe.side_effect = submit
    monkeypatch.setattr(transcription, "Transcriber", Mock(return_value=transcriber))
    failure = Mock()
    monkeypatch.setattr(transcription, "_record_asr_failure", failure)
    with pytest.raises(CloudProviderError, match="submission_unknown"):
        transcription.resume_confirmed_cloud_quote("task-1", claim_owner="claim", slot_owner="slot")
    assert progress.call_args.kwargs["stage"] == "cloud_submission_unknown"
    assert "避免重复计费" in progress.call_args.kwargs["message"]
    assert transcriber.transcribe.call_count == 1
    failure.assert_not_called()
    repository.require_refresh.assert_not_called()
