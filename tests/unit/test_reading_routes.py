from fastapi.testclient import TestClient
from datetime import UTC, datetime

from video_transcript_api.reading.schemas import ReadingParseRun


def _build_app():
    from video_transcript_api.api.app import create_app

    return create_app()


def test_reading_page_serves_real_shell():
    response = TestClient(_build_app()).get("/reading")

    assert response.status_code == 200
    assert 'id="reading-library"' in response.text
    assert 'id="reading-reader"' in response.text


def test_reading_deep_link_serves_same_shell():
    response = TestClient(_build_app()).get("/reading/document-123")

    assert response.status_code == 200
    assert 'id="reading-library"' in response.text
    assert 'id="reading-reader"' in response.text


def test_reading_documents_starts_with_an_authenticated_empty_list(monkeypatch):
    from video_transcript_api.api.routes import reading
    from video_transcript_api.api.services.transcription import verify_token

    class EmptyService:
        def list_documents(self, owner_user_id):
            return []

        def close(self):
            return None

    monkeypatch.setattr(reading, "get_reading_service", EmptyService)

    app = _build_app()
    app.dependency_overrides[verify_token] = lambda: {"user_id": "test-user"}

    response = TestClient(app).get("/api/reading/documents")

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "success",
        "data": {"items": [], "total": 0},
    }


def test_reading_documents_requires_authorization():
    response = TestClient(_build_app()).get("/api/reading/documents")

    assert response.status_code == 401


def test_main_app_registers_reading_routes():
    paths = {route.path for route in _build_app().routes}

    assert "/reading" in paths
    assert "/reading/{document_id}" in paths
    assert "/api/reading/documents" in paths
    assert "/api/reading/documents/{document_id}/assets/{asset_name}" in paths
    assert "/api/reading/documents/{document_id}/source" in paths


def test_reprocess_endpoint_reserves_run_and_schedules_owned_pdf(monkeypatch):
    from video_transcript_api.api.routes import reading
    from video_transcript_api.api.services.transcription import verify_token

    now = datetime.now(UTC)
    run = ReadingParseRun(
        id="run-1",
        document_id="document-1",
        generation=2,
        parent_run_id="run-0",
        parser_version="structured-v1",
        status="running",
        created_at=now,
        updated_at=now,
    )
    completed = []

    class ReprocessService:
        def start_reprocess_document(self, owner_user_id, document_id):
            assert (owner_user_id, document_id) == ("test-user", "document-1")
            return run

        def complete_reprocess_document(self, owner_user_id, document_id, run_id):
            completed.append((owner_user_id, document_id, run_id))

        def close(self):
            return None

    monkeypatch.setattr(reading, "get_reading_service", ReprocessService)
    app = _build_app()
    app.dependency_overrides[verify_token] = lambda: {"user_id": "test-user"}

    response = TestClient(app).post("/api/reading/documents/document-1/reprocess")

    assert response.status_code == 202
    assert response.json()["data"]["id"] == "run-1"
    assert completed == [("test-user", "document-1", "run-1")]
