"""
API route unit tests.

Covers:
- Audit routes: GET /api/audit/stats, GET /api/audit/calls
- Task routes: POST /api/transcribe, GET /api/task/{task_id}, GET /api/webhook-stats
- User routes: GET /api/users/profile
- Views: GET /robots.txt, GET /sitemap.xml
- Health endpoint is tested in test_health.py (not duplicated here)

All console output must be in English only (no emoji, no Chinese).
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from video_transcript_api.api.routes.views import _decorate_view_timing
from video_transcript_api.api.services.longcut import LongCutStartResult

# ---------------------------------------------------------------------------
# Helpers: build a minimal FastAPI app with mocked dependencies
# ---------------------------------------------------------------------------

# A fake user_info dict returned by the mocked verify_token dependency.
_FAKE_USER_INFO = {
    "user_id": "test-user",
    "api_key": "sk-test-key-123456",
    "wechat_webhook": None,
}


async def _fake_verify_token():
    """Replacement for the real verify_token dependency."""
    return _FAKE_USER_INFO


def _build_test_app() -> FastAPI:
    """Create a FastAPI app with all route routers included and deps overridden.

    We patch module-level singletons that are evaluated at import time
    (logger, config, audit_logger, cache_manager, user_manager, etc.)
    before importing the router modules.
    """
    app = FastAPI()

    # We need to override verify_token globally via dependency_overrides
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.api.routes import audit, tasks, users, views

    app.include_router(audit.router)
    app.include_router(tasks.router)
    app.include_router(users.router)
    app.include_router(views.router)

    app.dependency_overrides[verify_token] = _fake_verify_token

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_audit_logger():
    """Patch the audit_logger used in audit and tasks routes."""
    mock = MagicMock()
    mock.get_user_stats.return_value = {"total_calls": 10}
    mock.get_recent_calls.return_value = [
        {"endpoint": "/api/transcribe", "timestamp": "2025-01-01T00:00:00"}
    ]
    mock.log_api_call.return_value = None
    with patch(
        "video_transcript_api.api.routes.audit.audit_logger", mock
    ), patch(
        "video_transcript_api.api.routes.tasks.audit_logger", mock
    ):
        yield mock


@pytest.fixture()
def mock_user_manager():
    """Patch user_manager used in audit and users routes."""
    mock = MagicMock()
    mock.is_multi_user_mode.return_value = False
    mock.get_user_count.return_value = 1
    mock._mask_api_key.return_value = "sk-****5678"
    with patch(
        "video_transcript_api.api.routes.audit.user_manager", mock
    ), patch(
        "video_transcript_api.api.routes.users.user_manager", mock
    ):
        yield mock


@pytest.fixture()
def mock_cache_manager():
    """Patch cache_manager used in tasks and views routes."""
    mock = MagicMock()
    mock.create_task.return_value = {
        "task_id": "task-abc-123",
        "view_token": "vt-xyz-789",
    }
    with patch(
        "video_transcript_api.api.routes.tasks.cache_manager", mock
    ), patch(
        "video_transcript_api.api.routes.views.cache_manager", mock
    ):
        yield mock


@pytest.fixture()
def mock_task_queue():
    """Patch get_task_queue to return an asyncio.Queue."""
    q = asyncio.Queue(maxsize=10)
    with patch(
        "video_transcript_api.api.routes.tasks.get_task_queue", return_value=q
    ):
        yield q


@pytest.fixture()
def mock_send_notification():
    """Patch wechat notification sending."""
    with patch(
        "video_transcript_api.api.routes.tasks.send_view_link_wechat"
    ) as mock:
        yield mock


@pytest.fixture()
def mock_base_url():
    """Patch get_base_url used in views."""
    with patch(
        "video_transcript_api.api.routes.views.get_base_url",
        return_value="https://example.com",
    ):
        yield


@pytest.fixture()
def client(
    mock_audit_logger,
    mock_user_manager,
    mock_cache_manager,
    mock_task_queue,
    mock_send_notification,
    mock_base_url,
):
    """Create a TestClient with all mocks applied."""
    app = _build_test_app()
    return TestClient(app)


# ===========================================================================
# Audit routes
# ===========================================================================


class TestAuditStats:
    """Tests for GET /api/audit/stats."""

    def test_get_stats_default_days(self, client, mock_audit_logger, mock_user_manager):
        resp = client.get("/api/audit/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "user_stats" in body["data"]
        mock_audit_logger.get_user_stats.assert_called_once_with("test-user", 30)

    def test_get_stats_custom_days(self, client, mock_audit_logger):
        resp = client.get("/api/audit/stats?days=7")
        assert resp.status_code == 200
        mock_audit_logger.get_user_stats.assert_called_once_with("test-user", 7)

    def test_get_stats_includes_multi_user_info(self, client, mock_user_manager):
        resp = client.get("/api/audit/stats")
        body = resp.json()
        assert "is_multi_user_mode" in body["data"]
        assert "total_users" in body["data"]

    def test_get_stats_error_returns_500(self, client, mock_audit_logger):
        mock_audit_logger.get_user_stats.side_effect = RuntimeError("db error")
        resp = client.get("/api/audit/stats")
        assert resp.status_code == 500


class TestAuditCalls:
    """Tests for GET /api/audit/calls."""

    def test_get_calls_default_limit(self, client, mock_audit_logger):
        resp = client.get("/api/audit/calls")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "calls" in body["data"]
        mock_audit_logger.get_recent_calls.assert_called_once_with("test-user", 100)

    def test_get_calls_custom_limit(self, client, mock_audit_logger):
        resp = client.get("/api/audit/calls?limit=10")
        assert resp.status_code == 200
        mock_audit_logger.get_recent_calls.assert_called_once_with("test-user", 10)

    def test_get_calls_error_returns_500(self, client, mock_audit_logger):
        mock_audit_logger.get_recent_calls.side_effect = RuntimeError("db error")
        resp = client.get("/api/audit/calls")
        assert resp.status_code == 500


# ===========================================================================
# Task routes
# ===========================================================================


class TestTranscribeEndpoint:
    """Tests for POST /api/transcribe."""

    def test_transcribe_success(self, client, mock_cache_manager, mock_audit_logger):
        resp = client.post(
            "/api/transcribe",
            json={"url": "https://www.youtube.com/watch?v=abc123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 202
        assert body["data"]["task_id"] == "task-abc-123"
        assert body["data"]["view_token"] == "vt-xyz-789"
        mock_cache_manager.create_task.assert_called_once()

    def test_transcribe_empty_url_returns_400(self, client):
        resp = client.post("/api/transcribe", json={"url": ""})
        assert resp.status_code == 400

    def test_transcribe_with_speaker_recognition(self, client, mock_cache_manager):
        resp = client.post(
            "/api/transcribe",
            json={
                "url": "https://www.youtube.com/watch?v=abc123",
                "use_speaker_recognition": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 202
        # Verify speaker recognition flag was passed
        call_kwargs = mock_cache_manager.create_task.call_args
        assert call_kwargs.kwargs.get("use_speaker_recognition") is True or \
               (call_kwargs.args and len(call_kwargs.args) > 1)

    def test_transcribe_enqueues_comment_options_when_enabled(
        self, client, mock_task_queue
    ):
        resp = client.post(
            "/api/transcribe",
            json={
                "url": "https://www.youtube.com/watch?v=abc123",
                "include_comments": True,
                "comment_limit": 50,
            },
        )

        assert resp.status_code == 200
        queued_task = mock_task_queue.get_nowait()
        assert queued_task["include_comments"] is True
        assert queued_task["comment_limit"] == 50

    def test_transcribe_enqueues_source_preservation_when_requested(
        self, client, mock_task_queue
    ):
        resp = client.post(
            "/api/transcribe",
            json={
                "url": "https://www.youtube.com/watch?v=abc123",
                "preserve_source_file": True,
            },
        )

        assert resp.status_code == 200
        queued_task = mock_task_queue.get_nowait()
        assert queued_task["preserve_source_file"] is True

    def test_transcribe_enqueues_source_type_and_analysis_intent(
        self, client, mock_task_queue
    ):
        resp = client.post(
            "/api/transcribe",
            json={
                "url": "https://mp.weixin.qq.com/s/example",
                "source_type": "wechat_mp_article",
                "analysis_intent": "deep_learning",
            },
        )

        assert resp.status_code == 200
        queued_task = mock_task_queue.get_nowait()
        assert queued_task["source_type"] == "wechat_mp_article"
        assert queued_task["analysis_intent"] == "deep_learning"

    def test_transcribe_source_preservation_defaults_to_false(
        self, client, mock_task_queue
    ):
        resp = client.post(
            "/api/transcribe",
            json={"url": "https://www.youtube.com/watch?v=abc123"},
        )

        assert resp.status_code == 200
        queued_task = mock_task_queue.get_nowait()
        assert queued_task["preserve_source_file"] is False

    def test_transcribe_with_download_url(self, client, mock_cache_manager):
        resp = client.post(
            "/api/transcribe",
            json={
                "url": "https://www.youtube.com/watch?v=abc123",
                "download_url": "https://cdn.example.com/video.mp4",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 202

    def test_transcribe_empty_download_url_normalized_to_none(
        self, client, mock_cache_manager
    ):
        resp = client.post(
            "/api/transcribe",
            json={
                "url": "https://www.youtube.com/watch?v=abc123",
                "download_url": "   ",
            },
        )
        assert resp.status_code == 200
        call_kwargs = mock_cache_manager.create_task.call_args
        assert call_kwargs.kwargs.get("download_url") is None

    def test_transcribe_logs_audit(self, client, mock_audit_logger):
        client.post(
            "/api/transcribe",
            json={"url": "https://www.youtube.com/watch?v=abc123"},
        )
        assert mock_audit_logger.log_api_call.call_count >= 2


class TestUploadTranscribeEndpoint:
    """Tests for POST /api/upload-transcribe."""

    def test_upload_transcribe_logs_task_id_for_history(
        self, client, mock_audit_logger, tmp_path
    ):
        with patch(
            "video_transcript_api.api.routes.tasks.config",
            {"storage": {"temp_dir": str(tmp_path)}},
        ), patch(
            "video_transcript_api.api.routes.tasks.process_local_upload"
        ):
            resp = client.post(
                "/api/upload-transcribe",
                files={"file": ("notes.pdf", b"%PDF-1.4\ntext", "application/pdf")},
            )

        assert resp.status_code == 200
        assert resp.json()["code"] == 202
        audit_kwargs = mock_audit_logger.log_api_call.call_args.kwargs
        assert audit_kwargs["endpoint"] == "/api/upload-transcribe"
        assert audit_kwargs["task_id"] == "task-abc-123"
        assert audit_kwargs["status_code"] == 202

    def test_upload_transcribe_sets_local_file_title_for_processing_view(
        self, client, mock_cache_manager, tmp_path
    ):
        with patch(
            "video_transcript_api.api.routes.tasks.config",
            {"storage": {"temp_dir": str(tmp_path)}},
        ), patch(
            "video_transcript_api.api.routes.tasks.process_local_upload"
        ):
            resp = client.post(
                "/api/upload-transcribe",
                files={"file": ("notes.md", b"# Notes", "text/markdown")},
            )

        assert resp.status_code == 200
        mock_cache_manager.update_task_status.assert_called_once_with(
            "task-abc-123",
            "queued",
            platform="generic",
            media_id=ANY,
            title="notes.md",
        )
        assert (
            mock_cache_manager.create_task.call_args.kwargs["force_new_view_token"]
            is True
        )

    def test_upload_transcribe_uses_content_hash_as_media_id(
        self, client, mock_cache_manager, tmp_path
    ):
        with patch(
            "video_transcript_api.api.routes.tasks.config",
            {"storage": {"temp_dir": str(tmp_path)}},
        ), patch(
            "video_transcript_api.api.routes.tasks.process_local_upload"
        ):
            for _ in range(2):
                response = client.post(
                    "/api/upload-transcribe",
                    files={"file": ("lesson.mp4", b"same-video", "video/mp4")},
                )
                assert response.status_code == 200

        first_call, second_call = mock_cache_manager.create_task.call_args_list[-2:]
        first_media_id = first_call.kwargs["media_id"]
        second_media_id = second_call.kwargs["media_id"]
        assert first_media_id == second_media_id
        assert first_media_id.startswith("local_")


class TestGetTaskStatus:
    """Tests for GET /api/task/{task_id}.

    Status now comes from the persistent task_status table (single source of
    truth), read via cache_manager.get_task_by_id. The response data carries an
    explicit `status` field plus metadata; content is fetched via view_token.
    """

    def _row(self, **overrides):
        row = {
            "task_id": "task-1",
            "view_token": "vt-1",
            "status": "queued",
            "title": "Demo",
            "author": "Alice",
            "platform": "youtube",
            "completed_at": None,
            "error_message": None,
            "progress": None,
        }
        row.update(overrides)
        return row

    def test_task_not_found(self, client, mock_cache_manager):
        mock_cache_manager.get_task_by_id.return_value = None
        resp = client.get("/api/task/nonexistent-task")
        assert resp.status_code == 404

    def test_task_queued_returns_202(self, client, mock_cache_manager):
        mock_cache_manager.get_task_by_id.return_value = self._row(status="queued")
        body = client.get("/api/task/task-1").json()
        assert body["code"] == 202
        assert body["data"]["status"] == "queued"

    def test_task_processing_returns_202(self, client, mock_cache_manager):
        mock_cache_manager.get_task_by_id.return_value = self._row(status="processing")
        body = client.get("/api/task/task-1").json()
        assert body["code"] == 202
        assert body["data"]["status"] == "processing"

    def test_task_status_includes_progress_when_available(
        self, client, mock_cache_manager
    ):
        mock_cache_manager.get_task_by_id.return_value = self._row(
            status="processing",
            progress={
                "stage": "downloading",
                "stage_label": "正在下载音视频",
                "percent": 22,
                "basis": "download_bytes",
                "confidence": "high",
            },
        )

        body = client.get("/api/task/task-1").json()

        assert body["data"]["progress"]["stage"] == "downloading"
        assert body["data"]["progress"]["percent"] == 22

    def test_task_calibrating_returns_202(self, client, mock_cache_manager):
        # NEW state: transcript done, LLM calibration still running.
        mock_cache_manager.get_task_by_id.return_value = self._row(status="calibrating")
        body = client.get("/api/task/task-1").json()
        assert body["code"] == 202
        assert body["data"]["status"] == "calibrating"

    def test_task_success_returns_200_with_metadata(self, client, mock_cache_manager):
        mock_cache_manager.get_task_by_id.return_value = self._row(
            status="success", completed_at="2026-06-03T10:00:00"
        )
        body = client.get("/api/task/task-1").json()
        assert body["code"] == 200
        data = body["data"]
        assert data["status"] == "success"
        assert data["view_token"] == "vt-1"
        assert data["title"] == "Demo"
        assert data["author"] == "Alice"
        assert data["platform"] == "youtube"
        assert data["completed_at"] == "2026-06-03T10:00:00"
        # Inline transcript is intentionally dropped (fetch via view_token).
        assert "transcript" not in data

    def test_task_failed_returns_500_with_error(self, client, mock_cache_manager):
        mock_cache_manager.get_task_by_id.return_value = self._row(
            status="failed", error_message="ASR timeout"
        )
        resp = client.get("/api/task/task-1")
        body = resp.json()
        assert body["code"] == 500
        assert body["data"]["status"] == "failed"
        assert body["data"]["error"] == "ASR timeout"


class TestDeleteTask:
    """Tests for DELETE /api/task/{task_id}."""

    def test_deletes_task_and_its_cached_media(self, client, mock_cache_manager):
        mock_cache_manager.delete_task_and_cache.return_value = {
            "deleted_caches": 1,
            "deleted_tasks": 2,
        }

        response = client.delete("/api/task/task-1")

        assert response.status_code == 200
        assert response.json()["data"] == {
            "deleted_caches": 1,
            "deleted_tasks": 2,
        }
        mock_cache_manager.delete_task_and_cache.assert_called_once_with("task-1")


class TestRecalibrateEndpoint:
    """Tests for POST /api/recalibrate."""

    def test_recalibrate_can_force_summary_regeneration(
        self, client, mock_cache_manager
    ):
        cursor = MagicMock()
        mock_cache_manager._get_cursor.return_value.__enter__.return_value = cursor
        mock_cache_manager.generate_task_id.return_value = "task-recal-1"
        mock_cache_manager.get_cache_by_view_token.return_value = {
            "platform": "generic",
            "media_id": "media-1",
            "use_speaker_recognition": False,
            "title": "Demo",
            "author": "Author",
            "description": "",
            "file_path": "/tmp/cache",
            "transcript_type": "capswriter",
            "transcript_data": "transcript body",
            "task_info": {"url": "local://collection-source/media-1/Demo.mp4"},
        }
        llm_queue = MagicMock()
        user_manager = MagicMock()
        user_manager.check_permission.return_value = True

        with patch(
            "video_transcript_api.api.routes.tasks.get_user_manager",
            return_value=user_manager,
        ), patch(
            "video_transcript_api.api.context.get_llm_queue",
            return_value=llm_queue,
        ):
            resp = client.post(
                "/api/recalibrate",
                json={"view_token": "vt-1", "regenerate_summary": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 202
        queued_task = llm_queue.put.call_args.args[0]
        assert queued_task["task_id"] == "task-recal-1"
        assert queued_task["calibrate_only"] is True
        assert queued_task["regenerate_summary"] is True


class TestViewProgressEndpoint:
    """Tests for public view-token progress polling."""

    def test_decorate_view_timing_adds_elapsed_and_duration(self):
        processing = {
            "status": "processing",
            "created_at": "2026-06-08T10:00:00+00:00",
            "progress": {"updated_at": "2026-06-08T10:01:05+00:00"},
        }
        _decorate_view_timing(
            processing,
            now=datetime(2026, 6, 8, 10, 2, 30, tzinfo=timezone.utc),
        )

        assert processing["elapsed_seconds"] == 150
        assert processing["elapsed_display"] == "2 分 30 秒"
        assert processing["progress"]["updated_at_display"].endswith("18:01:05")

        completed = {
            "status": "success",
            "created_at": "2026-06-08T10:00:00+00:00",
            "completed_at": "2026-06-08T10:07:42+00:00",
        }
        _decorate_view_timing(completed)

        assert completed["duration_seconds"] == 462
        assert completed["duration_display"] == "7 分 42 秒"

    def test_processing_view_renders_progress_panel(self, client, mock_cache_manager):
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "processing",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "created_at": "2026-06-08T10:00:00",
            "elapsed_display": "1 分 30 秒",
            "progress": {
                "stage": "downloading",
                "stage_label": "正在下载音视频",
                "percent": 22,
                "basis": "download_bytes",
                "confidence": "high",
            },
        }

        resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        assert "progress-panel" in resp.text
        assert "/view/vt-1/progress" in resp.text
        assert "正在下载音视频" in resp.text
        assert "已处理" in resp.text
        assert "完成后会自动打开结果页" in resp.text
        assert "技术细节" not in resp.text
        assert "置信度" not in resp.text
        assert "依据" not in resp.text
        assert "刷新页面" not in resp.text
        assert "预计剩余" not in resp.text

    def test_processing_view_uses_document_copy_for_local_markdown(
        self, client, mock_cache_manager
    ):
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "processing",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": None,
            "url": "local://abc/notes.md",
            "platform": "generic",
            "created_at": "2026-06-08T10:00:00",
            "elapsed_display": "21 秒",
            "progress": {
                "stage": "calibrating",
                "stage_label": "正在校对和总结",
                "percent": 94,
            },
        }

        resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert "notes.md" in resp.text
        assert "文档解析处理中" in resp.text
        assert "视频转录查看器" not in resp.text
        assert "转录处理中" not in resp.text

    def test_raw_summary_export_normalizes_duplicate_heading_markers(
        self, client, mock_cache_manager, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "llm_summary.txt").write_text(
            "#### ##### 2.1 睡前一小时\n\n正文",
            encoding="utf-8",
        )
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "url": "https://example.com/video",
            "platform": "youtube",
            "media_id": "video-1",
            "cache_dir": str(cache_dir),
        }

        resp = client.get("/view/vt-1?raw=summary")

        assert resp.status_code == 200
        assert "#####" not in resp.text
        assert "#### 2.1 睡前一小时" in resp.text

    def test_scoped_bundle_export_returns_markdown_download(
        self, client, mock_cache_manager, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "llm_summary.txt").write_text("AI analysis", encoding="utf-8")
        (cache_dir / "llm_calibrated.txt").write_text("Proofread text", encoding="utf-8")
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "url": "https://example.com/video",
            "platform": "youtube",
            "media_id": "video-1",
            "cache_dir": str(cache_dir),
        }

        resp = client.get("/export/vt-1/bundle?scope=analysis")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "filename*=UTF-8''Demo-AI%E8%A7%A3%E6%9E%90-YouTube.md" in resp.headers[
            "content-disposition"
        ]
        assert "## 内容总结" in resp.text
        assert "AI analysis" in resp.text
        assert "Proofread text" not in resp.text

    def test_failed_view_is_not_cached(self, client, mock_cache_manager):
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "failed",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "url": "https://example.com/video",
            "platform": "xiaohongshu",
            "media_id": "note-1",
            "error_message": "download failed",
            "created_at": "2026-06-08T10:00:00",
        }

        resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        assert "download failed" in resp.text

    def test_success_view_links_preserved_local_source_file(
        self, client, mock_cache_manager, tmp_path
    ):
        source_dir = tmp_path / "source-files"
        source_dir.mkdir()
        (source_dir / "media-1.mp4").write_bytes(b"fake video")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "如何走出人生困局/1.mp4",
            "author": "本地上传",
            "url": "local://collection-source/media-1/如何走出人生困局/1.mp4",
            "platform": "generic",
            "media_id": "media-1",
            "summary": "",
            "transcript": "transcript",
            "cache_dir": str(cache_dir),
            "created_at": "2026-06-08T10:00:00",
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={
                "storage": {"source_files_dir": str(source_dir)},
                "longcut": {"enabled": False},
            },
        ), patch(
            "video_transcript_api.api.routes.views.render_calibrated_content_smart",
            return_value="<p>transcript</p>",
        ):
            resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert 'href="/view/vt-1/source-file"' in resp.text
        assert "local://collection-source" not in resp.text

    def test_success_view_passes_database_fallback_text_to_renderer(
        self, client, mock_cache_manager, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "url": "https://example.com/video",
            "platform": "youtube",
            "media_id": "video-1",
            "summary": "",
            "transcript": "数据库回退文本",
            "cache_dir": str(cache_dir),
            "created_at": "2026-06-08T10:00:00",
        }

        with patch(
            "video_transcript_api.api.routes.views.render_calibrated_content_smart",
            return_value="<p>数据库回退文本</p>",
        ) as render_content:
            resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        render_content.assert_called_once_with(str(cache_dir), "数据库回退文本")

    def test_view_source_file_serves_preserved_local_file(
        self, client, mock_cache_manager, tmp_path
    ):
        source_dir = tmp_path / "source-files"
        source_dir.mkdir()
        (source_dir / "media-1.mp4").write_bytes(b"fake video")
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "view_token": "vt-1",
            "title": "如何走出人生困局/1.mp4",
            "url": "local://collection-source/media-1/如何走出人生困局/1.mp4",
            "platform": "generic",
            "media_id": "media-1",
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={"storage": {"source_files_dir": str(source_dir)}},
        ):
            resp = client.get("/view/vt-1/source-file")

        assert resp.status_code == 200
        assert resp.content == b"fake video"

    def test_view_source_file_serves_online_preserved_file_path(
        self, client, mock_cache_manager, tmp_path
    ):
        source_file = tmp_path / "wechat.mp4"
        source_file.write_bytes(b"online video")
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "view_token": "vt-1",
            "title": "WeChat Demo",
            "url": "https://weixin.qq.com/sph/A1kpVPJjiX",
            "platform": "wechat_channels",
            "media_id": "A1kpVPJjiX",
            "source_file_path": str(source_file),
        }

        resp = client.get("/view/vt-1/source-file")

        assert resp.status_code == 200
        assert resp.content == b"online video"
        assert "wechat.mp4" in resp.headers.get("content-disposition", "")

    def test_success_view_renders_download_and_reveal_for_online_source_file(
        self, client, mock_cache_manager, tmp_path
    ):
        source_file = tmp_path / "wechat.mp4"
        source_file.write_bytes(b"online video")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "WeChat Demo",
            "author": "Author",
            "url": "https://weixin.qq.com/sph/A1kpVPJjiX",
            "platform": "wechat_channels",
            "media_id": "A1kpVPJjiX",
            "summary": "",
            "transcript": "transcript",
            "cache_dir": str(cache_dir),
            "created_at": "2026-07-04T10:00:00",
            "source_file_path": str(source_file),
        }

        with patch(
            "video_transcript_api.api.routes.views.render_calibrated_content_smart",
            return_value="<p>transcript</p>",
        ):
            resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert 'href="/view/vt-1/source-file"' in resp.text
        assert "下载源文件" in resp.text
        assert 'data-source-reveal-url="/view/vt-1/source-file/reveal"' in resp.text
        assert "在本机显示" in resp.text

    def test_view_source_file_reveal_opens_online_preserved_file(
        self, client, mock_cache_manager, tmp_path, monkeypatch
    ):
        from video_transcript_api.api.routes import views

        source_file = tmp_path / "wechat.mp4"
        source_file.write_bytes(b"online video")
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "view_token": "vt-1",
            "title": "WeChat Demo",
            "url": "https://weixin.qq.com/sph/A1kpVPJjiX",
            "platform": "wechat_channels",
            "media_id": "A1kpVPJjiX",
            "source_file_path": str(source_file),
        }
        opened = {}
        monkeypatch.setattr(
            views,
            "_reveal_path_in_file_manager",
            lambda path: opened.setdefault("path", str(path)),
            raising=False,
        )

        resp = client.post("/view/vt-1/source-file/reveal")

        assert resp.status_code == 200
        assert opened["path"] == str(source_file)
        assert resp.json()["data"]["filename"] == "wechat.mp4"

    def test_success_view_does_not_render_broken_local_source_link(
        self, client, mock_cache_manager, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "如何走出人生困局/1.mp4",
            "author": "本地上传",
            "url": "local://collection-source/media-1/如何走出人生困局/1.mp4",
            "platform": "generic",
            "media_id": "media-1",
            "summary": "",
            "transcript": "transcript",
            "cache_dir": str(cache_dir),
            "created_at": "2026-06-08T10:00:00",
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={
                "storage": {"source_files_dir": str(tmp_path / "source-files")},
                "longcut": {"enabled": False},
            },
        ), patch(
            "video_transcript_api.api.routes.views.render_calibrated_content_smart",
            return_value="<p>transcript</p>",
        ):
            resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert "local://collection-source" not in resp.text
        assert "源视频未保存或已清理" not in resp.text

    def test_success_view_with_missing_summary_does_not_show_processing(
        self, client, mock_cache_manager, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "author": "Author",
            "url": "local://collection-source/media-1/Demo.mp4",
            "platform": "generic",
            "media_id": "media-1",
            "summary": "",
            "summary_missing": True,
            "transcript": "transcript",
            "cache_dir": str(cache_dir),
            "created_at": "2026-06-08T10:00:00",
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={
                "storage": {"source_files_dir": str(tmp_path / "source-files")},
                "longcut": {"enabled": False},
            },
        ), patch(
            "video_transcript_api.api.routes.views.render_calibrated_content_smart",
            return_value="<p>transcript</p>",
        ):
            resp = client.get("/view/vt-1")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        assert "总结未生成" in resp.text
        assert "总结处理中" not in resp.text

    def test_success_view_renders_collection_navigation(
        self, client, mock_cache_manager, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "task_id": "task-2",
            "view_token": "vt-2",
            "title": "如何走出人生困局/2.mp4",
            "author": "本地上传",
            "url": "local://collection-source/media-2/如何走出人生困局/2.mp4",
            "platform": "generic",
            "media_id": "media-2",
            "summary": "## 内容总结",
            "transcript": "transcript",
            "cache_dir": str(cache_dir),
            "created_at": "2026-06-08T10:00:00",
        }
        navigation = {
            "collection": {
                "id": "collection-1",
                "title": "如何走出人生困局",
                "url": "/collections?collection_id=collection-1&source_id=source-2",
            },
            "items": [
                {
                    "id": "source-1",
                    "title": "1.mp4",
                    "view_url": "/view/vt-1",
                    "is_current": False,
                },
                {
                    "id": "source-2",
                    "title": "2.mp4",
                    "view_url": "/view/vt-2",
                    "is_current": True,
                },
                {
                    "id": "source-3",
                    "title": "3.mp4",
                    "view_url": "/view/vt-3",
                    "is_current": False,
                },
            ],
            "current": {"title": "2.mp4", "view_url": "/view/vt-2"},
            "previous": {"title": "1.mp4", "view_url": "/view/vt-1"},
            "next": {"title": "3.mp4", "view_url": "/view/vt-3"},
            "current_number": 2,
            "total": 3,
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={"longcut": {"enabled": False}},
        ), patch(
            "video_transcript_api.api.routes.views.render_calibrated_content_smart",
            return_value="<p>transcript</p>",
        ), patch(
            "video_transcript_api.api.routes.views._build_collection_navigation",
            return_value=navigation,
        ) as build_navigation:
            resp = client.get("/view/vt-2")

        assert resp.status_code == 200
        build_navigation.assert_called_once_with("vt-2")
        assert "<h1>2</h1>" in resp.text
        assert "如何走出人生困局/2.mp4" not in resp.text

    def test_view_progress_returns_minimal_progress_payload(
        self, client, mock_cache_manager
    ):
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "processing",
            "task_id": "task-1",
            "view_token": "vt-1",
            "title": "Demo",
            "created_at": "2026-06-08T10:00:00+00:00",
            "progress": {
                "stage": "transcribing",
                "stage_label": "正在转录音视频",
                "percent": 62,
                "basis": "funasr_server_progress",
                "confidence": "high",
                "updated_at": "2026-06-08T10:01:05+00:00",
            },
        }

        resp = client.get("/view/vt-1/progress")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "processing"
        assert body["task_id"] == "task-1"
        assert "elapsed_display" in body
        assert body["progress"]["percent"] == 62
        assert "updated_at_display" in body["progress"]
        assert "transcript" not in body
        assert "summary" not in body

    def test_view_progress_unknown_token_returns_404(self, client, mock_cache_manager):
        mock_cache_manager.get_view_data_by_token.return_value = None

        resp = client.get("/view/missing/progress")

        assert resp.status_code == 404

    def test_open_in_longcut_redirects_for_youtube(self, client, mock_cache_manager):
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "view_token": "vt-1",
            "platform": "youtube",
            "media_id": "abc123",
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={
                "longcut": {
                    "enabled": True,
                    "base_url": "http://localhost:3000",
                    "project_dir": "/tmp/longcut",
                }
            },
        ), patch(
            "video_transcript_api.api.routes.views.ensure_longcut_ready",
            return_value=LongCutStartResult(True, False, "ready"),
        ) as ensure_ready:
            resp = client.get("/view/vt-1/longcut", follow_redirects=False)

        assert resp.status_code == 303
        assert resp.headers["location"] == "http://localhost:3000/analyze/abc123"
        ensure_ready.assert_called_once()

    def test_open_in_longcut_rejects_non_youtube(self, client, mock_cache_manager):
        mock_cache_manager.get_view_data_by_token.return_value = {
            "status": "success",
            "view_token": "vt-1",
            "platform": "bilibili",
            "media_id": "BV123",
        }

        with patch(
            "video_transcript_api.api.routes.views.get_config",
            return_value={"longcut": {"enabled": True}},
        ), patch(
            "video_transcript_api.api.routes.views.ensure_longcut_ready"
        ) as ensure_ready:
            resp = client.get("/view/vt-1/longcut")

        assert resp.status_code == 400
        ensure_ready.assert_not_called()


class TestWebhookStatsEndpoint:
    """Tests for GET /api/webhook-stats (deprecated)."""

    def test_webhook_stats_returns_deprecated(self, client):
        resp = client.get("/api/webhook-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["deprecated"] is True


class TestWebhookStatusEndpoint:
    """Tests for GET /api/webhook-status."""

    def test_webhook_status_returns_deprecated(self, client):
        resp = client.get(
            "/api/webhook-status?webhook_url=https://hook.example.com/abc"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["deprecated"] is True

    def test_webhook_status_truncates_long_url(self, client):
        long_url = "https://hook.example.com/" + "x" * 100
        resp = client.get(f"/api/webhook-status?webhook_url={long_url}")
        body = resp.json()
        assert body["data"]["webhook_url"].endswith("...")


# ===========================================================================
# User routes
# ===========================================================================


class TestUserProfile:
    """Tests for GET /api/users/profile."""

    def test_get_profile_success(self, client, mock_user_manager):
        resp = client.get("/api/users/profile")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "user_info" in body["data"]
        assert "is_multi_user_mode" in body["data"]

    def test_get_profile_masks_api_key(self, client, mock_user_manager):
        resp = client.get("/api/users/profile")
        body = resp.json()
        # The mock _mask_api_key returns "sk-****5678"
        assert body["data"]["user_info"]["api_key"] == "sk-****5678"
        mock_user_manager._mask_api_key.assert_called_once()

    def test_get_profile_error_returns_500(self, client, mock_user_manager):
        mock_user_manager.is_multi_user_mode.side_effect = RuntimeError("db error")
        resp = client.get("/api/users/profile")
        assert resp.status_code == 500


# ===========================================================================
# Views routes (public, no auth)
# ===========================================================================


class TestRobotsTxt:
    """Tests for GET /robots.txt."""

    def test_robots_txt_content(self, client):
        resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/plain; charset=utf-8"
        text = resp.text
        assert "User-agent: *" in text
        assert "Disallow: /api/" in text
        assert "Sitemap:" in text
        assert "https://example.com/sitemap.xml" in text

    def test_robots_txt_allows_root(self, client):
        text = client.get("/robots.txt").text
        assert "Allow: /" in text


class TestSitemapXml:
    """Tests for GET /sitemap.xml."""

    def test_sitemap_xml_content(self, client):
        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "application/xml" in resp.headers["content-type"]
        text = resp.text
        assert "<urlset" in text
        assert "https://example.com/" in text

    def test_sitemap_xml_is_valid_xml(self, client):
        import xml.etree.ElementTree as ET
        resp = client.get("/sitemap.xml")
        # Should parse without errors
        ET.fromstring(resp.text)
