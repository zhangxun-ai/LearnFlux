from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
import asyncio

from video_transcript_api.cache.cache_manager import CacheManager


def test_collection_repository_persists_sources_and_markdown(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    db_path = tmp_path / "collections.db"
    repo = LearningCollectionRepository(db_path=str(db_path))

    collection = repo.create_collection(
        title="如何走出人生困局",
        creator_name="屠龙胭脂",
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
    assert detail["creator_name"] == "屠龙胭脂"
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
        creator_name="屠龙胭脂",
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
        creator_name="屠龙胭脂",
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
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
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
    assert detail["source_access"]["kind"] == "local_missing"
    assert detail["source_access"]["view_url"].startswith("/view/")


def test_collection_source_detail_exposes_failure_reason(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_info = cache_manager.create_task(
        url="local://collection-source/local_hash/15.m4a",
        use_speaker_recognition=False,
        platform="generic",
        media_id="local_hash",
    )
    cache_manager.update_task_status(
        task_info["task_id"],
        "failed",
        error_message="本地转录失败: 音频解码失败",
    )

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("千里挑一之生涯规划课", "屠龙胭脂井", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="15.令人心动的offer还是令人心梗的offer.m4a",
        source_type="video",
        position=15,
    )

    detail = service.get_source_detail(collection["id"], source["id"])

    assert detail["task_status"] == "failed"
    assert detail["error_message"] == "本地转录失败: 音频解码失败"


def test_collection_source_retry_requeues_failed_local_source(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    source_dir = tmp_path / "source-files"
    source_dir.mkdir()
    source_file = source_dir / "local_hash.m4a"
    source_file.write_bytes(b"fake-audio")

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    failed_task = cache_manager.create_task(
        url="local://collection-source/local_hash/15.m4a",
        use_speaker_recognition=False,
        platform="generic",
        media_id="local_hash",
    )
    cache_manager.update_task_status(
        failed_task["task_id"],
        "failed",
        error_message="本地转录失败: 音频解码失败",
    )

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        source_file_dir=str(source_dir),
    )
    collection = service.create_collection("千里挑一之生涯规划课", "屠龙胭脂井", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=failed_task["task_id"],
        view_token=failed_task["view_token"],
        title="15.令人心动的offer还是令人心梗的offer.m4a",
        source_type="video",
        position=15,
    )

    scheduled = {}

    def fake_process_local_upload(*args):
        scheduled["args"] = args

    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(collections, "process_local_upload", fake_process_local_upload)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/{source['id']}/retry"
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["source"]["task_status"] == "queued"
    assert data["source"]["error_message"] is None
    assert data["source"]["task_id"] != failed_task["task_id"]
    assert scheduled["args"] == (
        data["source"]["task_id"],
        str(source_file),
        "15.令人心动的offer还是令人心梗的offer.m4a",
        "local://collection-source/local_hash/15.m4a",
        "local_hash",
        False,
        True,
    )


def test_collection_source_navigation_by_view_token(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    sources = []
    for index in range(1, 4):
        sources.append(
            service.add_existing_source(
                collection_id=collection["id"],
                task_id=f"task-{index}",
                view_token=f"view-{index}",
                title=f"{index}.mp4",
                source_type="video",
                position=index,
            )
        )

    navigation = service.get_source_navigation_by_view_token("view-2")

    assert navigation["collection"]["title"] == "如何走出人生困局"
    assert navigation["collection"]["url"] == (
        f"/collections?collection_id={collection['id']}&source_id={sources[1]['id']}"
    )
    assert navigation["current_number"] == 2
    assert navigation["total"] == 3
    assert navigation["current"]["title"] == "2.mp4"
    assert navigation["previous"]["view_url"] == "/view/view-1"
    assert navigation["next"]["view_url"] == "/view/view-3"
    assert [item["is_current"] for item in navigation["items"]] == [False, True, False]
    assert service.get_source_navigation_by_view_token("missing") is None


def test_collection_source_detail_exposes_preserved_local_source_file(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    source_dir = tmp_path / "source-files"
    source_dir.mkdir()
    (source_dir / "local_hash.mp4").write_bytes(b"fake-video")

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
    cache_manager.update_task_status(
        task_info["task_id"],
        "success",
        platform="generic",
        media_id="local_hash",
        title="1.mp4",
        author="本地上传",
    )

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        source_file_dir=str(source_dir),
    )
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    detail = service.get_source_detail(collection["id"], source["id"])

    assert detail["source_access"]["kind"] == "local_file"
    assert detail["source_access"]["url"].endswith(f"/sources/{source['id']}/file")
    assert detail["source_access"]["reveal_url"].endswith(f"/sources/{source['id']}/reveal")
    assert service.get_source_file_path(collection["id"], source["id"]).endswith("local_hash.mp4")


def test_collection_source_reveal_opens_preserved_local_file(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    source_dir = tmp_path / "source-files"
    source_dir.mkdir()
    source_file = source_dir / "local_hash.mp4"
    source_file.write_bytes(b"fake-video")

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_info = cache_manager.create_task(
        url="local://collection-source/local_hash/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="local_hash",
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
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        source_file_dir=str(source_dir),
    )
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    opened = {}
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(
        collections,
        "_reveal_path_in_file_manager",
        lambda path: opened.setdefault("path", path),
        raising=False,
    )

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/{source['id']}/reveal"
    )

    assert response.status_code == 200
    assert opened["path"] == str(source_file)
    assert response.json()["data"]["filename"] == "local_hash.mp4"


def test_collection_repository_persists_knowledge_maps(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    collection = repo.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    source = repo.add_source(
        collection_id=collection["id"],
        task_id="task-1",
        view_token="view-1",
        title="1.mp4",
        source_type="video",
        position=1,
    )
    map_payload = {
        "version": 1,
        "scope": "source",
        "title": "1.mp4 知识地图",
        "central_question": "这节课如何把困局变成结构问题？",
        "user_value": "帮助用户停止自责，先识别稳定受益方。",
        "layout": "argument",
        "nodes": [
            {
                "id": "benefit",
                "title": "谁从现状中获益",
                "summary": "先找稳定受益方，而不是先自责。",
                "user_value": "避免把结构性损耗误判成个人问题。",
                "evidence": "不要先问我是不是不够好。",
                "kind": "core",
                "anchor": {"type": "video_time", "label": "08:12", "seconds": 492},
                "source_ids": [source["id"]],
            }
        ],
        "edges": [],
        "path": ["benefit"],
    }

    saved = repo.save_knowledge_map(
        collection_id=collection["id"],
        scope="source",
        map_json=map_payload,
        source_id=source["id"],
        model="fake-model",
    )
    loaded = repo.get_knowledge_map(
        collection_id=collection["id"],
        scope="source",
        source_id=source["id"],
    )

    assert saved["scope"] == "source"
    assert loaded["map_json"]["central_question"] == "这节课如何把困局变成结构问题？"
    assert loaded["map_json"]["nodes"][0]["anchor"]["label"] == "08:12"
    assert loaded["model"] == "fake-model"


def test_learning_collection_service_generates_and_reuses_source_knowledge_map(tmp_path):
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
        transcript_data="08:12 不要先问我是不是不够好，先问谁因为这个结构获得稳定收益。",
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
        content="## 谁从现状中获益\n判断长期困局时，先找稳定受益方，而不是先自责。",
    )
    cache_manager.update_task_status(
        task_info["task_id"],
        "success",
        platform="generic",
        media_id="local_hash",
        title="1.mp4",
        author="本地上传",
    )

    calls = []

    def fake_map_generator(payload):
        calls.append(payload)
        return {
            "version": 1,
            "scope": payload["scope"],
            "title": "1.mp4 知识地图",
            "central_question": "这节课如何判断关系困局？",
            "user_value": "帮助用户从自责切换到结构判断。",
            "layout": "argument",
            "nodes": [
                {
                    "id": "benefit",
                    "title": "谁从现状中获益",
                    "summary": "判断长期困局时，先找稳定受益方。",
                    "user_value": "避免把结构性损耗误判成个人不够努力。",
                    "evidence": "08:12 不要先问我是不是不够好。",
                    "kind": "core",
                    "anchor": {"type": "video_time", "label": "08:12", "seconds": 492},
                    "source_ids": [payload["source"]["id"]],
                }
            ],
            "edges": [],
            "path": ["benefit"],
        }

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        knowledge_map_generator=fake_map_generator,
    )
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    generated = service.generate_knowledge_map(
        collection_id=collection["id"],
        scope="source",
        source_id=source["id"],
    )
    cached = service.generate_knowledge_map(
        collection_id=collection["id"],
        scope="source",
        source_id=source["id"],
    )

    assert generated["map_json"]["nodes"][0]["title"] == "谁从现状中获益"
    assert cached["map_json"] == generated["map_json"]
    assert len(calls) == 1
    assert calls[0]["source"]["summary"].startswith("## 谁从现状中获益")
    assert "08:12" in calls[0]["source"]["transcript"]


def test_learning_collection_service_builds_collection_map_from_source_maps(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task_ids = []
    for index, transcript in enumerate(
        [
            "00:10 先识别负资产关系，不要把结构问题全归因到自己身上。",
            "00:20 用利益结构判断谁从现状获益，再决定是否投入。",
        ],
        start=1,
    ):
        media_id = f"local_hash_{index}"
        task_info = cache_manager.create_task(
            url=f"local://collection-source/{media_id}/{index}.mp4",
            use_speaker_recognition=False,
            platform="generic",
            media_id=media_id,
        )
        task_ids.append(task_info)
        cache_manager.save_cache(
            platform="generic",
            url=f"local://collection-source/{media_id}/{index}.mp4",
            media_id=media_id,
            use_speaker_recognition=False,
            transcript_data=transcript,
            transcript_type="capswriter",
            title=f"{index}.mp4",
            author="本地上传",
            description="",
        )
        cache_manager.save_llm_result(
            platform="generic",
            media_id=media_id,
            use_speaker_recognition=False,
            llm_type="summary",
            content=f"## 小节 {index}\n{transcript}",
        )
        cache_manager.update_task_status(
            task_info["task_id"],
            "success",
            platform="generic",
            media_id=media_id,
            title=f"{index}.mp4",
            author="本地上传",
        )

    calls = []

    def fake_map_generator(payload):
        calls.append(payload)
        if payload["scope"] == "collection":
            source_ids = [
                item["source"]["id"]
                for item in payload["source_maps"]
            ]
            return {
                "version": 1,
                "scope": "collection",
                "title": "如何走出人生困局集合地图",
                "central_question": "这个系列如何把人生困局转成可判断、可行动的结构问题？",
                "user_value": "帮助用户从全局理解系列主线，再选择最需要深看的小节。",
                "layout": "mainline",
                "nodes": [
                    {
                        "id": "mainline",
                        "title": "从自责转向结构判断",
                        "summary": "系列主线是先识别结构，再决定行动。",
                        "user_value": "先建立全局地图，避免逐集迷路。",
                        "evidence": "source 地图共同指向负资产关系与利益结构。",
                        "kind": "core",
                        "anchor": {"type": "global", "label": "全局", "seconds": None},
                        "source_ids": source_ids,
                    }
                ],
                "edges": [],
                "path": ["mainline"],
            }
        source_id = payload["source"]["id"]
        return {
            "version": 1,
            "scope": "source",
            "title": f"{payload['source']['title']} 知识地图",
            "central_question": "这节课贡献了什么关键判断？",
            "user_value": "帮助集合地图理解这个 source 的角色。",
            "layout": "argument",
            "nodes": [
                {
                    "id": f"node-{source_id}",
                    "title": "结构判断",
                    "summary": payload["source"]["transcript"],
                    "user_value": "识别这个 source 对主线的贡献。",
                    "evidence": payload["source"]["transcript"],
                    "kind": "concept",
                    "anchor": {"type": "video_time", "label": "00:10", "seconds": 10},
                    "source_ids": [source_id],
                }
            ],
            "edges": [],
            "path": [f"node-{source_id}"],
        }

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        knowledge_map_generator=fake_map_generator,
    )
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    for index, task_info in enumerate(task_ids, start=1):
        service.add_existing_source(
            collection_id=collection["id"],
            task_id=task_info["task_id"],
            view_token=task_info["view_token"],
            title=f"{index}.mp4",
            source_type="video",
            position=index,
        )

    generated = service.generate_knowledge_map(collection["id"], scope="collection")

    assert generated["map_json"]["central_question"].startswith("这个系列如何")
    assert generated["map_json"]["nodes"][0]["title"] == "从自责转向结构判断"
    assert [call["scope"] for call in calls] == ["source", "source", "collection"]
    assert "source_maps" in calls[-1]
    assert len(calls[-1]["source_maps"]) == 2


def test_collection_api_generates_and_reads_knowledge_map(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
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
        transcript_data="08:12 不要先问我是不是不够好，先问谁因为这个结构获得稳定收益。",
        transcript_type="capswriter",
        title="1.mp4",
        author="本地上传",
        description="",
    )
    cache_manager.update_task_status(
        task_info["task_id"],
        "success",
        platform="generic",
        media_id="local_hash",
        title="1.mp4",
        author="本地上传",
    )

    def fake_map_generator(payload):
        return {
            "version": 1,
            "scope": payload["scope"],
            "title": "1.mp4 知识地图",
            "central_question": "这节课如何判断关系困局？",
            "user_value": "帮助用户从自责切换到结构判断。",
            "layout": "argument",
            "nodes": [
                {
                    "id": "benefit",
                    "title": "谁从现状中获益",
                    "summary": "判断长期困局时，先找稳定受益方。",
                    "user_value": "避免把结构性损耗误判成个人不够努力。",
                    "evidence": "08:12 不要先问我是不是不够好。",
                    "kind": "core",
                    "anchor": {"type": "video_time", "label": "08:12", "seconds": 492},
                    "source_ids": [payload["source"]["id"]],
                }
            ],
            "edges": [],
            "path": ["benefit"],
        }

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(
        repository=repo,
        cache_manager=cache_manager,
        knowledge_map_generator=fake_map_generator,
    )
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    source = service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    monkeypatch.setattr(collections, "get_collection_service", lambda: service)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    missing = client.get(
        f"/api/collections/{collection['id']}/knowledge-map",
        params={"scope": "source", "source_id": source["id"]},
    )
    assert missing.status_code == 200
    assert missing.json()["data"]["status"] == "not_started"

    generated = client.post(
        f"/api/collections/{collection['id']}/knowledge-map",
        json={"scope": "source", "source_id": source["id"]},
    )
    assert generated.status_code == 200
    assert generated.json()["data"]["map_json"]["central_question"] == "这节课如何判断关系困局？"

    loaded = client.get(
        f"/api/collections/{collection['id']}/knowledge-map",
        params={"scope": "source", "source_id": source["id"]},
    )
    assert loaded.status_code == 200
    assert loaded.json()["data"]["status"] == "success"
    assert loaded.json()["data"]["map_json"]["nodes"][0]["title"] == "谁从现状中获益"


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
        json={
            "title": "如何走出人生困局",
            "creator_name": "屠龙胭脂",
            "collection_type": "video_course",
        },
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


def test_collection_summary_route_runs_generation_in_threadpool(monkeypatch):
    from video_transcript_api.api.routes import collections

    calls = []

    class FakeService:
        def generate_summary(self, collection_id):
            calls.append(("generate_summary", collection_id))
            return {"id": collection_id, "summary_markdown": "# summary"}

    async def fake_run_in_threadpool(func, *args, **kwargs):
        calls.append(("threadpool", func.__name__, args))
        return func(*args, **kwargs)

    monkeypatch.setattr(collections, "get_collection_service", lambda: FakeService())
    monkeypatch.setattr(collections, "run_in_threadpool", fake_run_in_threadpool, raising=False)

    response = asyncio.run(
        collections.generate_collection_summary("collection-1", user_info={"user_id": "u1"})
    )

    assert calls[0] == ("threadpool", "generate_summary", ("collection-1",))
    assert response.data["id"] == "collection-1"


def test_collection_summary_updates_ai_generated_description(tmp_path):
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
        transcript_data="这门课讲如何从人生困局里拆出可控变量。",
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
        summary_generator=lambda collection, sources: (
            "# 如何走出人生困局\n\n"
            "本专题帮助学习者识别困局、拆出可控变量，并形成持续行动的破局方法。\n\n"
            "## 行动清单\n找可控变量"
        ),
    )
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    service.add_existing_source(
        collection_id=collection["id"],
        task_id=task_info["task_id"],
        view_token=task_info["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    generated = service.generate_summary(collection["id"])

    assert generated["description"] == "本专题帮助学习者识别困局、拆出可控变量，并形成持续行动的破局方法。"


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
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")

    monkeypatch.setattr(collections, "cache_manager", cache_manager)
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(collections, "_source_files_dir", lambda: tmp_path / "source-files")

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


def test_collection_upload_appends_after_existing_sources(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    existing = cache_manager.create_task(
        url="local://collection-source/existing/01.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="existing",
    )
    service.add_existing_source(
        collection_id=collection["id"],
        task_id=existing["task_id"],
        view_token=existing["view_token"],
        title="01.mp4",
        source_type="video",
        position=1,
    )

    monkeypatch.setattr(collections, "cache_manager", cache_manager)
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(collections, "_source_files_dir", lambda: tmp_path / "source-files")
    monkeypatch.setattr(collections, "process_local_upload", lambda *args, **kwargs: None)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[
            ("files", ("02.mp4", b"second video bytes", "video/mp4")),
            ("files", ("03.mp4", b"third video bytes", "video/mp4")),
        ],
    )

    assert response.status_code == 202
    detail = service.get_collection_detail(collection["id"])
    assert [(source["title"], source["position"]) for source in detail["sources"]] == [
        ("01.mp4", 1),
        ("02.mp4", 2),
        ("03.mp4", 3),
    ]


def test_collection_upload_inserts_numbered_source_by_filename_prefix(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("创业中的 100 件事", "屠龙胭脂井", "video_course")
    for position, title in [
        (35, "35-黑子与流量游戏.mp4"),
        (36, "37-重新建立新型组织.mp4"),
        (37, "38-三种领域数字.mp4"),
    ]:
        task = cache_manager.create_task(
            url=f"local://collection-source/existing/{title}",
            use_speaker_recognition=False,
            platform="generic",
            media_id=f"existing-{position}",
        )
        service.add_existing_source(
            collection_id=collection["id"],
            task_id=task["task_id"],
            view_token=task["view_token"],
            title=title,
            source_type="video",
            position=position,
        )

    monkeypatch.setattr(collections, "cache_manager", cache_manager)
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(collections, "_source_files_dir", lambda: tmp_path / "source-files")
    monkeypatch.setattr(collections, "process_local_upload", lambda *args, **kwargs: None)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[
            (
                "files",
                (
                    "36-我卖不出去是我的问题，我卖出去了是全公司的问题.mp4",
                    b"missing lesson bytes",
                    "video/mp4",
                ),
            )
        ],
    )

    assert response.status_code == 202
    detail = service.get_collection_detail(collection["id"])
    assert [(source["position"], source["title"]) for source in detail["sources"]] == [
        (35, "35-黑子与流量游戏.mp4"),
        (36, "36-我卖不出去是我的问题，我卖出去了是全公司的问题.mp4"),
        (37, "37-重新建立新型组织.mp4"),
        (38, "38-三种领域数字.mp4"),
    ]


def test_cancel_collection_processing_only_cancels_unfinished_sources(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService
    from video_transcript_api.utils.task_status import TaskStatus

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    task_ids = []
    for index, status in enumerate(
        [TaskStatus.SUCCESS, TaskStatus.PROCESSING, TaskStatus.QUEUED],
        start=1,
    ):
        task = cache_manager.create_task(
            url=f"local://collection-source/media-{index}/{index}.mp4",
            use_speaker_recognition=False,
            platform="generic",
            media_id=f"media-{index}",
        )
        cache_manager.update_task_status(task["task_id"], status)
        task_ids.append(task["task_id"])
        service.add_existing_source(
            collection_id=collection["id"],
            task_id=task["task_id"],
            view_token=task["view_token"],
            title=f"{index}.mp4",
            source_type="video",
            position=index,
        )

    monkeypatch.setattr(collections, "get_collection_service", lambda: service)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(f"/api/collections/{collection['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["data"]["canceled_count"] == 2
    assert cache_manager.get_task_by_id(task_ids[0])["status"] == "success"
    assert cache_manager.get_task_by_id(task_ids[1])["status"] == "canceled"
    assert cache_manager.get_task_by_id(task_ids[2])["status"] == "canceled"


def test_collection_workflow_status_is_stopped_after_cancel(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService
    from video_transcript_api.utils.task_status import TaskStatus

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    collection = service.create_collection("如何走出人生困局", "屠龙胭脂", "video_course")
    task = cache_manager.create_task(
        url="local://collection-source/media-1/1.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="media-1",
    )
    cache_manager.update_task_status(task["task_id"], TaskStatus.PROCESSING)
    service.add_existing_source(
        collection_id=collection["id"],
        task_id=task["task_id"],
        view_token=task["view_token"],
        title="1.mp4",
        source_type="video",
        position=1,
    )

    service.cancel_collection_processing(collection["id"])

    assert service.get_collection_detail(collection["id"])["workflow_status"] == "stopped"
    assert service.list_collections(status="stopped")[0]["id"] == collection["id"]


def test_collections_page_restores_existing_collections():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")

    assert "collection-history-list" in html
    assert "collection-creator" in html
    assert "collection-description" not in html
    assert "collection-description" not in js
    assert "lc-intro-strip" in html
    assert "lc-history-panel" in html
    assert html.index('class="lc-import-card"') < html.index("lc-history-panel")
    assert "history-creator-filter" in html
    assert "metadata-creator" in html
    assert 'data-view="map"' in html
    assert "knowledge-map-svg" in html
    assert "map-generate" in html
    assert "map-stage-focus" in html
    assert "map-toggle-links" in html
    assert "lc-icon-btn" in html
    assert ">全屏查看<" not in html
    assert ">Fit<" not in html
    assert "隐藏连线" in html
    assert "map-zoom-in" in html
    assert "map-fit" in html
    assert "open-source-file" in html
    assert "append-folder" in html
    assert "append-files" in html
    assert "cancel-collection" in html
    assert "map-related-sources" in html
    assert "学习提纲" in html
    assert "源内容" in html
    assert "导出笔记" in html
    assert ">Markdown<" not in html
    assert "markdown-rendered" in html
    assert "markdown-preview-mode" in html
    assert "markdown-source-mode" in html
    assert "source-summary-preview" in html
    assert "source-summary-source" in html
    assert "regenerate-source-summary" in html
    assert "重新生成 AI 解读" in html
    assert "retry-source" in html
    assert "重新解析" in html
    assert "source-error" in html
    assert "当前 source" not in html
    assert "loadCollections" in js
    assert "loadFilterOptions" in js
    assert "selectedHistoryFilters" in js
    assert "selectCollection" in js
    assert "loadCollections().catch((error) => {\n                    showToast(error.message || '历史专题筛选失败');" in js
    assert "loadCollections({ selectLatest: false }).catch((error) => {\n                    showToast(error.message || '历史专题筛选失败');" not in js
    assert "renderKnowledgeMap" in js
    assert "loadKnowledgeMap" in js
    assert "generateKnowledgeMap" in js
    assert "/knowledge-map" in js
    assert "renderWrappedSvgText" in js
    assert "makeMapNodeDraggable" in js
    assert "openSourceFile" in js
    assert "appendFilesToCurrentCollection" in js
    assert "cancelCurrentCollection" in js
    assert "/cancel" in js
    assert "mapLinksVisible" in js
    assert "openRelatedSource" in js
    assert "openSourceAccess" in js
    assert "reveal_url" in js
    assert "markdownToHTML" in js
    assert "renderMarkdownExport" in js
    assert "sourceSummaryDisplayMode" in js
    assert "regenerateSourceSummary" in js
    assert "/api/recalibrate" in js
    assert "regenerate_summary: true" in js
    assert "retrySelectedSource" in js
    assert "/retry" in js
    assert "renderSourceError" in js


def test_collection_repository_filters_and_options(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    repo.create_collection(
        title="如何走出人生困局",
        creator_name="屠龙胭脂",
        collection_type="video_course",
        description="提炼破局判断标准",
        import_method="local_folder",
    )
    repo.create_collection(
        title="富贵的一人 IP 课程",
        creator_name="富贵",
        collection_type="document_topic",
        description="沉淀一人公司 SOP",
        import_method="local_files",
    )

    filtered = repo.list_collections(creator_name="屠龙胭脂", title="如何走出人生困局")
    assert len(filtered) == 1
    assert filtered[0]["creator_name"] == "屠龙胭脂"
    assert filtered[0]["description"] == "提炼破局判断标准"
    assert filtered[0]["import_method"] == "local_folder"

    options = repo.get_filter_options()
    assert "屠龙胭脂" in options["creator_names"]
    assert "富贵的一人 IP 课程" in options["titles"]


def test_collection_repository_date_filter_uses_source_upload_date(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository

    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    target = repo.create_collection(
        title="如何走出人生困局",
        creator_name="屠龙胭脂",
        collection_type="video_course",
    )
    repo.add_source(
        collection_id=target["id"],
        task_id="task-1",
        view_token="view-1",
        title="1.mp4",
        source_type="video",
        position=1,
    )
    other = repo.create_collection(
        title="其他专题",
        creator_name="屠龙胭脂",
        collection_type="video_course",
    )
    repo.add_source(
        collection_id=other["id"],
        task_id="task-2",
        view_token="view-2",
        title="2.mp4",
        source_type="video",
        position=1,
    )
    with repo._get_cursor() as cursor:
        cursor.execute(
            "UPDATE learning_collection_sources SET created_at = ? WHERE collection_id = ?",
            ("2026-06-11 10:26:00", target["id"]),
        )
        cursor.execute(
            "UPDATE learning_collection_sources SET created_at = ? WHERE collection_id = ?",
            ("2026-06-10 10:26:00", other["id"]),
        )

    filtered = repo.list_collections(date_from="2026-06-11", date_to="2026-06-11")

    assert [item["id"] for item in filtered] == [target["id"]]


def test_collection_service_requires_creator_name(tmp_path):
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)

    try:
        service.create_collection(
            title="如何走出人生困局",
            creator_name="",
            collection_type="video_course",
        )
    except ValueError as exc:
        assert "creator_name is required" in str(exc)
    else:
        raise AssertionError("Expected creator_name to be required")


def test_collection_api_filters_and_options(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import collections
    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.collections.repository import LearningCollectionRepository
    from video_transcript_api.collections.service import LearningCollectionService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache_manager)
    service.create_collection(
        title="如何走出人生困局",
        creator_name="屠龙胭脂",
        collection_type="video_course",
        description="提炼破局判断标准",
    )
    service.create_collection(
        title="富贵的一人 IP 课程",
        creator_name="富贵",
        collection_type="document_topic",
    )

    monkeypatch.setattr(collections, "get_collection_service", lambda: service)

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    listed = client.get(
        "/api/collections",
        params={"creator_name": "屠龙胭脂", "title": "如何走出人生困局"},
    )
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert len(data["collections"]) == 1
    assert data["collections"][0]["creator_name"] == "屠龙胭脂"
    assert data["collections"][0]["workflow_status"] == "draft"

    options = client.get("/api/collections/filter-options")
    assert options.status_code == 200
    assert "屠龙胭脂" in options.json()["data"]["creator_names"]
