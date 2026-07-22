from video_transcript_api.cache.cache_manager import CacheManager


def test_translation_is_saved_separately_from_source(tmp_path):
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    manager.save_cache(
        platform="youtube",
        url="https://example.com/video",
        media_id="english-1",
        use_speaker_recognition=False,
        transcript_data="Original English transcript.",
        transcript_type="capswriter",
    )
    before = manager.get_cache(platform="youtube", media_id="english-1")

    manager.save_zh_translation("youtube", "english-1", "中文译文。")
    after = manager.get_cache(platform="youtube", media_id="english-1")

    assert before["transcript_data"] == after["transcript_data"]
    assert after["source_transcript"] == "Original English transcript."
    assert after["zh_translation"] == "中文译文。"
    assert after["translation_language"] == "zh"


def test_legacy_cache_maps_transcript_to_source_without_fake_translation(tmp_path):
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    manager.save_cache(
        platform="youtube",
        url="https://example.com/video",
        media_id="legacy-1",
        use_speaker_recognition=False,
        transcript_data="Legacy source.",
        transcript_type="capswriter",
    )

    cached = manager.get_cache(platform="youtube", media_id="legacy-1")

    assert cached["source_transcript"] == "Legacy source."
    assert cached.get("zh_translation") is None


def test_success_view_data_exposes_bilingual_fields(tmp_path):
    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = manager.create_task(
        url="https://example.com/english-view",
        platform="youtube",
        media_id="english-view",
    )
    manager.save_cache(
        platform="youtube",
        url="https://example.com/english-view",
        media_id="english-view",
        use_speaker_recognition=False,
        transcript_data="Original English transcript.",
        transcript_type="capswriter",
        source_language="en",
    )
    manager.save_zh_translation("youtube", "english-view", "中文译文。")
    manager.update_task_status(
        task["task_id"],
        "success",
        platform="youtube",
        media_id="english-view",
    )

    view_data = manager.get_view_data_by_token(task["view_token"])

    assert view_data["source_transcript"] == "Original English transcript."
    assert view_data["source_language"] == "en"
    assert view_data["zh_translation"] == "中文译文。"
    assert view_data["translation_language"] == "zh"
