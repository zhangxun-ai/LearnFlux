from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


async def _user():
    return {"user_id": "u1", "api_key": "test"}


def _app(authorized=True):
    from video_transcript_api.api.routes import obsidian
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(obsidian.router)
    if authorized:
        app.dependency_overrides[verify_token] = _user
    else:
        async def unauthorized():
            raise HTTPException(status_code=401, detail="unauthorized")
        app.dependency_overrides[verify_token] = unauthorized
    return app


def _runtime(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import obsidian
    from video_transcript_api.obsidian.knowledge_models import KnowledgeItem

    vault = tmp_path / "vault"
    (vault / "raw" / "AI").mkdir(parents=True)
    (vault / "raw" / "其他").mkdir()
    settings = {
        "enabled": True,
        "vault_id": "vault",
        "vault_path": str(vault),
        "knowledge_raw_root": "raw",
        "knowledge_processed_root": "processed",
    }
    repo = MagicMock()
    binding = {
        "id": "b1",
        "owner_user_id": "u1",
        "scope_type": "single",
        "scope_id": "view-1",
        "vault_id": "vault",
        "category": "AI",
        "collection_directory": "",
        "revision": 1,
    }
    repo.get_binding.return_value = binding
    repo.save_binding.return_value = binding
    sync = MagicMock()
    sync.preview.return_value = {
        "binding_revision": 1,
        "items": [{"documents": [{"state": "new"}]}],
        "preconditions": [{"context_key": "k"}],
    }
    sync.apply.return_value = {
        "items": [{"documents": [{"status": "created"}]}],
        "counts": {"created": 1},
    }
    resolver = MagicMock()
    single_item = KnowledgeItem(
        "u1", "view-1", "标题", "原文", "解读", "online_url", "https://e"
    )
    resolver.resolve_single.return_value = single_item
    collection_items = [
        KnowledgeItem(
            "u1", "v1", "01", "r1", "a1", "online_url", "https://e/1",
            "c1", "s1", "作者-专题", "作者", 1,
        ),
        KnowledgeItem(
            "u1", "v2", "02", "r2", "a2", "online_url", "https://e/2",
            "c1", "s2", "作者-专题", "作者", 2,
        ),
    ]
    resolver.resolve_collection.return_value = (
        {
            "id": "c1",
            "title": "专题",
            "creator_name": "作者",
            "sources": [{"id": "s1"}, {"id": "s2"}],
        },
        collection_items,
        [{"source_id": "s3", "code": "analysis_not_ready"}],
    )
    recommender = MagicMock()
    recommender.recommend.return_value = MagicMock(
        category="AI", confidence=0.9, reason="match", recommended_by="llm"
    )
    recommender.recommend_collection.return_value = recommender.recommend.return_value
    monkeypatch.setattr(obsidian, "_configured_settings", lambda: settings)
    monkeypatch.setattr(obsidian, "get_obsidian_knowledge_repository", lambda: repo)
    monkeypatch.setattr(obsidian, "get_obsidian_knowledge_service", lambda: sync)
    monkeypatch.setattr(obsidian, "get_obsidian_source_resolver", lambda: resolver)
    monkeypatch.setattr(obsidian, "get_obsidian_category_recommender", lambda: recommender)
    monkeypatch.setattr(obsidian, "_require_owned_single_content", lambda *_: None)
    monkeypatch.setattr(obsidian, "_require_owned_collection", lambda *_: None)
    return repo, sync, resolver, recommender, binding


def test_knowledge_routes_require_authentication():
    assert TestClient(_app(authorized=False)).get(
        "/api/obsidian/knowledge/categories"
    ).status_code == 401


def test_categories_and_recommendation_use_server_content(monkeypatch, tmp_path):
    _repo, _sync, resolver, recommender, _binding = _runtime(
        monkeypatch, tmp_path
    )
    client = TestClient(_app())

    categories = client.get("/api/obsidian/knowledge/categories")
    recommendation = client.post(
        "/api/obsidian/knowledge/single/view-1/recommend-category",
        json={"raw_content": "client must not control prompt"},
    )

    assert categories.json()["data"]["items"] == ["AI", "其他"]
    assert recommendation.status_code == 200
    assert recommendation.json()["data"]["category"] == "AI"
    item = resolver.resolve_single.return_value
    recommender.recommend.assert_called_once_with(
        candidates=["AI", "其他"],
        title=item.title,
        analysis_excerpt=item.analysis_content,
        raw_excerpt=item.raw_content,
    )


def test_single_binding_preview_apply_and_stale_contract(monkeypatch, tmp_path):
    from video_transcript_api.obsidian.knowledge_service import (
        KnowledgeStalePreview,
    )

    repo, sync, _resolver, _recommender, binding = _runtime(
        monkeypatch, tmp_path
    )
    client = TestClient(_app())
    loaded = client.get("/api/obsidian/knowledge/single/view-1/binding")
    saved = client.put(
        "/api/obsidian/knowledge/single/view-1/binding",
        json={"category": "AI", "expected_revision": 1},
    )
    preview = client.post(
        "/api/obsidian/knowledge/single/view-1/preview", json={}
    )
    missing = client.post(
        "/api/obsidian/knowledge/single/view-1/apply",
        json={"expected_binding_revision": 1},
    )
    applied = client.post(
        "/api/obsidian/knowledge/single/view-1/apply",
        json={
            "expected_binding_revision": 1,
            "preconditions": [
                {
                    "context_key": "k",
                    "document_type": "raw",
                    "relative_path": "raw/AI/a.md",
                    "desired_hash": "d",
                    "existing_hash": "__absent__",
                }
            ],
        },
    )

    assert loaded.json()["data"]["binding"]["id"] == "b1"
    assert saved.status_code == 200
    assert preview.json()["data"]["binding_revision"] == 1
    assert missing.status_code == 422
    assert applied.json()["data"]["counts"] == {"created": 1}
    repo.save_binding.assert_called_once()

    sync.apply.side_effect = KnowledgeStalePreview(
        {"binding_revision": 1, "items": []}
    )
    stale = client.post(
        "/api/obsidian/knowledge/single/view-1/apply",
        json={
            "expected_binding_revision": 1,
            "preconditions": [
                {
                    "context_key": "k",
                    "document_type": "raw",
                    "relative_path": "raw/AI/a.md",
                    "desired_hash": "d",
                    "existing_hash": "__absent__",
                }
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_preview"
    assert stale.json()["detail"]["latest_preview"]["items"] == []


def test_collection_selected_incremental_and_force_resolve_correct_sources(
    monkeypatch, tmp_path
):
    repo, sync, resolver, _recommender, binding = _runtime(
        monkeypatch, tmp_path
    )
    collection_binding = {
        **binding,
        "scope_type": "collection",
        "scope_id": "c1",
        "collection_directory": "作者-专题",
    }
    repo.get_binding.return_value = collection_binding
    repo.save_binding.return_value = collection_binding
    client = TestClient(_app())

    selected = client.post(
        "/api/obsidian/knowledge/collections/c1/preview",
        json={"source_ids": ["s2"], "sync_all": False, "force": False},
    )
    sync.preview.return_value = {
        "binding_revision": 1,
        "items": [{"documents": [{"state": "unchanged"}]}],
        "preconditions": [{"context_key": "k"}],
    }
    incremental = client.post(
        "/api/obsidian/knowledge/collections/c1/preview",
        json={"sync_all": True, "force": False},
    )
    forced = client.post(
        "/api/obsidian/knowledge/collections/c1/preview",
        json={"sync_all": True, "force": True},
    )
    invalid_force = client.post(
        "/api/obsidian/knowledge/collections/c1/preview",
        json={"source_ids": ["s1"], "force": True},
    )
    applied = client.post(
        "/api/obsidian/knowledge/collections/c1/apply",
        json={
            "sync_all": True,
            "force": True,
            "expected_binding_revision": 1,
            "preconditions": [
                {
                    "context_key": "k",
                    "document_type": "raw",
                    "relative_path": "raw/AI/作者-专题/a.md",
                    "desired_hash": "d",
                    "existing_hash": "__absent__",
                }
            ],
        },
    )

    assert selected.status_code == incremental.status_code == forced.status_code == 200
    calls = resolver.resolve_collection.call_args_list
    assert calls[0].args == ("u1", "c1", ["s2"])
    assert calls[1].args == ("u1", "c1", None)
    assert calls[2].args == ("u1", "c1", None)
    assert calls[3].args == ("u1", "c1", None)
    assert sync.preview.call_args_list[1].kwargs["force"] is False
    assert sync.preview.call_args_list[2].kwargs["force"] is True
    assert sync.apply.call_args.kwargs["force"] is True
    assert selected.json()["data"]["unavailable"][0]["code"] == "analysis_not_ready"
    assert incremental.json()["data"]["counts"]["unchanged"] == 1
    assert applied.json()["data"]["counts"] == {"created": 1}
    assert applied.json()["data"]["unavailable"][0]["code"] == "analysis_not_ready"
    assert invalid_force.status_code == 422


def test_ownership_failures_are_hidden_as_404(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import obsidian

    _runtime(monkeypatch, tmp_path)

    def hidden(*_args):
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    monkeypatch.setattr(obsidian, "_require_owned_single_content", hidden)
    response = TestClient(_app()).get(
        "/api/obsidian/knowledge/single/other/binding"
    )
    assert response.status_code == 404
