import os
import time

from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.utils.source_file_cleanup import (
    cleanup_old_source_files,
    is_ephemeral_managed_media_path,
    purge_managed_collection_media,
    should_preserve_local_media_path,
)


def _touch_old(path, days_old):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("source", encoding="utf-8")
    old_ts = time.time() - days_old * 24 * 60 * 60
    os.utime(path, (old_ts, old_ts))


def test_cleanup_removes_only_unreferenced_expired_source_files(tmp_path):
    source_root = tmp_path / "source_files"
    collection_dir = source_root / "collection_uploads"
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    try:
        referenced_collection = collection_dir / "local_keep.mp4"
        referenced_study = source_root / "study_uploads" / "local_study.pdf"
        orphan_collection = collection_dir / "local_orphan.mp4"
        orphan_online = source_root / "online_downloads" / "old-note.md"
        fresh_orphan = collection_dir / "local_fresh.mp4"
        for path in (
            referenced_collection,
            referenced_study,
            orphan_collection,
            orphan_online,
        ):
            _touch_old(path, 40)
        _touch_old(fresh_orphan, 1)

        manager.create_task(
            url="local://collection-source/local_keep/lesson.mp4",
            platform="generic",
            media_id="local_keep",
        )
        manager.create_task(
            url="local://study-source/local_study/guide.pdf",
            platform="generic",
            media_id="local_study",
        )

        result = cleanup_old_source_files(
            cache_manager=manager,
            source_root=source_root,
            collection_source_dir=collection_dir,
            max_age_days=30,
        )

        assert result.deleted_count == 2
        assert result.skipped_referenced_count == 2
        assert referenced_collection.exists()
        assert referenced_study.exists()
        assert fresh_orphan.exists()
        assert not orphan_collection.exists()
        assert not orphan_online.exists()
    finally:
        manager.close()


def test_cleanup_never_scans_reading_managed_sources(tmp_path):
    source_root = tmp_path / "source_files"
    reading_source = source_root / "reading" / "u_safe" / "document.pdf"
    _touch_old(reading_source, 365)
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    try:
        result = cleanup_old_source_files(
            cache_manager=manager,
            source_root=source_root,
            max_age_days=30,
        )

        assert result.scanned_count == 0
        assert result.deleted_count == 0
        assert reading_source.exists()
    finally:
        manager.close()


def test_should_preserve_source_media_for_ux_but_not_audio_intermediates(tmp_path):
    collection_dir = tmp_path / "source_files" / "collection_uploads"
    temp_dir = tmp_path / "temp"
    user_video = tmp_path / "Course" / "01.mp4"
    managed = collection_dir / "local_abc.mp4"
    audio = temp_dir / "collection_audio" / "local_xyz.audio.m4a"
    for path in (user_video, managed, audio):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    # UX first: both path-import originals and durable managed copies are kept
    # when preserve_source_file is requested (open source / re-parse).
    assert should_preserve_local_media_path(
        user_video,
        preserve_source_file=True,
        temp_dir=temp_dir,
        collection_source_dir=collection_dir,
    )
    assert should_preserve_local_media_path(
        managed,
        preserve_source_file=True,
        temp_dir=temp_dir,
        collection_source_dir=collection_dir,
    )
    assert not should_preserve_local_media_path(
        audio,
        preserve_source_file=True,
        temp_dir=temp_dir,
        collection_source_dir=collection_dir,
    )
    assert is_ephemeral_managed_media_path(
        managed,
        temp_dir=temp_dir,
        collection_source_dir=collection_dir,
    )


def test_purge_managed_collection_media_deletes_copies_and_clears_refs(tmp_path):
    collection_dir = tmp_path / "source_files" / "collection_uploads"
    temp_dir = tmp_path / "temp"
    managed = collection_dir / "local_dup.mp4"
    staging = temp_dir / "collection_staging" / "local_stage.mp4"
    user_video = tmp_path / "library" / "keep.mp4"
    for path in (managed, staging, user_video):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video-bytes")

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    try:
        managed_task = manager.create_task(
            url="local://collection-source/local_dup/lesson.mp4",
            platform="generic",
            media_id="local_dup",
            source_file_path=str(managed),
        )
        user_task = manager.create_task(
            url="local://collection-source/local_user/keep.mp4",
            platform="generic",
            media_id="local_user",
            source_file_path=str(user_video),
        )

        result = purge_managed_collection_media(
            cache_manager=manager,
            collection_source_dir=collection_dir,
            temp_dir=temp_dir,
        )

        assert result.deleted_count >= 2
        assert not managed.exists()
        assert not staging.exists()
        assert user_video.exists()
        assert manager.get_task_by_id(managed_task["task_id"]).get("source_file_path") in (
            None,
            "",
        )
        assert manager.get_task_by_id(user_task["task_id"]).get("source_file_path") == str(
            user_video
        )
    finally:
        manager.close()
