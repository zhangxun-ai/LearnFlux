import os
import time

from src.video_transcript_api.cache.cache_manager import CacheManager
from src.video_transcript_api.utils.source_file_cleanup import cleanup_old_source_files


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
