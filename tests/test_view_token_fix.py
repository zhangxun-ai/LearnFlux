"""Offline regression for selecting a successful task by its generated view token."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_transcript_api.cache import CacheManager


def test_view_token_query(tmp_path):
    """Use disposable cache data and never read or print a real access token."""
    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    try:
        url = "https://example.com/test-video"
        failed = cache_manager.create_task(url=url, platform="youtube", media_id="test-video")
        cache_manager.update_task_status(failed["task_id"], "failed", error_message="Test failure")
        cache_manager.save_cache(
            platform="youtube", url=url, media_id="test-video",
            use_speaker_recognition=False, transcript_data="Public test transcript.",
            transcript_type="capswriter", title="Test Video", author="Test Author",
        )
        success = cache_manager.create_task(url=url, platform="youtube", media_id="test-video")
        cache_manager.update_task_status(
            success["task_id"], "success", platform="youtube", media_id="test-video",
            title="Test Video", author="Test Author",
        )
        assert success["view_token"] == failed["view_token"]
        task_info = cache_manager.get_task_by_view_token(success["view_token"])
        view_data = cache_manager.get_view_data_by_token(success["view_token"])
        assert task_info is not None
        assert task_info["task_id"] == success["task_id"]
        assert task_info["status"] == "success"
        assert view_data is not None
        assert view_data["status"] == "success"
        assert view_data["media_id"] == "test-video"
    finally:
        cache_manager.close()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__]))
