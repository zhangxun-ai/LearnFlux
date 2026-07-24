from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _fake_verify_token():
    return {"user_id": "user-a", "api_key": "sk-test"}


def _app():
    from video_transcript_api.api.routes import study
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(study.router)
    app.dependency_overrides[verify_token] = _fake_verify_token
    return app


def test_collection_media_grant_is_bound_to_collection_source():
    from video_transcript_api.study.media_access import StudyMediaAccess

    access = StudyMediaAccess("secret", clock=lambda: 100)
    token = access.issue_collection(
        user_id="user-a", collection_id="c1", source_id="s1", ttl_seconds=20
    )

    payload = access.verify_collection(token, collection_id="c1", source_id="s1")

    assert payload["user_id"] == "user-a"
    for context in [("c2", "s1"), ("c1", "s2")]:
        try:
            access.verify_collection(token, collection_id=context[0], source_id=context[1])
        except ValueError:
            pass
        else:
            raise AssertionError("cross-context media grant was accepted")


def test_collection_notes_are_isolated_even_when_view_token_is_shared(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repository = StudyRepository(str(tmp_path / "study.db"))
    repository.create_note(
        "shared", 12, "A note", owner_user_id="user-a", collection_id="c1", source_id="s1"
    )
    repository.create_note(
        "shared", 12, "B note", owner_user_id="user-a", collection_id="c2", source_id="s2"
    )

    notes = repository.list_notes(
        "shared", owner_user_id="user-a", collection_id="c1", source_id="s1"
    )

    assert [note["body"] for note in notes] == ["A note"]


def test_collection_study_session_resolves_exact_source(monkeypatch):
    from video_transcript_api.api.routes import study

    collection_service = MagicMock()
    collection_service.repository.get_collection.return_value = {
        "id": "c1", "owner_user_id": "user-a"
    }
    collection_service.get_source_detail.return_value = {
        "id": "s2", "view_token": "shared-token", "title": "Episode 2.mp4"
    }
    collection_service.get_collection_detail.return_value = {
        "id": "c1",
        "title": "Course",
        "sources": [
            {"id": "s1", "title": "Episode 1.mp4", "position": 1},
            {"id": "s2", "title": "Episode 2.mp4", "position": 2},
        ],
    }
    study_service = MagicMock()
    study_service.get_collection_session.return_value = {
        "state": "ready",
        "metadata": {"title": "Episode 2.mp4"},
        "playback": {"source_available": True},
        "source": {"kind": "video"},
        "transcript": {"lines": []},
        "ai": {},
        "notes": [],
    }
    access = MagicMock()
    access.issue_collection.return_value = "signed"
    monkeypatch.setattr(study, "get_collection_service", lambda: collection_service)
    monkeypatch.setattr(study, "get_study_service", lambda: study_service)
    monkeypatch.setattr(study, "get_study_media_access", lambda: access)

    response = TestClient(_app()).get("/api/study/collections/c1/sources/s2")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["collection"]["current_source_id"] == "s2"
    assert data["playback"]["source_url"].endswith("media_token=signed")
    study_service.get_collection_session.assert_called_once_with(
        "shared-token", owner_user_id="user-a", collection_id="c1", source_id="s2"
    )


def test_collection_study_rejects_cross_owner(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    service.repository.get_collection.return_value = {
        "id": "c1", "owner_user_id": "user-b"
    }
    monkeypatch.setattr(study, "get_collection_service", lambda: service)

    response = TestClient(_app()).get("/api/study/collections/c1/sources/s1")

    assert response.status_code == 404
