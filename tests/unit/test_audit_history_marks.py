from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.marks.repository import ContentMarkRepository
from video_transcript_api.utils.logging.audit_logger import AuditLogger
from video_transcript_api.utils.task_status import TaskStatus


async def _fake_verify_token():
    return {"user_id": "test-user", "api_key": "sk-test-key-123456"}


def _build_client(monkeypatch, cache_manager, audit_logger):
    from video_transcript_api.api.routes import audit
    from video_transcript_api.api.services.transcription import verify_token

    monkeypatch.setattr(audit, "audit_logger", audit_logger)
    monkeypatch.setattr(audit, "get_cache_manager", lambda: cache_manager)

    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[verify_token] = _fake_verify_token
    return TestClient(app)


def _success_task(cache_manager, audit_logger, url, title):
    task = cache_manager.create_task(url=url)
    cache_manager.update_task_status(
        task["task_id"],
        TaskStatus.SUCCESS,
        platform="youtube",
        media_id=task["task_id"],
        title=title,
        author="Channel",
    )
    audit_logger.log_api_call(
        api_key="sk-test-key-123456",
        user_id="test-user",
        endpoint="/api/transcribe",
        video_url=url,
        task_id=task["task_id"],
    )
    return task


def test_history_can_filter_marked_transcripts(monkeypatch, tmp_path):
    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    audit_logger = AuditLogger(db_path=str(tmp_path / "audit.db"))
    marked = _success_task(cache_manager, audit_logger, "https://example.com/a", "Marked")
    _success_task(cache_manager, audit_logger, "https://example.com/b", "Plain")

    user_key = audit_logger._mask_api_key("sk-test-key-123456")
    ContentMarkRepository(str(cache_manager.db_path)).mark(
        "transcript", marked["view_token"], user_key
    )

    client = _build_client(monkeypatch, cache_manager, audit_logger)
    response = client.get("/api/audit/history?marked=true")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["title"] for item in items] == ["Marked"]
    assert items[0]["is_marked"] is True


def test_marked_legacy_local_upload_is_found_by_url(monkeypatch, tmp_path):
    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    audit_logger = AuditLogger(db_path=str(tmp_path / "audit.db"))
    local_url = "local://local_pdf_123/notes.pdf"
    task = cache_manager.create_task(url=local_url, platform="generic", media_id="local_pdf_123")
    cache_manager.update_task_status(
        task["task_id"],
        TaskStatus.SUCCESS,
        platform="generic",
        media_id="local_pdf_123",
        title="notes.pdf",
        author="本地上传",
    )
    audit_logger.log_api_call(
        api_key="sk-test-key-123456",
        user_id="test-user",
        endpoint="/api/upload-transcribe",
        video_url=local_url,
        status_code=202,
    )

    user_key = audit_logger._mask_api_key("sk-test-key-123456")
    ContentMarkRepository(str(cache_manager.db_path)).mark(
        "transcript", task["view_token"], user_key
    )

    client = _build_client(monkeypatch, cache_manager, audit_logger)
    response = client.get("/api/audit/history?marked=true")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["task_id"] == task["task_id"]
    assert items[0]["view_token"] == task["view_token"]
    assert items[0]["title"] == "notes.pdf"
    assert items[0]["is_marked"] is True
