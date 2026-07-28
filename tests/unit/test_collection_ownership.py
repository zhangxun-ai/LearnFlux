from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def test_collection_repository_persists_filters_and_backfills_owner(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repository = LearningCollectionRepository(str(tmp_path / "collections.db"))
    owned_a = repository.create_collection(
        title="Course A",
        creator_name="Alice",
        collection_type="video_course",
        owner_user_id="user-a",
    )
    repository.create_collection(
        title="Course B",
        creator_name="Bob",
        collection_type="video_course",
        owner_user_id="user-b",
    )
    legacy = repository.create_collection(
        title="Legacy Course",
        creator_name="Legacy",
        collection_type="video_course",
    )

    assert [item["id"] for item in repository.list_collections(owner_user_id="user-a")] == [owned_a["id"]]
    assert repository.get_filter_options(owner_user_id="user-a") == {
        "creator_names": ["Alice"],
        "titles": ["Course A"],
        "titles_by_creator": {"Alice": ["Course A"]},
    }

    repository.assign_unowned_collections("legacy_user")

    assert repository.get_collection(legacy["id"])["owner_user_id"] == "legacy_user"


def _collection_app(user_id="user-a"):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token

    async def fake_verify_token():
        return {"user_id": user_id, "api_key": "sk-test"}

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = fake_verify_token
    return app


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/collections/c1", {}),
        ("get", "/api/collections/c1/sources/s1", {}),
        ("post", "/api/collections/c1/sources/s1/retry", {}),
        (
            "post",
            "/api/collections/c1/sources/upload",
            {"files": {"files": ("lesson.mp4", b"video", "video/mp4")}},
        ),
        ("post", "/api/collections/c1/cancel", {}),
        ("post", "/api/collections/c1/summary", {}),
        ("get", "/api/collections/c1/knowledge-map", {}),
        (
            "post",
            "/api/collections/c1/knowledge-map",
            {"json": {"scope": "collection"}},
        ),
        ("get", "/api/collections/c1/export/markdown", {}),
        ("get", "/api/collections/c1/sources/s1/file", {}),
        ("post", "/api/collections/c1/sources/s1/reveal", {}),
    ],
)
def test_all_collection_resource_routes_reject_cross_owner(
    monkeypatch,
    method,
    path,
    kwargs,
):
    from video_transcript_api.api.routes import collections

    service = MagicMock()
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)

    def deny(*args, **kwargs):
        raise HTTPException(status_code=404, detail="collection not found")

    monkeypatch.setattr(collections, "_require_collection_owner", deny)

    response = getattr(TestClient(_collection_app()), method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json()["detail"] == "collection not found"


def test_collection_create_and_list_use_authenticated_owner(monkeypatch):
    from video_transcript_api.api.routes import collections

    service = MagicMock()
    service.create_collection.return_value = {"id": "c1"}
    service.list_collections.return_value = []
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    client = TestClient(_collection_app())

    created = client.post(
        "/api/collections",
        json={
            "title": "Course",
            "creator_name": "Alice",
            "collection_type": "video_course",
        },
    )
    listed = client.get("/api/collections")

    assert created.status_code == 200
    assert listed.status_code == 200
    assert service.create_collection.call_args.kwargs["owner_user_id"] == "user-a"
    assert service.list_collections.call_args.kwargs["owner_user_id"] == "user-a"
