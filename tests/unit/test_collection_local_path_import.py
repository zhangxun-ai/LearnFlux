"""Zero-copy local path import for learning collections."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.api.routes import collections
from video_transcript_api.api.services.transcription import verify_token
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.collections.repository import LearningCollectionRepository
from video_transcript_api.collections.service import LearningCollectionService


def _build_client(tmp_path, monkeypatch):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repository = LearningCollectionRepository(tmp_path / "collections.db")
    service = LearningCollectionService(repository=repository, cache_manager=cache)
    collection = service.create_collection(
        "Series",
        "Teacher",
        "video_course",
        owner_user_id="owner",
        transcription_strategy="local",
        transcription_concurrency=1,
    )
    scheduled = []
    monkeypatch.setattr(collections, "cache_manager", cache)
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(
        collections,
        "get_transcription_concurrency_controller",
        lambda: type("C", (), {"update_soft_limits": staticmethod(lambda **kw: None)})(),
    )
    monkeypatch.setattr(
        collections,
        "process_local_upload",
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )
    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {
        "user_id": "owner",
        "api_key": "test",
    }
    return TestClient(app), collection, service, scheduled, tmp_path


def test_resolve_local_import_paths_uses_original_file_without_copy(tmp_path):
    media_dir = tmp_path / "course"
    media_dir.mkdir()
    video = media_dir / "01-intro.mp4"
    video.write_bytes(b"fake-video-bytes-for-hash")

    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repository = LearningCollectionRepository(tmp_path / "collections.db")
    service = LearningCollectionService(repository=repository, cache_manager=cache)
    collection = service.create_collection(
        "Course", "IP", "video_course", owner_user_id="owner"
    )

    candidates = service.resolve_local_import_paths(
        collection["id"],
        directory=str(media_dir),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["file_path"] == str(video.resolve())
    assert candidate["original_name"] == "01-intro.mp4"
    assert candidate["path_referenced"] is True
    assert candidate["content_sha256"]
    # Must not create managed copies under source_files.
    managed = tmp_path / "source_files"
    assert not managed.exists() or not any(managed.rglob("*.mp4"))


def test_from_local_paths_endpoint_registers_sources_without_copy(tmp_path, monkeypatch):
    client, collection, service, scheduled, root = _build_client(tmp_path, monkeypatch)
    media_dir = root / "lessons"
    media_dir.mkdir()
    first = media_dir / "001-a.mp4"
    second = media_dir / "002-b.mp4"
    first.write_bytes(b"video-one")
    second.write_bytes(b"video-two")

    response = client.post(
        f"/api/collections/{collection['id']}/sources/from-local-paths",
        json={"directory": str(media_dir)},
    )

    assert response.status_code == 202, response.text
    payload = response.json()["data"]
    assert payload["candidate_count"] == 2
    assert payload["path_referenced"] is True
    assert payload["pending_count"] == 2
    assert len(scheduled) == 2

    detail = service.get_collection_detail(collection["id"])
    assert len(detail["sources"]) == 2
    # Background worker receives original absolute paths.
    launched_paths = {args[1] for args, _kwargs in scheduled}
    assert launched_paths == {str(first.resolve()), str(second.resolve())}
    # preserve_source_file is positional arg index 6 (True)
    for args, kwargs in scheduled:
        assert args[6] is True


def test_collections_page_prefers_local_path_zero_copy_import():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")

    assert 'id="local-import-path"' in html
    assert 'id="import-local-path"' in html
    assert "扫描路径并导入" in html
    assert "不复制视频" in html
    assert "from-local-paths" in js
    assert "importFromLocalDirectory" in js
    assert "appendLocalDirectoryToCurrentCollection" in js
    assert "path_referenced" in (
        project_root / "src/video_transcript_api/collections/service.py"
    ).read_text(encoding="utf-8")
