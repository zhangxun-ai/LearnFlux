from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _fake_verify_token():
    return {"user_id": "test-user", "api_key": "sk-test"}


def _build_app(*, authenticated=True):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(visual_learning.router)
    if authenticated:
        app.dependency_overrides[verify_token] = _fake_verify_token
    return app


def _record(
    status="success",
    document_id="visual-1",
    *,
    owner_type="study",
    owner_id="view-1",
    document_type="overview",
):
    document_json = None
    if status == "success":
        document_json = {
            "title": "图解笔记",
            "diagram_recommendations": [
                {
                    "diagram_type": "concept_chain",
                    "label": "概念链",
                    "rationale": "有清晰主线",
                    "score": 0.9,
                }
            ],
            "selected_diagram_type": "concept_chain",
        }
    return {
        "id": document_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "document_type": document_type,
        "status": status,
        "style": "study-notes",
        "document_json": document_json,
        "source_hash": "hash-1",
    }


def _state(
    status="success",
    document_id="visual-1",
    *,
    owner_type="study",
    owner_id="view-1",
    document_type="overview",
):
    record = _record(
        status,
        document_id,
        owner_type=owner_type,
        owner_id=owner_id,
        document_type=document_type,
    )
    document_json = record.get("document_json") or {}
    return {
        "document": record,
        "latest_attempt": record,
        "diagram_recommendations": document_json.get("diagram_recommendations", []),
        "selected_diagram_type": document_json.get("selected_diagram_type"),
        "stale": False,
        "phase": "completed" if status == "success" else "generating_visual",
        "source_progress": {"stage": "ready_for_generation", "percent": 100},
        "generation_progress": None,
        "interpretation_sections": [
            {
                "id": "section-1",
                "title": "第一节",
                "markdown": "第一节解读",
                "source_ref_ids": [f"{owner_type}:{owner_id}:summary"],
            }
        ],
        "interpretation_available": True,
        "workflow_progress": {
            "stage": "completed",
            "overall_percent": 100,
        },
    }


def test_get_study_visual_state_recovers_stale_jobs(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.get_study_state.return_value = _state()
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).get(
        "/api/visual-learning/study/view-1?document_type=overview"
    )

    assert response.status_code == 200
    assert response.json()["data"]["document"]["id"] == "visual-1"
    assert set(response.json()["data"]) == {
        "document",
        "latest_attempt",
        "diagram_recommendations",
        "selected_diagram_type",
        "stale",
        "phase",
        "source_progress",
        "generation_progress",
        "interpretation_sections",
        "interpretation_available",
        "workflow_progress",
    }
    service.repository.recover_stale_generations.assert_called_once_with(20)


def test_get_study_visual_state_maps_source_errors(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotFound,
        VisualLearningSourceNotReady,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)
    client = TestClient(_build_app())

    service.get_study_state.side_effect = VisualLearningSourceNotFound()
    assert client.get("/api/visual-learning/study/missing").status_code == 404

    service.get_study_state.side_effect = VisualLearningSourceNotReady()
    assert client.get("/api/visual-learning/study/view-1").status_code == 409


def test_generate_study_visual_returns_pending_and_runs_background(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_study_generation.return_value = _record("pending")
    service.get_study_state.return_value = _state("pending")
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/study/view-1/generate",
        json={
            "document_type": "overview",
            "style": "study-notes",
            "diagram_type": "auto",
            "force": False,
        },
    )

    assert response.status_code == 202
    assert response.json()["data"]["latest_attempt"]["status"] == "pending"
    service.generate_prepared_study.assert_called_once_with(
        "visual-1", "view-1", "overview", "study-notes", "auto"
    )


def test_generate_study_visual_reuses_success_without_background(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_study_generation.return_value = _record("success")
    service.get_study_state.return_value = _state("success")
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/study/view-1/generate",
        json={"document_type": "overview"},
    )

    assert response.status_code == 200
    service.generate_prepared_study.assert_not_called()


def test_generate_study_visual_rejects_invalid_options(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_study_generation.side_effect = ValueError("invalid document_type")
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/study/view-1/generate",
        json={"document_type": "poster"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid document_type"


def test_generate_waits_for_source_analysis_without_creating_document(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_study_generation.side_effect = VisualLearningSourceNotReady(
        "full analysis pending",
        source_progress={"stage": "waiting_analysis", "percent": 80},
    )
    service.get_study_state.return_value = {
        "document": None,
        "latest_attempt": None,
        "diagram_recommendations": [],
        "selected_diagram_type": None,
        "stale": False,
        "phase": "source_processing",
        "source_progress": {"stage": "waiting_analysis", "percent": 80},
        "generation_progress": None,
        "interpretation_sections": [],
        "interpretation_available": False,
        "workflow_progress": {
            "stage": "source_processing",
            "overall_percent": 80,
        },
    }
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/study/view-1/generate",
        json={"document_type": "diagram"},
    )

    assert response.status_code == 202
    assert response.json()["data"]["phase"] == "source_processing"
    service.generate_prepared_study.assert_not_called()


def test_generate_rejects_terminal_missing_summary(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_study_generation.side_effect = VisualLearningSourceNotReady(
        "full analysis failed",
        source_progress={"stage": "failed", "percent": 0},
        terminal=True,
    )
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/study/view-1/generate",
        json={"document_type": "diagram"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "全文分析失败，请重新提交内容"


def test_visual_learning_service_factory_reuses_cached_collection_service(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    collection_service = MagicMock(name="cached_collection_service")
    cache_manager = MagicMock(db_path="/tmp/visual-learning-test.db")
    monkeypatch.setattr(visual_learning, "get_config", lambda: {})
    monkeypatch.setattr(visual_learning, "get_cache_manager", lambda: cache_manager)
    monkeypatch.setattr(
        visual_learning,
        "get_collection_service",
        MagicMock(return_value=collection_service),
    )

    service = visual_learning.get_visual_learning_service()

    assert service.collection_source_resolver.collection_service is collection_service
    visual_learning.get_collection_service.assert_called_once_with()


def test_collection_visual_routes_require_authentication(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)
    client = TestClient(_build_app(authenticated=False))

    get_response = client.get("/api/visual-learning/collections/collection-1")
    post_response = client.post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "overview"},
    )

    assert get_response.status_code == 401
    assert post_response.status_code == 401
    service.repository.recover_stale_generations.assert_not_called()


def test_get_collection_visual_state_recovers_stale_jobs(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.get_collection_state.return_value = _state(
        owner_type="collection",
        owner_id="collection-1",
    )
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).get(
        "/api/visual-learning/collections/collection-1?document_type=overview"
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "集合视觉学习状态",
        "data": _state(owner_type="collection", owner_id="collection-1"),
    }
    service.repository.recover_stale_generations.assert_called_once_with(20)
    service.get_collection_state.assert_called_once_with("collection-1", "overview")


def test_get_collection_visual_state_maps_source_and_option_errors(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotFound,
        VisualLearningSourceNotReady,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)
    client = TestClient(_build_app())

    service.get_collection_state.side_effect = VisualLearningSourceNotFound()
    assert client.get("/api/visual-learning/collections/missing").status_code == 404

    service.get_collection_state.side_effect = VisualLearningSourceNotReady()
    assert client.get("/api/visual-learning/collections/collection-1").status_code == 409

    service.get_collection_state.side_effect = ValueError("invalid document_type")
    response = client.get(
        "/api/visual-learning/collections/collection-1?document_type=diagram"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid document_type"


def test_generate_collection_visual_returns_pending_and_runs_background(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_collection_generation.return_value = _record(
        "pending",
        owner_type="collection",
        owner_id="collection-1",
        document_type="full_note",
    )
    service.get_collection_state.return_value = _state(
        "pending",
        owner_type="collection",
        owner_id="collection-1",
        document_type="full_note",
    )
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/collections/collection-1/generate",
        json={
            "document_type": "full_note",
            "style": "clean-lecture",
            "diagram_type": "hierarchy",
            "force": True,
        },
    )

    assert response.status_code == 202
    assert response.json()["data"] == _state(
        "pending",
        owner_type="collection",
        owner_id="collection-1",
        document_type="full_note",
    )
    service.prepare_collection_generation.assert_called_once_with(
        "collection-1", "full_note", "clean-lecture", "hierarchy", True
    )
    service.generate_prepared_collection.assert_called_once_with(
        "visual-1", "collection-1", "full_note", "clean-lecture", "hierarchy"
    )


def test_generate_collection_visual_safely_records_preclaim_background_failure(
    monkeypatch,
):
    from video_transcript_api.api.routes import visual_learning

    pending_record = {
        **_record(
            "pending",
            owner_type="collection",
            owner_id="collection-1",
        ),
        "generation_token": "",
        "request_key": "request-key-1",
        "error_message": None,
        "progress_json": None,
    }
    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_collection_generation.return_value = pending_record
    service.get_collection_state.return_value = _state(
        "pending",
        owner_type="collection",
        owner_id="collection-1",
    )
    service.generate_prepared_collection.side_effect = RuntimeError(
        "sensitive upstream detail"
    )
    service.repository.get_document.return_value = pending_record
    service.repository.claim_generation.return_value = "fallback-token"
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "overview"},
    )

    assert response.status_code == 202
    service.repository.get_document.assert_called_once_with("visual-1")
    service.repository.claim_generation.assert_called_once_with(
        "visual-1", previous_token=""
    )
    service.repository.save_failure.assert_called_once_with(
        "visual-1",
        "fallback-token",
        "visual generation failed before start",
    )


def test_generate_collection_visual_does_not_overwrite_when_fallback_claim_loses(
    monkeypatch,
):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotFound,
    )

    pending_record = {
        **_record(
            "pending",
            owner_type="collection",
            owner_id="collection-1",
        ),
        "generation_token": "old-token",
        "request_key": "request-key-1",
        "error_message": None,
        "progress_json": None,
    }
    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_collection_generation.return_value = pending_record
    service.get_collection_state.return_value = _state(
        "pending",
        owner_type="collection",
        owner_id="collection-1",
    )
    service.generate_prepared_collection.side_effect = VisualLearningSourceNotFound(
        "source disappeared"
    )
    service.repository.get_document.return_value = pending_record
    service.repository.claim_generation.return_value = None
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "overview"},
    )

    assert response.status_code == 202
    service.repository.claim_generation.assert_called_once_with(
        "visual-1", previous_token="old-token"
    )
    service.repository.save_failure.assert_not_called()


def test_generate_collection_visual_reuses_success_without_background(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_collection_generation.return_value = _record(
        owner_type="collection",
        owner_id="collection-1",
    )
    service.get_collection_state.return_value = _state(
        owner_type="collection",
        owner_id="collection-1",
    )
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "overview"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "已复用集合视觉学习内容"
    service.generate_prepared_collection.assert_not_called()


def test_generate_collection_visual_maps_not_found_and_invalid_options(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotFound,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)
    client = TestClient(_build_app())

    service.prepare_collection_generation.side_effect = VisualLearningSourceNotFound()
    assert (
        client.post(
            "/api/visual-learning/collections/missing/generate",
            json={"document_type": "overview"},
        ).status_code
        == 404
    )

    service.prepare_collection_generation.side_effect = ValueError(
        "invalid document_type"
    )
    response = client.post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "diagram"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid document_type"


def test_generate_collection_visual_returns_pending_while_summary_processes(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_collection_generation.side_effect = VisualLearningSourceNotReady(
        "collection summary pending",
        source_progress={"stage": "waiting_summary", "percent": 80},
    )
    pending_state = {
        "document": None,
        "latest_attempt": None,
        "diagram_recommendations": [],
        "selected_diagram_type": None,
        "stale": False,
        "phase": "source_processing",
        "source_progress": {"stage": "waiting_summary", "percent": 80},
        "generation_progress": None,
        "interpretation_sections": [],
        "interpretation_available": False,
        "workflow_progress": {
            "stage": "source_processing",
            "overall_percent": 80,
        },
    }
    service.get_collection_state.return_value = pending_state
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "overview"},
    )

    assert response.status_code == 202
    assert response.json()["data"] == pending_state
    service.get_collection_state.assert_called_once_with("collection-1", "overview")
    service.generate_prepared_collection.assert_not_called()


def test_generate_collection_visual_rejects_terminal_missing_summary(monkeypatch):
    from video_transcript_api.api.routes import visual_learning
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    service = MagicMock()
    service.repository.recover_stale_generations.return_value = 0
    service.prepare_collection_generation.side_effect = VisualLearningSourceNotReady(
        "collection summary is not ready",
        source_progress={"stage": "failed", "percent": 0},
        terminal=True,
    )
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).post(
        "/api/visual-learning/collections/collection-1/generate",
        json={"document_type": "overview"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "集合摘要不可用，无法生成视觉学习内容"


def test_get_visual_document_and_recent_diagrams(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.get_document_state.return_value = _state(document_id="visual-2")
    service.repository.list_recent.return_value = [
        _record("success", document_id="visual-2")
    ]
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)
    client = TestClient(_build_app())

    detail = client.get("/api/visual-learning/documents/visual-2")
    recent = client.get(
        "/api/visual-learning/documents?document_type=diagram&limit=10"
    )

    assert detail.status_code == 200
    assert detail.json()["data"]["document"]["id"] == "visual-2"
    assert recent.status_code == 200
    assert recent.json()["data"]["documents"][0]["id"] == "visual-2"
    service.repository.list_recent.assert_called_once_with("diagram", 10)


def test_get_visual_document_returns_404(monkeypatch):
    from video_transcript_api.api.routes import visual_learning

    service = MagicMock()
    service.get_document_state.return_value = None
    monkeypatch.setattr(visual_learning, "get_visual_learning_service", lambda: service)

    response = TestClient(_build_app()).get(
        "/api/visual-learning/documents/missing"
    )

    assert response.status_code == 404


def test_visual_learning_page_serves_static_shell(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import visual_learning

    page = tmp_path / "visual-learning.html"
    page.write_text("<html><head></head><body>图解生成</body></html>", encoding="utf-8")
    monkeypatch.setattr(visual_learning, "get_static_dir", lambda: tmp_path)

    response = TestClient(_build_app()).get("/visual-learning")

    assert response.status_code == 200
    assert "图解生成" in response.text
    assert '<base href="/static/">' in response.text


def test_main_app_registers_visual_learning_routes():
    from video_transcript_api.api.app import create_app

    paths = {route.path for route in create_app().routes}

    assert "/visual-learning" in paths
    assert "/api/visual-learning/study/{view_token}" in paths
    assert "/api/visual-learning/study/{view_token}/generate" in paths
    assert "/api/visual-learning/collections/{collection_id}" in paths
    assert "/api/visual-learning/collections/{collection_id}/generate" in paths
