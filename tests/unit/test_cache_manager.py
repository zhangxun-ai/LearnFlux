"""Unit tests for CacheManager.

NOTE: The integration-style tests in tests/cache/test_cache_manager.py cover
manual end-to-end flows. This file focuses on isolated, pytest-based unit tests
with tmp_path fixtures and no side effects.
"""
import json
import threading
from pathlib import Path

import pytest

from src.video_transcript_api.cache.cache_manager import CacheManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_dir(tmp_path):
    """Provide a temporary cache directory."""
    return tmp_path / "cache"


@pytest.fixture
def cm(cache_dir):
    """Create a CacheManager with a temporary directory."""
    manager = CacheManager(cache_dir=str(cache_dir))
    yield manager
    manager.close()


def _save_sample_capswriter(cm, media_id="vid1", platform="youtube"):
    """Helper: save a capswriter transcript and return the result dict."""
    return cm.save_cache(
        platform=platform,
        url=f"https://example.com/{media_id}",
        media_id=media_id,
        use_speaker_recognition=False,
        transcript_data="Hello world. This is a test transcript.",
        transcript_type="capswriter",
        title="Test Video",
        author="Author",
        description="A test video",
    )


def _save_sample_funasr(cm, media_id="vid2", platform="bilibili"):
    """Helper: save a funasr transcript and return the result dict."""
    funasr_data = {
        "speakers": ["Speaker1", "Speaker2"],
        "segments": [
            {"speaker": "Speaker1", "text": "Hello", "start": 0, "end": 1},
            {"speaker": "Speaker2", "text": "Hi", "start": 1, "end": 2},
        ],
    }
    return cm.save_cache(
        platform=platform,
        url=f"https://example.com/{media_id}",
        media_id=media_id,
        use_speaker_recognition=True,
        transcript_data=funasr_data,
        transcript_type="funasr",
        title="FunASR Video",
        author="Author2",
        description="A funasr test",
    )


# ---------------------------------------------------------------------------
# save_cache
# ---------------------------------------------------------------------------

class TestSaveCache:
    """Tests for CacheManager.save_cache."""

    def test_returns_dict_on_success(self, cm):
        result = _save_sample_capswriter(cm)
        assert result is not None
        assert result["platform"] == "youtube"
        assert result["media_id"] == "vid1"

    def test_creates_directory_structure(self, cm, cache_dir):
        _save_sample_capswriter(cm)
        # Directory should exist under cache_dir/youtube/YYYY/YYYYMM/vid1
        dirs = list(cache_dir.rglob("vid1"))
        assert len(dirs) == 1
        assert dirs[0].is_dir()

    def test_capswriter_creates_txt_file(self, cm, cache_dir):
        _save_sample_capswriter(cm)
        txt_files = list(cache_dir.rglob("transcript_capswriter.txt"))
        assert len(txt_files) == 1
        content = txt_files[0].read_text(encoding="utf-8")
        assert "Hello world" in content

    def test_funasr_creates_json_file(self, cm, cache_dir):
        _save_sample_funasr(cm)
        json_files = list(cache_dir.rglob("transcript_funasr.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert "speakers" in data
        assert len(data["segments"]) == 2

    def test_extra_json_data_saved(self, cm, cache_dir):
        extra = {"compat": True, "segments": []}
        cm.save_cache(
            platform="youtube",
            url="https://example.com/extra",
            media_id="extra1",
            use_speaker_recognition=False,
            transcript_data="text content",
            transcript_type="capswriter",
            extra_json_data=extra,
        )
        json_files = list(cache_dir.rglob("transcript_capswriter.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert data["compat"] is True


class TestTaskSourceFilePath:
    """Tests for optional preserved source file metadata on tasks."""

    def test_update_task_status_persists_source_file_path(self, cm, tmp_path):
        task = cm.create_task(
            url="https://weixin.qq.com/sph/A1kpVPJjiX",
            platform="wechat_channels",
            media_id="A1kpVPJjiX",
        )
        source_file = tmp_path / "wechat.mp4"
        source_file.write_bytes(b"video")

        cm.update_task_status(
            task["task_id"],
            "calibrating",
            source_file_path=str(source_file),
        )

        row = cm.get_task_by_id(task["task_id"])
        assert row["source_file_path"] == str(source_file)

    def test_view_data_includes_source_file_path(self, cm, tmp_path):
        task = cm.create_task(
            url="https://weixin.qq.com/sph/A1kpVPJjiX",
            platform="wechat_channels",
            media_id="A1kpVPJjiX",
        )
        _save_sample_capswriter(cm, media_id="A1kpVPJjiX", platform="wechat_channels")
        source_file = tmp_path / "wechat.mp4"
        source_file.write_bytes(b"video")
        cm.update_task_status(
            task["task_id"],
            "success",
            platform="wechat_channels",
            media_id="A1kpVPJjiX",
            source_file_path=str(source_file),
        )

        view_data = cm.get_view_data_by_token(task["view_token"])

        assert view_data["source_file_path"] == str(source_file)


# ---------------------------------------------------------------------------
# get_cache
# ---------------------------------------------------------------------------

class TestGetCache:
    """Tests for CacheManager.get_cache."""

    def test_returns_saved_capswriter_data(self, cm):
        _save_sample_capswriter(cm)
        result = cm.get_cache(platform="youtube", media_id="vid1")
        assert result is not None
        assert result["transcript_type"] == "capswriter"
        assert "Hello world" in result["transcript_data"]

    def test_returns_saved_funasr_data(self, cm):
        _save_sample_funasr(cm)
        result = cm.get_cache(
            platform="bilibili", media_id="vid2", use_speaker_recognition=True
        )
        assert result is not None
        assert result["transcript_type"] == "funasr"
        assert len(result["transcript_data"]["speakers"]) == 2

    def test_returns_none_for_missing(self, cm):
        result = cm.get_cache(platform="youtube", media_id="nonexistent")
        assert result is None

    def test_returns_none_when_no_params(self, cm):
        result = cm.get_cache()
        assert result is None

    def test_query_by_url(self, cm):
        _save_sample_capswriter(cm)
        result = cm.get_cache(url="https://example.com/vid1")
        assert result is not None
        assert result["media_id"] == "vid1"

    def test_returns_metadata_fields(self, cm):
        _save_sample_capswriter(cm)
        result = cm.get_cache(platform="youtube", media_id="vid1")
        assert result["title"] == "Test Video"
        assert result["author"] == "Author"
        assert result["platform"] == "youtube"


class TestDeleteTaskAndCache:
    """Tests for invalidating a completed task's shared media cache."""

    def test_removes_media_cache_and_all_associated_tasks(self, cm):
        media_id = "douyin-video"
        cache_result = _save_sample_capswriter(
            cm, media_id=media_id, platform="douyin"
        )
        first = cm.create_task(
            url="https://v.douyin.com/example/",
            platform="douyin",
            media_id=media_id,
        )
        second = cm.create_task(
            url="https://www.douyin.com/video/example",
            platform="douyin",
            media_id=media_id,
        )
        for task in (first, second):
            cm.update_task_status(
                task["task_id"],
                "success",
                platform="douyin",
                media_id=media_id,
            )
        cache_path = Path(cache_result["transcript_file"]).parent

        deleted = cm.delete_task_and_cache(first["task_id"])

        assert deleted == {"deleted_caches": 1, "deleted_tasks": 2}
        assert not cache_path.exists()
        assert cm.get_cache(platform="douyin", media_id=media_id) is None
        assert cm.get_task_by_id(first["task_id"]) is None
        assert cm.get_task_by_id(second["task_id"]) is None


# ---------------------------------------------------------------------------
# save_llm_result
# ---------------------------------------------------------------------------

class TestSaveLLMResult:
    """Tests for CacheManager.save_llm_result."""

    def test_save_calibrated(self, cm, cache_dir):
        _save_sample_capswriter(cm)
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="calibrated",
            content="Calibrated text here.",
        )
        assert ok is True
        files = list(cache_dir.rglob("llm_calibrated.txt"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == "Calibrated text here."

    def test_save_summary(self, cm, cache_dir):
        _save_sample_capswriter(cm)
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="summary",
            content="Summary bullet points.",
        )
        assert ok is True
        files = list(cache_dir.rglob("llm_summary.txt"))
        assert len(files) == 1

    def test_save_structured(self, cm, cache_dir):
        _save_sample_capswriter(cm)
        structured = {"sections": [{"title": "Intro", "content": "Hello"}]}
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="structured",
            content=structured,
        )
        assert ok is True
        files = list(cache_dir.rglob("llm_processed.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["format_version"] == "v2"
        assert data["sections"][0]["title"] == "Intro"

    def test_structured_rejects_non_dict(self, cm):
        _save_sample_capswriter(cm)
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="structured",
            content="not a dict",
        )
        assert ok is False

    def test_returns_false_for_missing_cache(self, cm):
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="nonexistent",
            use_speaker_recognition=False,
            llm_type="calibrated",
            content="text",
        )
        assert ok is False

    def test_unknown_llm_type_returns_false(self, cm):
        _save_sample_capswriter(cm)
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="unknown_type",
            content="text",
        )
        assert ok is False

    def test_get_cache_includes_llm_results(self, cm):
        _save_sample_capswriter(cm)
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="calibrated",
            content="Calibrated.",
        )
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="summary",
            content="Summary.",
        )
        result = cm.get_cache(platform="youtube", media_id="vid1")
        assert "llm_calibrated" in result
        assert result["llm_calibrated"] == "Calibrated."
        assert "llm_summary" in result
        assert result["llm_summary"] == "Summary."

    def test_save_comment_insight(self, cm, cache_dir):
        _save_sample_capswriter(cm)
        ok = cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="comment_insight",
            content="Comment insight.",
        )
        assert ok is True
        files = list(cache_dir.rglob("comment_insight.txt"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == "Comment insight."

    def test_save_comment_samples_and_get_cache(self, cm):
        _save_sample_capswriter(cm)
        samples = [{"text": "useful comment", "like_count": 12}]
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="comment_samples",
            content=samples,
        )

        result = cm.get_cache(platform="youtube", media_id="vid1")

        assert result["comment_samples"] == samples


# ---------------------------------------------------------------------------
# list_cache
# ---------------------------------------------------------------------------

class TestListCache:
    """Tests for CacheManager.list_cache."""

    def test_empty_returns_empty_list(self, cm):
        assert cm.list_cache() == []

    def test_returns_saved_records(self, cm):
        _save_sample_capswriter(cm, media_id="a")
        _save_sample_capswriter(cm, media_id="b")
        results = cm.list_cache()
        assert len(results) == 2

    def test_filter_by_platform(self, cm):
        _save_sample_capswriter(cm, media_id="a", platform="youtube")
        _save_sample_funasr(cm, media_id="b", platform="bilibili")
        results = cm.list_cache(platform="youtube")
        assert len(results) == 1
        assert results[0]["platform"] == "youtube"

    def test_pagination_limit(self, cm):
        for i in range(5):
            _save_sample_capswriter(cm, media_id=f"v{i}")
        results = cm.list_cache(limit=3)
        assert len(results) == 3

    def test_pagination_offset(self, cm):
        for i in range(5):
            _save_sample_capswriter(cm, media_id=f"v{i}")
        all_results = cm.list_cache(limit=100)
        offset_results = cm.list_cache(limit=100, offset=2)
        assert len(offset_results) == len(all_results) - 2


# ---------------------------------------------------------------------------
# get_cache_stats
# ---------------------------------------------------------------------------

class TestGetCacheStats:
    """Tests for CacheManager.get_cache_stats."""

    def test_empty_stats(self, cm):
        stats = cm.get_cache_stats()
        assert stats["total_records"] == 0
        assert stats["platform_stats"] == {}

    def test_counts_records(self, cm):
        _save_sample_capswriter(cm, media_id="a")
        _save_sample_funasr(cm, media_id="b")
        stats = cm.get_cache_stats()
        assert stats["total_records"] == 2

    def test_platform_stats(self, cm):
        _save_sample_capswriter(cm, media_id="a", platform="youtube")
        _save_sample_capswriter(cm, media_id="b", platform="youtube")
        _save_sample_funasr(cm, media_id="c", platform="bilibili")
        stats = cm.get_cache_stats()
        assert stats["platform_stats"]["youtube"] == 2
        assert stats["platform_stats"]["bilibili"] == 1

    def test_speaker_recognition_stats(self, cm):
        _save_sample_capswriter(cm, media_id="a")  # speaker=False
        _save_sample_funasr(cm, media_id="b")      # speaker=True
        stats = cm.get_cache_stats()
        assert stats["speaker_recognition_stats"][False] == 1
        assert stats["speaker_recognition_stats"][True] == 1

    def test_cache_size_present(self, cm):
        _save_sample_capswriter(cm)
        stats = cm.get_cache_stats()
        assert "cache_size_mb" in stats
        assert stats["cache_size_mb"] >= 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """Tests for per-thread database connections."""

    def test_get_connection_returns_per_thread_connections(self, cm):
        """_get_connection should return different connections in different threads."""
        main_conn = cm._get_connection()
        thread_conn = [None]

        def worker():
            thread_conn[0] = cm._get_connection()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert thread_conn[0] is not None
        assert thread_conn[0] is not main_conn

    def test_concurrent_saves_do_not_raise(self, cm):
        """Multiple threads saving concurrently should not raise exceptions."""
        errors = []

        def worker(idx):
            try:
                cm.save_cache(
                    platform="youtube",
                    url=f"https://example.com/thread{idx}",
                    media_id=f"thread{idx}",
                    use_speaker_recognition=False,
                    transcript_data=f"Transcript from thread {idx}",
                    transcript_type="capswriter",
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        results = cm.list_cache()
        assert len(results) == 5


# ---------------------------------------------------------------------------
# llm_config fallback for cache-hit tasks
# ---------------------------------------------------------------------------

class TestLLMConfigFallback:
    """Tests for llm_config fallback when viewing cache-hit tasks.

    When the same URL is submitted multiple times, later cache-hit tasks
    have no llm_config. The view should fall back to the llm_config from
    an earlier task under the same view_token.
    """

    def _create_task_at_time(self, cm, url, timestamp, llm_config_dict=None):
        """Helper: create a task at a specific timestamp, optionally with llm_config."""
        task_info = cm.create_task(url=url, platform="youtube", media_id="vid1")
        task_id = task_info["task_id"]
        cm.update_task_status(task_id, "success", platform="youtube", media_id="vid1")
        # Force a specific created_at to control ordering
        with cm._get_cursor() as cursor:
            cursor.execute(
                "UPDATE task_status SET created_at = ? WHERE task_id = ?",
                (timestamp, task_id),
            )
        if llm_config_dict:
            cm.update_task_llm_config(task_id, llm_config_dict)
        return task_info

    def test_fallback_returns_llm_config_from_earlier_task(self, cm):
        """Cache-hit task should inherit llm_config from the original LLM task."""
        _save_sample_capswriter(cm)
        config = {"calibrate_model": "deepseek-v4", "summary_model": "deepseek-v4"}

        # T=00:00: LLM task with config
        self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 00:00:00", config
        )
        # T=01:00: cache-hit task, no config
        cache_hit = self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 01:00:00"
        )

        view_data = cm.get_view_data_by_token(cache_hit["view_token"])
        assert view_data is not None
        assert view_data.get("llm_config") is not None
        assert view_data["llm_config"]["calibrate_model"] == "deepseek-v4"

    def test_fallback_returns_most_recent_llm_config(self, cm):
        """When multiple tasks have llm_config, the most recent one wins."""
        _save_sample_capswriter(cm)
        old_config = {"calibrate_model": "old-model", "summary_model": "old-model"}
        new_config = {"calibrate_model": "new-model", "summary_model": "new-model"}

        # T=00:00: first LLM task
        self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 00:00:00", old_config
        )
        # T=01:00: second LLM task (recalibrate)
        self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 01:00:00", new_config
        )
        # T=02:00: cache-hit task
        cache_hit = self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 02:00:00"
        )

        view_data = cm.get_view_data_by_token(cache_hit["view_token"])
        assert view_data["llm_config"]["calibrate_model"] == "new-model"

    def test_no_fallback_needed_when_latest_task_has_config(self, cm):
        """Direct llm_config on the latest task should be used without fallback."""
        _save_sample_capswriter(cm)
        config = {"calibrate_model": "direct-model", "summary_model": "direct-model"}

        task = self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 00:00:00", config
        )

        view_data = cm.get_view_data_by_token(task["view_token"])
        assert view_data["llm_config"]["calibrate_model"] == "direct-model"

    def test_no_llm_config_anywhere_returns_none(self, cm):
        """If no task under this view_token has llm_config, return None."""
        _save_sample_capswriter(cm)
        cache_hit = self._create_task_at_time(
            cm, "https://example.com/vid1", "2026-01-01 00:00:00"
        )

        view_data = cm.get_view_data_by_token(cache_hit["view_token"])
        assert view_data is not None
        assert view_data.get("llm_config") is None


class TestCommentInsightViewData:
    """Tests for exposing comment insight artifacts to view templates."""

    def test_view_data_includes_comment_insight_and_samples(self, cm):
        _save_sample_capswriter(cm)
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="calibrated",
            content="Calibrated.",
        )
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="summary",
            content="Summary.",
        )
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="comment_insight",
            content="Comment insight.",
        )
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="comment_samples",
            content=[{"text": "useful comment", "like_count": 42}],
        )
        task_info = cm.create_task(
            url="https://example.com/vid1",
            platform="youtube",
            media_id="vid1",
        )
        cm.update_task_status(
            task_info["task_id"],
            "success",
            platform="youtube",
            media_id="vid1",
        )

        view_data = cm.get_view_data_by_token(task_info["view_token"])

        assert view_data["comment_insight"] == "Comment insight."
        assert view_data["comment_samples"] == [
            {"text": "useful comment", "like_count": 42}
        ]


class TestTaskProgress:
    """Tests for persisted task progress."""

    def test_create_task_initializes_queued_progress(self, cm):
        task = cm.create_task(url="https://example.com/progress")

        task_info = cm.get_task_by_id(task["task_id"])

        assert task_info["progress"]["stage"] == "queued"
        assert task_info["progress"]["percent"] == 0
        assert task_info["progress"]["basis"] == "task_created"

    def test_update_task_progress_persists_structured_progress(self, cm):
        task = cm.create_task(url="https://example.com/progress-update")

        cm.update_task_progress(
            task["task_id"],
            stage="downloading",
            stage_label="正在下载音视频",
            fraction=0.5,
            basis="download_bytes",
            confidence="high",
            evidence={"completed": 50, "total": 100, "unit": "bytes"},
        )

        task_info = cm.get_task_by_id(task["task_id"])

        assert task_info["progress"]["stage"] == "downloading"
        assert task_info["progress"]["percent"] == 22
        assert task_info["progress"]["confidence"] == "high"
        assert task_info["progress"]["evidence"]["unit"] == "bytes"

    def test_processing_view_data_includes_progress_and_tokens(self, cm):
        task = cm.create_task(
            url="https://www.youtube.com/watch?v=abc123",
            platform="youtube",
            media_id="abc123",
        )
        cm.update_task_status(task["task_id"], "processing")
        cm.update_task_progress(
            task["task_id"],
            stage="transcribing",
            stage_label="正在转录音视频",
            fraction=0.25,
            basis="capswriter_audio_sent",
            confidence="medium",
        )

        view_data = cm.get_view_data_by_token(task["view_token"])

        assert view_data["status"] == "processing"
        assert view_data["task_id"] == task["task_id"]
        assert view_data["view_token"] == task["view_token"]
        assert view_data["platform"] == "youtube"
        assert view_data["media_id"] == "abc123"
        assert view_data["progress"]["stage"] == "transcribing"
        assert view_data["progress"]["percent"] == 46

    def test_view_token_prefers_success_over_older_failed_task(self, cm):
        url = "https://www.xiaohongshu.com/discovery/item/note123?xsec_token=tok"
        failed_task = cm.create_task(
            url=url,
            platform="xiaohongshu",
            media_id="note123",
        )
        cm.update_task_status(
            failed_task["task_id"],
            "failed",
            platform="xiaohongshu",
            media_id="note123",
            error_message="old download failed",
        )
        _save_sample_capswriter(cm, media_id="note123", platform="xiaohongshu")
        success_task = cm.create_task(
            url=url,
            platform="xiaohongshu",
            media_id="note123",
        )
        assert success_task["view_token"] == failed_task["view_token"]
        cm.update_task_status(
            success_task["task_id"],
            "success",
            platform="xiaohongshu",
            media_id="note123",
            title="人生怎么作弊",
            author="苏越越",
        )

        task_info = cm.get_task_by_view_token(failed_task["view_token"])
        view_data = cm.get_view_data_by_token(failed_task["view_token"])

        assert task_info["task_id"] == success_task["task_id"]
        assert task_info["status"] == "success"
        assert view_data["status"] == "success"
        assert view_data["media_id"] == "note123"

    def test_processing_view_data_recovers_when_final_cache_exists(self, cm):
        _save_sample_capswriter(cm)
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="calibrated",
            content="final calibrated transcript",
        )
        task = cm.create_task(
            url="https://example.com/vid1",
            platform="youtube",
            media_id="vid1",
        )
        cm.update_task_status(
            task["task_id"],
            "calibrating",
            platform="youtube",
            media_id="vid1",
        )

        view_data = cm.get_view_data_by_token(task["view_token"])
        task_info = cm.get_task_by_id(task["task_id"])

        assert view_data["status"] == "success"
        assert view_data["transcript"] == "final calibrated transcript"
        assert task_info["status"] == "success"
        assert task_info["progress"]["basis"] == "task_completed"

    def test_progress_reminder_markers_are_persisted(self, cm):
        task = cm.create_task(url="https://example.com/progress-reminder")
        cm.update_task_status(task["task_id"], "processing")

        cm.mark_progress_reminder_sent(task["task_id"], "10m")

        task_info = cm.get_task_by_id(task["task_id"])
        active_tasks = cm.list_active_tasks_for_progress_reminders()

        assert task_info["progress_reminders"] == ["10m"]
        assert active_tasks[0]["progress_reminders"] == ["10m"]

    def test_success_view_data_includes_completed_at_for_duration(self, cm):
        _save_sample_capswriter(cm)
        task = cm.create_task(
            url="https://example.com/vid1",
            platform="youtube",
            media_id="vid1",
        )

        cm.update_task_status(
            task["task_id"],
            "success",
            platform="youtube",
            media_id="vid1",
        )

        view_data = cm.get_view_data_by_token(task["view_token"])

        assert view_data["status"] == "success"
        assert view_data["platform"] == "youtube"
        assert view_data["media_id"] == "vid1"
        assert view_data["completed_at"]

    def test_success_view_data_marks_missing_summary(self, cm):
        _save_sample_capswriter(cm)
        cm.save_llm_result(
            platform="youtube",
            media_id="vid1",
            use_speaker_recognition=False,
            llm_type="calibrated",
            content="calibrated body",
        )
        task = cm.create_task(
            url="https://example.com/vid1",
            platform="youtube",
            media_id="vid1",
        )
        cm.update_task_status(
            task["task_id"],
            "success",
            platform="youtube",
            media_id="vid1",
        )

        view_data = cm.get_view_data_by_token(task["view_token"])

        assert view_data["status"] == "success"
        assert view_data["summary"] == ""
        assert view_data["summary_missing"] is True
def test_terminal_progress_preserves_explicit_evidence(tmp_path):
    from video_transcript_api.cache.cache_manager import CacheManager

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    success = manager.create_task(
        url="local://study-source/doc/guide.pdf",
        platform="generic",
        media_id="doc",
    )
    evidence = {
        "analysis_mode": "document_fast",
        "visual_ready": True,
        "quality": {"mode": "fast", "reasons": [], "metrics": {}},
    }
    manager.update_task_status(
        success["task_id"], "success", terminal_evidence=evidence
    )

    failed = manager.create_task(
        url="local://study-source/bad/bad.pdf",
        platform="generic",
        media_id="bad",
    )
    manager.update_task_status(
        failed["task_id"],
        "failed",
        error_message="invalid document",
        terminal_evidence={"analysis_mode": "document_fallback"},
    )

    assert manager.get_task_by_id(success["task_id"])["progress"]["evidence"] == evidence
    assert manager.get_task_by_id(failed["task_id"])["progress"]["evidence"] == {
        "analysis_mode": "document_fallback"
    }
