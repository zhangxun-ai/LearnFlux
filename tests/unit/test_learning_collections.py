from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path

from video_transcript_api.cache.cache_manager import CacheManager


def test_collection_repository_persists_sources_and_markdown(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    db_path = tmp_path / "collections.db"
    repo = LearningCollectionRepository(db_path=str(db_path))

    collection = repo.create_collection(
        title="如何走出人生困局",
        collection_type="video_course",
        goal="沉淀破局方法论",
    )
    repo.add_source(
        collection_id=collection["id"],
        task_id="task-1",
        view_token="view-1",
        title="1.mp4",
        source_type="video",
        position=1,
    )
    repo.add_source(
        collection_id=collection["id"],
        task_id="task-2",
        view_token="view-2",
        title="2.mp4",
        source_type="video",
        position=2,
    )

    detail = repo.get_collection_detail(collection["id"])
    assert detail["title"] == "如何走出人生困局"
    assert detail["collection_type"] == "video_course"
    assert [source["title"] for source in detail["sources"]] == ["1.mp4", "2.mp4"]

    markdown = "# 如何走出人生困局\n\n## SOP\n写下困局 -> 找可控变量"
    repo.save_summary(collection["id"], markdown)

    updated = repo.get_collection_detail(collection["id"])
    assert updated["summary_status"] == "success"
    assert "找可控变量" in updated["summary_markdown"]


def test_collection_repository_rejects_mixed_source_type(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    collection = repo.create_collection(
        title="如何走出人生困局",
        collection_type="video_course",
    )

    try:
        repo.add_source(
            collection_id=collection["id"],
            task_id="task-doc",
            view_token="view-doc",
            title="note.pdf",
            source_type="document",
            position=1,
        )
    except ValueError as exc:
        assert "video_course" in str(exc)
    else:
        raise AssertionError("Expected mixed source type to be rejected")


def test_collection_summary_requires_all_sources_ready(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_info = cache_manager.create_task(
        url="local://1/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="media-1",
    )
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        summary_generator=lambda collection, sources: "# should not run",
    )
    collection = service.create_collection(
        title="如何走出人生困局",
        collection_type="video_course",
    )
    service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    detail = service.get_collection_detail(collection["id"])
    assert detail["sources"][0]["task_status"] == "queued"

    try:
        service.generate_summary(collection["id"])
    except ValueError as exc:
        assert "all sources" in str(exc)
    else:
        raise AssertionError("Expected collection summary to wait for parsed sources")


def test_collection_source_detail_returns_content_and_timing(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_info = cache_manager.create_task(
        url="local://collection-source/local_hash/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="local_hash",
    )
    cache_manager.save_cache(
        platform="generic",
        url="local://collection-source/local_hash/1.mp4",
        media_id="local_hash",
        use_speaker_recognition=False,
        transcript_data="第一节说明困局要先拆出可控变量。",
        transcript_type="capswriter",
        title="1.mp4",
        author="本地上传",
        description="",
    )
    cache_manager.save_llm_result(
        platform="generic",
        media_id="local_hash",
        use_speaker_recognition=False,
        llm_type="summary",
        content="## 单篇总结\n先拆可控变量。",
    )
    cache_manager.update_task_status(
        task_info["task_id"],
        "success",
        platform="generic",
        media_id="local_hash",
        title="1.mp4",
        author="本地上传",
    )

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("如何走出人生困局", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    detail = service.get_source_detail(collection["id"], source["id"])
    assert detail["task_status"] == "success"
    assert "可控变量" in detail["transcript"]
    assert "单篇总结" in detail["summary"]
    assert detail["created_at"]
    assert detail["completed_at"]
    assert isinstance(detail["elapsed_seconds"], int)


def test_collection_api_create_generate_and_export_markdown(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_info = cache_manager.create_task(
        url="local://1/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="media-1",
    )
    cache_manager.save_cache(
        platform="generic",
        url="local://1/1.mp4",
        media_id="media-1",
        use_speaker_recognition=False,
        transcript_data="第一节说明困局不是没有路，而是没有拆出可控变量。",
        transcript_type="capswriter",
        title="1.mp4",
        author="本地上传",
        description="",
    )
    cache_manager.update_task_status(
        task_info["task_id"],
        "success",
        platform="generic",
        media_id="media-1",
        title="1.mp4",
        author="本地上传",
    )

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        summary_generator=lambda collection, sources: "# 如何走出人生困局\n\n## 行动清单\n找可控变量",
    )

    monkeypatch.setattr(collections, "get_collection_service", lambda: service)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    created = client.post(
        "/api/collections",
        json={"title": "如何走出人生困局", "collection_type": "video_course"},
    )
    assert created.status_code == 200
    collection_id = created.json()["data"]["id"]

    service.add_existing_source(
        collection_id=collection_id,
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    generated = client.post(f"/api/collections/{collection_id}/summary")
    assert generated.status_code == 200
    assert "找可控变量" in generated.json()["data"]["summary_markdown"]
    assert generated.json()["data"]["sources"][0]["task_status"] == "success"

    exported = client.get(f"/api/collections/{collection_id}/export/markdown")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "## 行动清单" in exported.text


def test_collection_upload_reuses_cached_local_file(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    file_bytes = b"same local video bytes"
    media_id = collections._media_id_for_upload_hash(collections._sha256_bytes(file_bytes))

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_info = cache_manager.create_task(
        url=f"local://collection-source/{media_id}/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id=media_id,
    )
    cache_manager.save_cache(
        platform="generic",
        url=f"local://collection-source/{media_id}/1.mp4",
        media_id=media_id,
        use_speaker_recognition=False,
        transcript_data="cached transcript",
        transcript_type="capswriter",
        title="1.mp4",
        author="本地上传",
        description="",
    )
    cache_manager.update_task_status(
        task_info["task_id"],
        "success",
        platform="generic",
        media_id=media_id,
        title="1.mp4",
        author="本地上传",
    )

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("如何走出人生困局", "video_course")

    monkeypatch.setattr(collections, "cache_manager", cache_manager)
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)

    def fail_if_processing_starts(*args, **kwargs):
        raise AssertionError("cached local file should not start another transcription")

    monkeypatch.setattr(collections, "process_local_upload", fail_if_processing_starts)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("1.mp4", file_bytes, "video/mp4"))],
    )

    assert response.status_code == 202
    source = response.json()["data"]["sources"][0]
    assert source["reused"] is True
    assert source["task_id"] == task_info["task_id"]


def test_collections_page_restores_existing_collections():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")

    assert "collection-history-list" in html
    assert "loadCollections" in js
    assert "apiJSON('/api/collections')" in js
    assert "selectCollection" in js
