from video_transcript_api.cache.cache_manager import CacheManager


def _create_successful_local_task(
    cache_manager: CacheManager,
    url: str = "local://study-source/local_abc/lesson.mp4",
    title: str = "lesson.mp4",
):
    task = cache_manager.create_task(
        url=url,
        use_speaker_recognition=False,
        platform="generic",
        media_id="local_abc",
    )
    cache_manager.save_cache(
        platform="generic",
        url=url,
        media_id="local_abc",
        use_speaker_recognition=False,
        transcript_data="第一段内容。\n第二段内容。",
        transcript_type="capswriter",
        title=title,
        author="本地上传",
        description="",
    )
    cache_manager.save_llm_result(
        platform="generic",
        media_id="local_abc",
        use_speaker_recognition=False,
        llm_type="summary",
        content="## 总结\n这一节讲核心概念。",
    )
    cache_manager.update_task_status(
        task["task_id"],
        "success",
        platform="generic",
        media_id="local_abc",
        title=title,
        author="本地上传",
    )
    return task


def test_study_service_builds_ready_session_with_source_file(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService
    from video_transcript_api.study.source_files import build_study_source_path

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = _create_successful_local_task(cache_manager)
    source = build_study_source_path(tmp_path / "sources", "local_abc", "lesson.mp4")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    repo.create_note(task["view_token"], 12, "重点复看")
    service = StudyService(
        cache_manager=cache_manager,
        repository=repo,
        source_root=tmp_path / "sources",
    )

    session = service.get_session(task["view_token"])

    assert session["state"] == "ready"
    assert session["metadata"]["title"] == "lesson.mp4"
    assert session["playback"]["source_available"] is True
    assert session["playback"]["source_url"].endswith("/api/study/" + task["view_token"] + "/source-file")
    assert session["source"] == {
        "kind": "video",
        "filename": "lesson.mp4",
        "media_type": "video/mp4",
        "original_url": "/api/study/" + task["view_token"] + "/source-file",
    }
    assert "核心概念" in session["ai"]["overview"]
    assert session["transcript"]["lines"][0]["text"] == "第一段内容。"
    assert session["notes"][0]["body"] == "重点复看"


def test_study_service_exposes_document_source_metadata(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService
    from video_transcript_api.study.source_files import build_study_source_path

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    url = "local://study-source/local_abc/guide.pdf"
    task = _create_successful_local_task(cache_manager, url=url, title="guide.pdf")
    source = build_study_source_path(tmp_path / "sources", "local_abc", "guide.pdf")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")
    service = StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(db_path=str(tmp_path / "study.db")),
        source_root=tmp_path / "sources",
    )

    session = service.get_session(task["view_token"])

    assert session["source"]["kind"] == "document"
    assert session["source"]["filename"] == "guide.pdf"
    assert session["source"]["media_type"] == "application/pdf"
    assert session["source"]["original_url"].endswith("/source-file")


def test_study_service_exposes_fast_document_analysis_from_terminal_progress(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    url = "local://study-source/local_fast/guide.pdf"
    task = cache_manager.create_task(
        url=url,
        platform="generic",
        media_id="local_fast",
    )
    cache_manager.save_cache(
        platform="generic",
        url=url,
        media_id="local_fast",
        use_speaker_recognition=False,
        transcript_data="原始正文" * 100,
        transcript_type="capswriter",
        title="guide.pdf",
        author="本地上传",
        description="",
    )
    quality = {"mode": "fast", "reasons": [], "metrics": {"printable_ratio": 1.0}}
    cache_manager.update_task_status(
        task["task_id"],
        "success",
        platform="generic",
        media_id="local_fast",
        terminal_evidence={
            "analysis_mode": "document_fast",
            "visual_ready": True,
            "quality": quality,
        },
    )
    service = StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(db_path=str(tmp_path / "study.db")),
        source_root=tmp_path / "sources",
    )

    session = service.get_session(task["view_token"])

    assert session["analysis"] == {
        "mode": "document_fast",
        "visual_ready": True,
        "quality": quality,
    }
    assert session["ai"]["overview"] == ""
    assert session["ai"]["summary_missing"] is True


def test_study_service_reports_source_missing_without_failing(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = _create_successful_local_task(cache_manager)
    service = StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(db_path=str(tmp_path / "study.db")),
        source_root=tmp_path / "sources",
    )

    session = service.get_session(task["view_token"])

    assert session["state"] == "source_missing"
    assert session["playback"]["source_available"] is False
    assert session["transcript"]["lines"]


def test_study_service_maps_non_terminal_states_for_ui(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = cache_manager.create_task(
        url="local://study-source/local_processing/lesson.mp4",
        use_speaker_recognition=False,
        platform="generic",
        media_id="local_processing",
    )
    cache_manager.update_task_progress(
        task["task_id"],
        stage="transcribing",
        stage_label="正在转录本地文件",
        fraction=0.4,
        basis="local_upload",
        confidence="high",
    )
    service = StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(db_path=str(tmp_path / "study.db")),
        source_root=tmp_path / "sources",
    )

    processing = service.get_session(task["view_token"])
    assert processing["state"] == "transcribing"
    assert processing["progress"]["stage_label"] == "正在转录本地文件"

    cache_manager.update_task_status(
        task["task_id"],
        "calibrating",
        platform="generic",
        media_id="local_processing",
    )
    generating_ai = service.get_session(task["view_token"])
    assert generating_ai["state"] == "generating_ai"


def test_study_service_returns_none_for_unknown_token(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService

    service = StudyService(
        cache_manager=CacheManager(cache_dir=str(tmp_path / "cache")),
        repository=StudyRepository(db_path=str(tmp_path / "study.db")),
        source_root=tmp_path / "sources",
    )

    assert service.get_session("missing") is None


def test_study_service_exports_markdown(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = _create_successful_local_task(cache_manager)
    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    repo.create_note(task["view_token"], 12, "重点复看")
    service = StudyService(
        cache_manager=cache_manager,
        repository=repo,
        source_root=tmp_path / "sources",
    )

    markdown = service.export_markdown(task["view_token"])

    assert "# lesson.mp4" in markdown
    assert "## AI 看" in markdown
    assert "核心概念" in markdown
    assert "## 文稿" in markdown
    assert "第一段内容" in markdown
    assert "## 我的笔记" in markdown
    assert "重点复看" in markdown


def test_study_service_ai_chat_uses_deepseek_v4_and_video_context(tmp_path):
    from video_transcript_api.study.repository import StudyRepository
    from video_transcript_api.study.service import StudyService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = _create_successful_local_task(cache_manager)
    calls = {}

    def fake_answerer(**kwargs):
        calls.update(kwargs)
        return "稳定系统指的是在压力下更不容易被激发的系统。"

    service = StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(db_path=str(tmp_path / "study.db")),
        source_root=tmp_path / "sources",
        llm_config={},
        llm_answerer=fake_answerer,
    )

    result = service.ask_ai(
        task["view_token"],
        "稳定系统是什么意思？",
        history=[{"role": "user", "content": "我没理解前面的比喻"}],
    )

    assert result["model"] == "deepseek-v4-pro"
    assert result["reasoning_effort"] == "high"
    assert result["answer"].startswith("稳定系统")
    assert calls["model"] == "deepseek-v4-pro"
    assert calls["reasoning_effort"] == "high"
    assert calls["task_type"] == "study_chat"
    assert "稳定系统是什么意思？" in calls["prompt"]
    assert "我没理解前面的比喻" in calls["prompt"]
    assert "这一节讲核心概念" in calls["prompt"]
    assert "第一段内容" in calls["prompt"]
    assert "不要输出 Markdown 分隔线" in calls["prompt"]
