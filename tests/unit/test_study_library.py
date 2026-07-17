from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.study.source_files import build_study_source_path
from video_transcript_api.utils.logging.audit_logger import AuditLogger


def _create_task(cache_manager, *, media_id, title, status="success"):
    url = f"local://study-source/{media_id}/{title}"
    task = cache_manager.create_task(
        url=url,
        use_speaker_recognition=False,
        platform="generic",
        media_id=media_id,
    )
    cache_manager.update_task_status(
        task["task_id"],
        status,
        platform="generic",
        media_id=media_id,
        title=title,
        author="Local upload",
    )
    return task, url


def test_single_library_returns_only_owned_playable_media(tmp_path):
    from video_transcript_api.study.library import StudyLibraryService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    audit_logger = AuditLogger(db_path=str(tmp_path / "audit.db"))
    source_root = tmp_path / "sources"

    owned, owned_url = _create_task(
        cache_manager,
        media_id="owned_media",
        title="Product lesson.mp3",
    )
    missing, missing_url = _create_task(
        cache_manager,
        media_id="missing_media",
        title="Missing lesson.mp4",
    )
    other, other_url = _create_task(
        cache_manager,
        media_id="other_media",
        title="Other lesson.mp4",
    )
    source = build_study_source_path(source_root, "owned_media", "Product lesson.mp3")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"audio")

    for task, url, user_id, api_key in (
        (owned, owned_url, "user-a", "sk-user-a-123456"),
        (missing, missing_url, "user-a", "sk-user-a-123456"),
        (other, other_url, "user-b", "sk-user-b-123456"),
    ):
        audit_logger.log_api_call(
            api_key=api_key,
            user_id=user_id,
            endpoint="/api/study/upload",
            video_url=url,
            status_code=202,
            task_id=task["task_id"],
        )

    service = StudyLibraryService(
        cache_manager=cache_manager,
        audit_logger=audit_logger,
        source_root=source_root,
    )

    result = service.list_single(user_id="user-a", q="product", limit=20, offset=0)

    assert result["total"] == 1
    assert [item["view_token"] for item in result["items"]] == [owned["view_token"]]
    assert result["items"][0]["source_kind"] == "audio"
    assert result["items"][0]["media_type"] == "audio/mpeg"
    assert missing["view_token"] not in {item["view_token"] for item in result["items"]}
    assert other["view_token"] not in {item["view_token"] for item in result["items"]}


def test_single_library_deduplicates_audit_rows_and_paginates(tmp_path):
    from video_transcript_api.study.library import StudyLibraryService

    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    audit_logger = AuditLogger(db_path=str(tmp_path / "audit.db"))
    source_root = tmp_path / "sources"
    task, url = _create_task(cache_manager, media_id="lesson", title="Lesson.mp4")
    source = build_study_source_path(source_root, "lesson", "Lesson.mp4")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"video")
    for endpoint in ("/api/study/upload", f"/api/task/{task['task_id']}"):
        audit_logger.log_api_call(
            api_key="sk-user-a-123456",
            user_id="user-a",
            endpoint=endpoint,
            video_url=url,
            task_id=task["task_id"],
            status_code=200,
        )

    service = StudyLibraryService(cache_manager, audit_logger, source_root)

    assert service.list_single("user-a", limit=1, offset=0)["total"] == 1
    assert service.list_single("user-a", limit=1, offset=1)["items"] == []
