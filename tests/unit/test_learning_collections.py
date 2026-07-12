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


def test_collection_summary_prompt_builds_full_series_interpretation():
    from video_transcript_api.collections.service import build_collection_summary_prompt

    prompt = build_collection_summary_prompt(
        {
            "title": "如何走出人生困局",
            "collection_type": "video_course",
            "goal": "先建立全局视角，再选择性深度学习",
        },
        [
            {
                "title": "01 开篇.mp4",
                "source_type": "video",
                "position": 1,
                "single_summary": "第一节说明困局要先拆出可控变量。",
                "transcript": "原文A" * 400,
            },
            {
                "title": "02 行动.mp4",
                "source_type": "video",
                "position": 2,
                "single_summary": "",
                "transcript": "第二节用行动闭环把判断变成实践。",
            },
        ],
    )

    assert "全系列解读" in prompt
    assert "课前导览" in prompt
    assert "课后复习" in prompt
    assert "这个系列解决什么问题" in prompt
    assert "为什么值得学" in prompt
    assert "全系列主线" in prompt
    assert "章节地图" in prompt
    assert "核心框架" in prompt
    assert "复习索引" in prompt
    assert "第一节说明困局要先拆出可控变量。" in prompt
    assert "原文补充" in prompt
    assert "不要使用 ```" in prompt
    assert len(prompt) < 18000


def test_collection_summary_prompt_keeps_all_sources_in_long_series():
    from video_transcript_api.collections.service import build_collection_summary_prompt

    sources = [
        {
            "title": f"{index:02d} 创业中的 100 件事.mp4",
            "source_type": "video",
            "position": index,
            "single_summary": f"第 {index} 节讲创业关键问题。" * 80,
            "transcript": f"第 {index} 节原文补充。" * 120,
        }
        for index in range(1, 76)
    ]

    prompt = build_collection_summary_prompt(
        {
            "title": "创业中的 100 件事",
            "collection_type": "video_course",
            "goal": "先建立创业知识全局视角，再选择性复习具体章节",
        },
        sources,
    )

    assert "## Source 1: 01 创业中的 100 件事.mp4" in prompt
    assert "## Source 75: 75 创业中的 100 件事.mp4" in prompt
    assert "位置: 75" in prompt
    assert len(prompt) < 65000


def test_collection_summary_llm_uses_full_source_content_for_small_collection(monkeypatch):
    from video_transcript_api.collections import service as collection_service
    from video_transcript_api.collections.service import LearningCollectionService

    calls = []

    def fake_call_llm_api(**kwargs):
        calls.append(kwargs)
        return "# 全系列解读\n\n## 章节地图\n第 1 节：完整覆盖。"

    monkeypatch.setattr(collection_service, "call_llm_api", fake_call_llm_api)
    service = LearningCollectionService(
        repository=None,
        cache_manager=None,
        llm_config={"model": "fake", "collection_direct_char_limit": 10000},
    )

    markdown = service._generate_summary_with_llm(
        {"title": "小合集", "collection_type": "video_course"},
        [
            {
                "title": "01 小课.mp4",
                "source_type": "video",
                "position": 1,
                "single_summary": "短摘要",
                "transcript": "完整源内容开头。FULL_SOURCE_TAIL",
            }
        ],
    )

    assert markdown.startswith("# 全系列解读")
    assert [call["task_type"] for call in calls] == ["collection_summary"]
    assert "FULL_SOURCE_TAIL" in calls[0]["prompt"]


def test_collection_summary_defaults_to_direct_until_model_context_is_exceeded(monkeypatch):
    from video_transcript_api.collections import service as collection_service
    from video_transcript_api.collections.service import LearningCollectionService

    calls = []

    def fake_call_llm_api(**kwargs):
        calls.append(kwargs)
        positions = "、".join(str(index) for index in range(1, 76))
        return f"# 全系列解读\n\n## 章节地图\n第 {positions} 节：默认直接处理。"

    monkeypatch.setattr(collection_service, "call_llm_api", fake_call_llm_api)
    service = LearningCollectionService(
        repository=None,
        cache_manager=None,
        llm_config={"collection_summary_model": "deepseek-v4-pro"},
    )
    sources = [
        {
            "title": f"{index:02d} 创业课.mp4",
            "source_type": "video",
            "position": index,
            "single_summary": f"第 {index} 节摘要",
            "transcript": f"FULL_CONTEXT_SOURCE_{index} " * 120,
        }
        for index in range(1, 76)
    ]

    service._generate_summary_with_llm(
        {"title": "创业中的 100 件事", "collection_type": "video_course"},
        sources,
    )

    assert [call["task_type"] for call in calls] == ["collection_summary"]
    assert calls[0]["model"] == "deepseek-v4-pro"
    assert "FULL_CONTEXT_SOURCE_75" in calls[0]["prompt"]


def test_collection_summary_llm_layers_large_collection_with_full_module_sources(monkeypatch):
    from video_transcript_api.collections import service as collection_service
    from video_transcript_api.collections.service import LearningCollectionService

    class FakeStructuredResult:
        def __init__(self, data):
            self.success = True
            self.data = data
            self.error = None

    calls = []

    def fake_call_llm_api(**kwargs):
        calls.append(kwargs)
        task_type = kwargs["task_type"]
        if task_type == "collection_module_plan":
            return FakeStructuredResult(
                {
                    "mainline": "先校准认知，再进入方法。",
                    "modules": [
                        {
                            "title": "认知校准",
                            "role": "建立创业底层判断",
                            "rationale": "前 3 节都在校准创业认知。",
                            "source_numbers": [1, 2, 3],
                        },
                        {
                            "title": "方法展开",
                            "role": "进入具体行动方法",
                            "rationale": "后 3 节开始讲验证和行动。",
                            "source_numbers": [4, 5, 6],
                        },
                    ],
                }
            )
        if task_type == "collection_module_summary":
            return f"模块解读：{kwargs['prompt'].split('模块名称：', 1)[1].splitlines()[0]}"
        if task_type == "collection_summary":
            return "# 全系列解读\n\n## 章节地图\n第 1、2、3、4、5、6 节：全部纳入模块。"
        raise AssertionError(f"Unexpected task type: {task_type}")

    monkeypatch.setattr(collection_service, "call_llm_api", fake_call_llm_api)
    service = LearningCollectionService(
        repository=None,
        cache_manager=None,
        llm_config={
            "model": "fake",
            "collection_direct_char_limit": 10,
            "collection_module_source_char_limit": 10000,
        },
    )
    sources = [
        {
            "title": f"{index:02d} 创业课.mp4",
            "source_type": "video",
            "position": index,
            "single_summary": f"第 {index} 节摘要",
            "transcript": f"FULL_TRANSCRIPT_{index} " * 20,
        }
        for index in range(1, 7)
    ]

    markdown = service._generate_summary_with_llm(
        {"title": "创业中的 100 件事", "collection_type": "video_course"},
        sources,
    )

    assert "第 1、2、3、4、5、6 节" in markdown
    assert [call["task_type"] for call in calls] == [
        "collection_module_plan",
        "collection_module_summary",
        "collection_module_summary",
        "collection_summary",
    ]
    module_prompts = [
        call["prompt"] for call in calls if call["task_type"] == "collection_module_summary"
    ]
    assert "FULL_TRANSCRIPT_1" in module_prompts[0]
    assert "FULL_TRANSCRIPT_6" in module_prompts[1]


def test_collection_summary_llm_repairs_missing_source_coverage(monkeypatch):
    from video_transcript_api.collections import service as collection_service
    from video_transcript_api.collections.service import LearningCollectionService

    class FakeStructuredResult:
        success = True
        error = None
        data = {
            "mainline": "从认知到行动。",
            "modules": [
                {
                    "title": "完整模块",
                    "role": "覆盖全部章节",
                    "rationale": "三节共同构成一个小闭环。",
                    "source_numbers": [1, 2, 3],
                }
            ],
        }

    calls = []

    def fake_call_llm_api(**kwargs):
        calls.append(kwargs)
        task_type = kwargs["task_type"]
        if task_type == "collection_module_plan":
            return FakeStructuredResult()
        if task_type == "collection_module_summary":
            return "模块解读：覆盖 1-3 节。"
        if task_type == "collection_summary":
            return "# 全系列解读\n\n## 章节地图\n第 1 节：只写了开头。"
        if task_type == "collection_summary_repair":
            return "# 全系列解读\n\n## 章节地图\n第 1、2、3 节：修正后全部覆盖。"
        raise AssertionError(f"Unexpected task type: {task_type}")

    monkeypatch.setattr(collection_service, "call_llm_api", fake_call_llm_api)
    service = LearningCollectionService(
        repository=None,
        cache_manager=None,
        llm_config={"model": "fake", "collection_direct_char_limit": 10},
    )
    sources = [
        {
            "title": f"{index:02d} 创业课.mp4",
            "source_type": "video",
            "position": index,
            "single_summary": f"第 {index} 节摘要",
            "transcript": f"FULL_TRANSCRIPT_{index} " * 20,
        }
        for index in range(1, 4)
    ]

    markdown = service._generate_summary_with_llm(
        {"title": "创业中的 100 件事", "collection_type": "video_course"},
        sources,
    )

    assert "修正后全部覆盖" in markdown
    assert calls[-1]["task_type"] == "collection_summary_repair"
    assert "第 2 节" in calls[-1]["prompt"]
    assert "FULL_TRANSCRIPT_3" in calls[-1]["prompt"]


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


def test_collections_import_uses_one_primary_choice_and_collapsed_history():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")

    intro = html[html.index('class="lc-intro-strip"') : html.index('class="lc-import-card"')]
    import_card = html[html.index('class="lc-import-card"') : html.index('class="lc-history')]
    import_files = js[js.index("async function importFiles(") : js.index("async function appendFilesToCurrentCollection(")]

    assert "lc-eyebrow" not in intro
    assert "lc-points" not in intro
    assert '<div class="lc-drop" id="drop-action"' in import_card
    assert "dropAction.addEventListener('click'" not in js
    assert 'class="lc-btn primary" id="pick-files"' in import_card
    assert import_card.count("lc-btn primary") == 1
    busy_guard = import_files[import_files.index("if (busy)") : import_files.index("const files = normalizeFiles")]
    assert "return;" in busy_guard
    assert '<details class="lc-history lc-history-panel"' in html
    assert '<summary class="lc-history-summary">' in html
    assert '<details class="lc-history lc-history-panel" open' not in html


def test_collections_page_restores_existing_collections():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")
    css = (project_root / "src/web/static/css/collections.css").read_text(encoding="utf-8")

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
    assert "全系列解读" in html
    assert "grid-template-rows: auto minmax(0, 1fr)" in css
    assert "top: 16px" in css
    assert "max-height: none" in css
    assert "学习提纲" not in html
    assert "学习提纲" not in js
    assert "collection-summary-text" in html
    assert "collection-summary-visual" in html
    assert "collection-summary-text-panel" in html
    assert "collection-summary-visual-panel" in html
    assert "collection-summary-article" in html
    assert "collection-summary-visual-root" in html
    assert "阅读全文" in html
    assert "沉浸阅读全文" not in html
    assert "collectionSummaryArticle" in js
    assert "collectionSummaryVisualRoot" in js
    assert "renderCollectionSummaryArticle" in js
    assert "focusCollectionSummaryArticle" in js
    assert "renderInlineSummaryVisual" in js
    assert "setCollectionSummaryMode" in js
    assert "summaryToc" in js
    assert "summaryStructured" in js
    assert "summary-reader" in html
    assert "summary-toc" in html
    assert "summary-structured" in html
    assert "summary-dialog" in html
    assert 'data-summary-card="problem"' not in html
    assert "renderSummaryReader" in js
    assert "openSummaryDialog" in js
    assert "buildSummarySections" in js
    assert "renderSummaryToc" in js
    assert "renderStructuredSummaryBlocks" in js
    assert "splitInlineNumberedItems" in js
    assert "data-summary-anchor" in js
    assert "aria-disabled" in js
    assert ".lc-summary-reader-head" in css
    assert ".lc-summary-reader-actions" in css
    assert ".lc-summary-inline-article" in css
    assert ".lc-summary-inline-visual" in css
    assert ".lc-summary-dialog" in css
    assert ".lc-summary-reader" in css
    assert ".lc-summary-toc" in css
    assert ".lc-summary-article" in css
    assert ".lc-inline-numbered" in css
    assert "grid-template-columns: minmax(0, 1fr) 220px" in css
    assert "normalizeMarkdownForPreview" in js
    assert "summarizeMarkdownSection" in js
    assert "startSummaryProgress" in js
    assert "summaryProgressByCollection" in js
    assert "function isSummaryGenerating(collectionId)" in js
    assert "startSummaryProgress(collectionId)" in js
    assert "stopSummaryProgress(collectionId" in js
    assert "currentCollection.id === collectionId" in js
    generate_summary_body = js[
        js.index("async function generateSummary()") : js.index("async function exportMarkdown()")
    ]
    assert "setBusy(true);" not in generate_summary_body
    assert "lc-btn-progress" in html
    assert "summary-progress-text" in html
    assert "文字版" in html
    assert "图解版" in html
    assert "内容总结" in html
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


def test_collections_page_exposes_immersive_text_visual_reader():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")
    css = (project_root / "src/web/static/css/collections.css").read_text(encoding="utf-8")

    assert '/static/css/visual-learning.css?v=__ASSET_VERSION__' in html
    assert '/static/js/visual-learning.js?v=__ASSET_VERSION__' in html
    assert 'data-view="visual"' not in html
    assert 'data-view="summary"' in html
    assert "图解版" in html
    for element_id in (
        "visual-view",
        "collection-visual-root",
        "collection-visual-overview-status",
        "collection-visual-overview-retry",
        "collection-visual-full-note-status",
        "collection-visual-full-note-retry",
        "collection-visual-theme",
        "collection-visual-export",
        "collection-visual-print",
        "collection-visual-open",
        "collection-summary-text",
        "collection-summary-visual",
        "collection-summary-text-panel",
        "collection-summary-visual-panel",
        "collection-summary-article",
        "collection-summary-reader-open",
        "collection-immersive-reader",
    ):
        assert f'id="{element_id}"' in html

    assert "function activateCollectionVisuals()" in js
    assert "currentView !== 'visual'" in js
    assert "document_type=${encodeURIComponent(documentType)}" in js
    assert "document_type: documentType" in js
    assert "'overview'" in js
    assert "'full_note'" in js
    assert "window.VisualLearning.renderImmersiveReader" in js
    assert "window.VisualLearning.createReaderState" in js
    assert "function openCollectionReader(" in js
    assert "function openCollectionSummaryReader(" in js
    assert "function closeCollectionReader(" in js
    summary_tab_branch = js[
        js.index("els.tabs.forEach((tab) => {") : js.index("if (els.collectionVisualOverviewRetry)")
    ]
    assert "currentView === 'summary'" in summary_tab_branch
    assert "openCollectionReader('text', tab)" not in summary_tab_branch
    assert "openCollectionReader('visual', tab)" not in summary_tab_branch
    assert "requestedView === 'visual'" in summary_tab_branch
    assert "setCollectionSummaryMode('text', false)" in summary_tab_branch
    assert "setCollectionSummaryMode('visual', true)" in summary_tab_branch
    assert "ensureCollectionVisualLayer('overview', false)" in js
    assert "function renderInlineSummaryVisual()" in js
    assert "function setCollectionSummaryMode(" in js
    assert "function renderCollectionSummaryArticle(" in js
    assert "function focusCollectionSummaryArticle(" in js
    assert "renderCollectionSummaryArticle(markdown, waitingText)" in js
    assert "visualScope: 'global'" in js
    assert "onExportText: exportMarkdown" in js
    assert "fullNote: null" in js
    assert "合集全局图解" in html
    assert "子内容图解请进入对应内容页独立查看" in js
    assert "readerGeneration" in js
    assert ".accepts(" in js
    assert "window.VisualLearning.activeDiagram" in js
    assert "function retryCollectionVisual(documentType)" in js
    assert "function parseCollectionVisualRef(" in js
    assert "function visualSummarySections()" in js
    assert "function collectionReaderTextSections(" in js
    assert "focusCollectionSummaryArticle('')" in js
    assert "openCollectionReader('text', els.collectionSummaryReaderOpen)" not in js
    assert "openCollectionReader('visual', els.collectionVisualOpen)" not in js
    assert "openSummaryDialog(`card:${card.dataset.summaryCard || 'problem'}`, card)" not in js
    assert 'data-summary-section="${escapeHTML(section.id)}"' in js
    visual_navigation = js[
        js.index("async function navigateCollectionVisualRef(") : js.index("function exportCollectionVisualSvg(")
    ]
    assert ".find((section) => section.id === target.sectionId)" in visual_navigation
    assert "focusCollectionSummaryArticle(readerSection ? readerSection.id : '')" in visual_navigation
    assert "openCollectionReader('text'" not in visual_navigation
    assert "openSummaryDialog(" not in visual_navigation
    assert ".find((section) => section.title.trim()" not in visual_navigation
    assert "collection:${collectionId}:source:" in js
    assert "collection:${collectionId}:summary:section:" in js
    assert "ensureSourceDetail(sourceId)" in js
    assert "resetCollectionVisualState" in js
    assert "window.clearInterval(collectionVisual.pollTimers.overview)" in js
    assert "window.clearInterval(collectionVisual.pollTimers.full_note)" in js
    assert "@media print" in css
    assert ".lc-visual-view" in css
    assert "overflow: visible" in css
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
