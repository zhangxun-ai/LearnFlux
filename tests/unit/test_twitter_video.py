"""Offline regressions for X embedded video routing and cache isolation."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_transcript_api.api.services import transcription
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.downloaders.factory import create_downloader
from video_transcript_api.downloaders.twitter import TwitterDownloader


TWEET_ID = "2115474764672225585"
POST_URL = f"https://x.com/0xkichiro/status/{TWEET_ID}"
VIDEO_URL = f"{POST_URL}/video/1"
TEXT = "This is a description of the lecture, not the spoken lecture."
MP4 = "https://video.twimg.com/amplify_video/sample/lecture.mp4?tag=14"
VIDEO = {
    "type": "video",
    "expanded_url": VIDEO_URL,
    "video_info": {
        "duration_millis": 7427086,
        "variants": [
            {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/a.m3u8"},
            {"content_type": "video/mp4", "bitrate": 256000, "url": "https://video.twimg.com/low.mp4"},
            {"content_type": "video/mp4", "bitrate": 832000, "url": MP4},
        ],
    },
}


def detail(videos=None):
    return {
        "code": 200,
        "data": {
            "id": TWEET_ID,
            "author": {"screen_name": "0xkichiro"},
            "text": TEXT,
            "display_text": TEXT,
            "entities": {"media": deepcopy([VIDEO] if videos is None else videos)},
        },
    }


def adapter(monkeypatch, response):
    downloader = TwitterDownloader()
    request = Mock(return_value=response)
    monkeypatch.setattr(downloader, "make_api_request", request)
    return downloader, request


@pytest.mark.parametrize("url", [VIDEO_URL, POST_URL, POST_URL.replace("x.com", "twitter.com")])
def test_factory_recognizes_x_post_and_video_urls(url):
    assert isinstance(create_downloader(url), TwitterDownloader)


def test_actual_tikhub_entities_shape_exposes_video_not_text(monkeypatch):
    downloader, request = adapter(monkeypatch, detail())
    metadata = downloader.get_metadata(VIDEO_URL)
    download = downloader.get_download_info(VIDEO_URL)
    assert metadata.video_id == f"{TWEET_ID}_video_1"
    assert metadata.duration == 7427.086
    assert metadata.extra["media_type"] == "video"
    assert download.download_url == MP4
    assert download.filename == f"twitter_{TWEET_ID}_video_1.mp4"
    assert downloader.get_subtitle(VIDEO_URL) is None
    request.assert_called_once_with(
        "/api/v1/twitter/web/fetch_tweet_detail", {"tweet_id": TWEET_ID}
    )


def test_normalized_media_video_shape(monkeypatch):
    response = detail([])
    response["data"]["media"] = {
        "video": [{"duration": 7427086, "variants": VIDEO["video_info"]["variants"]}]
    }
    downloader, _ = adapter(monkeypatch, response)
    assert downloader.get_metadata(VIDEO_URL).duration == 7427.086
    assert downloader.get_download_info(VIDEO_URL).download_url == MP4


def test_quote_embed_is_resolved_without_reading_reply_videos(monkeypatch):
    response = detail([])
    response["data"]["quoted"] = detail()["data"]
    downloader, _ = adapter(monkeypatch, response)
    assert downloader.get_download_info(POST_URL).download_url == MP4
    response = detail([])
    response["data"]["thread"] = [detail()["data"]]
    downloader, _ = adapter(monkeypatch, response)
    assert downloader.get_metadata(POST_URL).extra["media_type"] == "article"


def test_video_selectors_have_separate_media_and_instance_caches(monkeypatch):
    second = deepcopy(VIDEO)
    second["expanded_url"] = POST_URL + "/video/2"
    second["video_info"]["variants"] = [
        {"content_type": "video/mp4", "url": "https://video.twimg.com/second.mp4"}
    ]
    downloader, request = adapter(monkeypatch, detail([VIDEO, second]))
    assert downloader.get_metadata(VIDEO_URL).video_id.endswith("_video_1")
    assert downloader.get_metadata(POST_URL + "/video/2").video_id.endswith("_video_2")
    assert downloader.get_download_info(VIDEO_URL).download_url == MP4
    assert downloader.get_download_info(POST_URL + "/video/2").download_url.endswith("second.mp4")
    assert request.call_count == 1


def test_mixed_photo_video_uses_expanded_url_selector(monkeypatch):
    second = deepcopy(VIDEO)
    second["expanded_url"] = POST_URL + "/video/2"
    downloader, _ = adapter(monkeypatch, detail([{"type": "photo"}, second]))
    assert downloader.get_metadata(POST_URL + "/video/2").video_id.endswith("_video_2")
    assert downloader.get_metadata(POST_URL).video_id.endswith("_video_2")


def test_text_post_stays_text_but_explicit_missing_video_fails(monkeypatch):
    downloader, _ = adapter(monkeypatch, detail([]))
    assert downloader.get_metadata(POST_URL).extra["media_type"] == "article"
    with pytest.raises(ValueError, match="未改用帖子正文"):
        downloader.get_metadata(VIDEO_URL)


@pytest.mark.parametrize("variants", [
    [],
    [{"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/a.m3u8"}],
    [{"content_type": "video/mp4", "url": "http://127.0.0.1/private.mp4"}],
])
def test_unavailable_mp4_never_falls_back_to_description(monkeypatch, variants):
    response = detail()
    response["data"]["entities"]["media"][0]["video_info"]["variants"] = variants
    downloader, _ = adapter(monkeypatch, response)
    assert downloader.get_metadata(VIDEO_URL).extra["media_type"] == "video"
    with pytest.raises(ValueError, match="未改用帖子正文"):
        downloader.get_download_info(VIDEO_URL)


def install_flow(monkeypatch, tmp_path, *, url=VIDEO_URL, response=None):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    task = cache.create_task(url=url, use_speaker_recognition=False)
    queue = SimpleNamespace(items=[])
    queue.put = queue.items.append
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: Mock())
    downloader, _ = adapter(monkeypatch, response or detail())
    monkeypatch.setattr(transcription, "create_downloader", lambda _: downloader)
    return cache, task, queue, downloader


@pytest.mark.parametrize("url", [VIDEO_URL, POST_URL])
@pytest.mark.parametrize("strategy", ["cloud", "local"])
def test_video_bypasses_legacy_text_cache_and_uses_selected_asr(
    monkeypatch, tmp_path, url, strategy,
):
    cache, task, queue, downloader = install_flow(monkeypatch, tmp_path, url=url)
    cache.save_cache(
        platform="twitter", url=VIDEO_URL, media_id=TWEET_ID,
        use_speaker_recognition=False, transcript_data=TEXT,
        transcript_type="capswriter", description="X 帖子正文",
    )
    media = tmp_path / "download.mp4"
    media.write_bytes(b"offline video fixture")
    download = Mock(return_value=str(media))
    monkeypatch.setattr(transcription, "_download_file_with_progress", download)
    text_path = Mock(side_effect=AssertionError("Video must never enter text path"))
    monkeypatch.setattr(transcription, "_queue_twitter_post_deep_learning", text_path)
    cloud = Mock(return_value={"status": "awaiting_cloud_confirmation"})
    local = Mock(return_value={"status": "processing"})
    monkeypatch.setattr(transcription, "_pause_for_cloud_confirmation", cloud)
    monkeypatch.setattr(transcription, "_submit_local_link_asr", local)

    result = transcription.process_transcription(
        task["task_id"], url, transcription_strategy=strategy,
        cloud_confirmation_required=True,
    )

    download.assert_called_once_with(downloader, MP4, f"twitter_{TWEET_ID}_video_1.mp4", task["task_id"])
    assert queue.items == []
    text_path.assert_not_called()
    # The original erroneous result remains readable; no user data is deleted.
    assert cache.get_cache("twitter", TWEET_ID, False)["transcript_data"] == TEXT
    if strategy == "cloud":
        assert result["status"] == "awaiting_cloud_confirmation"
        cloud.assert_called_once()
        assert cloud.call_args.kwargs["media_path"] == str(media)
        assert f"{TWEET_ID}_video_1" in cloud.call_args.kwargs["continuation_json"]
        local.assert_not_called()
    else:
        assert result["status"] == "processing"
        assert local.call_args.kwargs["media_id"] == f"{TWEET_ID}_video_1"
        cloud.assert_not_called()


def test_plain_post_keeps_existing_deep_learning_flow(monkeypatch, tmp_path):
    _, task, _, _ = install_flow(monkeypatch, tmp_path, url=POST_URL, response=detail([]))
    text_path = Mock(return_value={"status": "success", "data": {"media_type": "article"}})
    monkeypatch.setattr(transcription, "_queue_twitter_post_deep_learning", text_path)
    result = transcription.process_transcription(task["task_id"], POST_URL)
    assert result["data"]["media_type"] == "article"
    assert text_path.call_args.kwargs["tweet_id"] == TWEET_ID


def test_missing_video_fails_before_legacy_cache_or_text_path(monkeypatch, tmp_path):
    cache, task, queue, _ = install_flow(monkeypatch, tmp_path, response=detail([]))
    cache_read = Mock(side_effect=AssertionError("Do not reuse post text"))
    monkeypatch.setattr(cache, "get_cache", cache_read)
    result = transcription.process_transcription(task["task_id"], VIDEO_URL, transcription_strategy="cloud")
    assert result["status"] == "failed"
    assert "未改用帖子正文" in result["message"]
    assert not queue.items
    cache_read.assert_not_called()


def test_real_video_cache_is_reused_without_redownload_or_asr(monkeypatch, tmp_path):
    cache, task, queue, _ = install_flow(monkeypatch, tmp_path)
    speech = "Welcome to the lecture. Today we will build an agent."
    cache.save_cache(
        platform="twitter", url=VIDEO_URL, media_id=f"{TWEET_ID}_video_1",
        use_speaker_recognition=False, transcript_data=speech,
        transcript_type="capswriter",
    )
    download = Mock(side_effect=AssertionError("Cached video must not be downloaded"))
    monkeypatch.setattr(transcription, "_download_file_with_progress", download)
    result = transcription.process_transcription(task["task_id"], VIDEO_URL)
    assert result["data"]["transcript"] == speech
    assert result["data"]["cached"] is True
    assert queue.items[0]["media_id"] == f"{TWEET_ID}_video_1"
    download.assert_not_called()


@pytest.mark.parametrize("response", [{"code": 200, "data": {}}, {"code": 404}])
def test_detail_failure_never_becomes_post_text(monkeypatch, response):
    downloader, _ = adapter(monkeypatch, response)
    with pytest.raises(ValueError):
        downloader.get_metadata(VIDEO_URL)
