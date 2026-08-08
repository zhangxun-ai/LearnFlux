"""Zero-copy local path import for learning collections."""

import hashlib
import sqlite3
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


def _task_count(cache_manager):
    with sqlite3.connect(cache_manager.db_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM task_status").fetchone()[0])


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


def test_resolve_local_import_paths_accepts_mpeg_transport_stream(tmp_path):
    media_dir = tmp_path / "course"
    media_dir.mkdir()
    video = media_dir / "087-lesson.ts"
    video.write_bytes(b"mpeg-transport-stream")

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
    assert candidates[0]["file_path"] == str(video.resolve())
    assert candidates[0]["source_type"] == "video"


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


def test_from_local_paths_reconciles_legacy_source_by_media_id(
    tmp_path, monkeypatch
):
    client, collection, service, scheduled, root = _build_client(tmp_path, monkeypatch)
    media_dir = root / "lessons"
    media_dir.mkdir()
    video = media_dir / "001-a.mp4"
    content = b"legacy-video"
    video.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    media_id = f"local_{digest[:32]}"
    cache = service.cache_manager
    repository = service.repository
    old_task = cache.create_task(
        url=f"local://collection-source/{media_id}/001-a.mp4",
        platform="generic",
        media_id=media_id,
        owner_user_id="owner",
    )
    cache.update_task_status(
        old_task["task_id"],
        "success",
        platform="generic",
        media_id=media_id,
        title="001-a.mp4",
        cache_id=1,
    )
    legacy_source = repository.add_source(
        collection_id=collection["id"],
        task_id=old_task["task_id"],
        view_token=old_task["view_token"],
        title="001-a.mp4",
        source_type="video",
        position=1,
        content_sha256=None,
    )
    monkeypatch.setattr(
        cache,
        "get_cache",
        lambda **_kwargs: {"id": 1, "llm_summary": "ready"},
    )

    response = client.post(
        f"/api/collections/{collection['id']}/sources/from-local-paths",
        json={"directory": str(media_dir)},
    )

    assert response.status_code == 202, response.text
    payload = response.json()["data"]
    assert payload["candidate_count"] == 1
    assert payload["new_source_count"] == 0
    assert payload["existing_source_count"] == 0
    assert payload["reconciled_source_count"] == 1
    assert payload["pending_count"] == 0
    assert scheduled == []
    sources = repository.get_sources(collection["id"])
    assert len(sources) == 1
    assert sources[0]["id"] == legacy_source["id"]
    assert sources[0]["content_sha256"] == digest
    reconciled_task = cache.get_task_by_id(sources[0]["task_id"])
    assert reconciled_task["source_file_path"] == str(video.resolve())


def test_repeating_local_path_import_does_not_create_another_task(
    tmp_path, monkeypatch
):
    client, collection, service, scheduled, root = _build_client(tmp_path, monkeypatch)
    media_dir = root / "lessons"
    media_dir.mkdir()
    (media_dir / "001-a.mp4").write_bytes(b"video-one")

    first = client.post(
        f"/api/collections/{collection['id']}/sources/from-local-paths",
        json={"directory": str(media_dir)},
    )
    assert first.status_code == 202, first.text
    task_count = _task_count(service.cache_manager)
    scheduled.clear()

    second = client.post(
        f"/api/collections/{collection['id']}/sources/from-local-paths",
        json={"directory": str(media_dir)},
    )

    assert second.status_code == 202, second.text
    payload = second.json()["data"]
    assert payload["new_source_count"] == 0
    assert payload["existing_source_count"] == 1
    assert payload["reconciled_source_count"] == 0
    assert payload["pending_count"] == 0
    assert _task_count(service.cache_manager) == task_count
    assert len(service.repository.get_sources(collection["id"])) == 1
    assert scheduled == []


def test_collections_page_prefers_local_path_zero_copy_import():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")

    assert 'id="local-import-path"' in html
    assert 'id="import-local-path"' in html
    assert 'id="browse-local-path"' in html
    assert "选择文件夹并导入" in html
    assert "扫描路径并导入" not in html
    assert "from-local-paths" in js
    assert "importFromLocalDirectory" in js
    assert "startFolderImport" in js
    assert "importSelectedLocalDirectory" in js
    assert "appendLocalDirectoryToCurrentCollection" in js
    assert "existing_source_count" in js
    assert "new_source_count" in js
    assert "path_referenced" in (
        project_root / "src/video_transcript_api/collections/service.py"
    ).read_text(encoding="utf-8")
