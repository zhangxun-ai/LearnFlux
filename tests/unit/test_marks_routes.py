from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _fake_verify_token():
    return {"user_id": "test-user", "api_key": "sk-test-key-123456"}


def _build_app():
    from video_transcript_api.api.routes import marks
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(marks.router)
    app.dependency_overrides[verify_token] = _fake_verify_token
    return app


def test_mark_transcript_and_get_status(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import marks
    from video_transcript_api.marks.repository import ContentMarkRepository

    repository = ContentMarkRepository(db_path=str(tmp_path / "marks.db"))
    cache_manager = MagicMock()
    cache_manager.get_task_by_view_token.return_value = {"view_token": "view-1"}
    audit_logger = MagicMock()
    audit_logger._mask_api_key.return_value = "sk-t************3456"

    monkeypatch.setattr(marks, "get_marks_repository", lambda: repository)
    monkeypatch.setattr(marks, "cache_manager", cache_manager)
    monkeypatch.setattr(marks, "audit_logger", audit_logger)

    client = TestClient(_build_app())

    create_response = client.post("/api/marks/transcripts/view-1")
    assert create_response.status_code == 200
    assert create_response.json()["data"]["marked"] is True

    status_response = client.get("/api/marks/transcripts/view-1")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["marked"] is True


def test_unmark_transcript(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import marks
    from video_transcript_api.marks.repository import ContentMarkRepository

    repository = ContentMarkRepository(db_path=str(tmp_path / "marks.db"))
    repository.mark("transcript", "view-1", "sk-t************3456")
    cache_manager = MagicMock()
    cache_manager.get_task_by_view_token.return_value = {"view_token": "view-1"}
    audit_logger = MagicMock()
    audit_logger._mask_api_key.return_value = "sk-t************3456"

    monkeypatch.setattr(marks, "get_marks_repository", lambda: repository)
    monkeypatch.setattr(marks, "cache_manager", cache_manager)
    monkeypatch.setattr(marks, "audit_logger", audit_logger)

    client = TestClient(_build_app())

    response = client.delete("/api/marks/transcripts/view-1")
    assert response.status_code == 200
    assert response.json()["data"]["marked"] is False
