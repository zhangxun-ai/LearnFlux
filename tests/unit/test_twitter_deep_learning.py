"""Deep-learning routing tests for X/Twitter text sources."""

from __future__ import annotations

import pytest

from video_transcript_api.api.services import transcription
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.downloaders.models import VideoMetadata
from video_transcript_api.downloaders.twitter import TwitterDownloader


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Tracker:
    def __init__(self):
        self.counts = []

    def count(self, name):
        self.counts.append(name)


class _Notifier:
    def __init__(self):
        self.calls = []

    def notify_task_status(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _Router:
    def notify_task_status(self, *args, **kwargs):
        return None

    def send_text(self, *args, **kwargs):
        return None

    def send_long_text(self, *args, **kwargs):
        return None


class _DetailRequester:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def __call__(self, endpoint, params):
        self.calls.append((endpoint, params))
        return {"code": 200, "data": self.data}


def _metadata(text="A detailed explanation of agent architecture."):
    return VideoMetadata(
        video_id="2082108948505674112",
        platform="twitter",
        title="Agent architecture",
        author="leoxbtt",
        description=text,
        extra={"source_type": "social_post", "content_kind": "social_text"},
    )


def test_twitter_text_queues_deep_learning_without_comments(monkeypatch):
    queue = _Queue()
    saved = []
    statuses = []
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(
        transcription.cache_manager,
        "save_cache",
        lambda **kwargs: saved.append(kwargs) or {"cache_id": "cache-x"},
    )
    monkeypatch.setattr(
        transcription.cache_manager,
        "update_task_status",
        lambda *args, **kwargs: statuses.append((args, kwargs)) or True,
    )
    monkeypatch.setattr(
        transcription,
        "_safe_update_progress",
        lambda *args, **kwargs: True,
    )

    result = transcription._queue_twitter_text_deep_learning(
        task_id="task-x",
        url=(
            "https://x.com/leoxbtt/status/"
            "2082108948505674112/video/1?s=46"
        ),
        display_url="X source",
        metadata=_metadata(),
        use_speaker_recognition=False,
        wechat_webhook=None,
        notification_channel=None,
        notification_webhooks={},
        tracker=_Tracker(),
        task_notifier=_Notifier(),
    )

    assert result["status"] == "success"
    assert saved[0]["platform"] == "twitter"
    assert saved[0]["transcript_data"].startswith("A detailed explanation")
    assert len(queue.items) == 1
    payload = queue.items[0]
    assert payload["analysis_intent"] == "deep_learning"
    assert payload["source_type"] == "social_post"
    assert payload["content_kind"] == "social_text"
    assert payload["include_comments"] is False
    assert payload["comment_only"] is False
    assert statuses


def test_twitter_text_rejects_empty_content_without_cache_or_llm(monkeypatch):
    queue = _Queue()
    saved = []
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(
        transcription.cache_manager,
        "save_cache",
        lambda **kwargs: saved.append(kwargs) or True,
    )

    with pytest.raises(ValueError, match="未获取到可学习内容"):
        transcription._queue_twitter_text_deep_learning(
            task_id="task-x",
            url="https://x.com/leoxbtt/status/2082108948505674112",
            display_url="X source",
            metadata=_metadata(text=""),
            use_speaker_recognition=False,
            wechat_webhook=None,
            notification_channel=None,
            notification_webhooks={},
            tracker=_Tracker(),
            task_notifier=_Notifier(),
        )

    assert saved == []
    assert queue.items == []


def test_twitter_text_rejects_lookalike_host_before_side_effects(monkeypatch):
    queue = _Queue()
    monkeypatch.setattr(transcription, "llm_task_queue", queue)

    with pytest.raises(ValueError, match="不是受支持的 X"):
        transcription._queue_twitter_text_deep_learning(
            task_id="task-x",
            url="https://x.com.evil.example/leoxbtt/status/2082108948505674112",
            display_url="X source",
            metadata=_metadata(),
            use_speaker_recognition=False,
            wechat_webhook=None,
            notification_channel=None,
            notification_webhooks={},
            tracker=_Tracker(),
            task_notifier=_Notifier(),
        )

    assert queue.items == []


def test_worker_uses_confirmed_twitter_adapter_not_client_source_hint():
    source = (
        transcription.Path(transcription.__file__)
        .read_text(encoding="utf-8")
    )

    assert "isinstance(metadata_downloader, TwitterDownloader)" in source
    assert "source_type == \"social_post\"" not in source


def test_noncanonical_twitter_match_cannot_reuse_twitter_cache(monkeypatch):
    cache_calls = []
    cache = type(
        "_Cache",
        (),
        {
            "get_cache": lambda self, **kwargs: cache_calls.append(kwargs) or None,
            "update_task_status": lambda self, *args, **kwargs: True,
            "update_task_progress": lambda self, *args, **kwargs: True,
        },
    )()
    helper = []
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: _Router())
    monkeypatch.setattr(
        transcription,
        "_queue_twitter_text_deep_learning",
        lambda **kwargs: helper.append(kwargs),
    )
    monkeypatch.setattr(
        transcription,
        "create_downloader",
        lambda url: (_ for _ in ()).throw(RuntimeError("stop after route check")),
    )

    result = transcription.process_transcription(
        "task-x",
        "https://evil.example/x.com/user/status/2082108948505674112",
        source_type="social_post",
        analysis_intent="deep_learning",
    )

    assert result["status"] == "failed"
    assert cache_calls == []
    assert helper == []


def test_process_routes_confirmed_x_text_to_text_helper_once(monkeypatch):
    requester = _DetailRequester(
        {
            "id": "2082108948505674112",
            "display_text": "Deep explanation in the post body.",
            "author": {"screen_name": "leoxbtt"},
        }
    )
    downloader = TwitterDownloader(request_func=requester)
    cache = type(
        "_Cache",
        (),
        {
            "get_cache": lambda self, **kwargs: None,
            "update_task_status": lambda self, *args, **kwargs: True,
            "update_task_progress": lambda self, *args, **kwargs: True,
        },
    )()
    helper_calls = []
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: _Router())
    monkeypatch.setattr(
        transcription,
        "_queue_twitter_text_deep_learning",
        lambda **kwargs: helper_calls.append(kwargs)
        or {"status": "success", "message": "queued"},
    )

    result = transcription.process_transcription(
        "task-x",
        "https://x.com/leoxbtt/status/2082108948505674112/video/1?s=46",
        source_type="wechat_mp_article",
        analysis_intent="deep_learning",
        include_comments=True,
    )

    assert result["status"] == "success"
    assert len(helper_calls) == 1
    assert helper_calls[0]["metadata"].extra["content_kind"] == "social_text"
    assert len(requester.calls) == 1


def test_process_routes_confirmed_x_video_to_existing_media_pipeline(monkeypatch):
    requester = _DetailRequester(
        {
            "id": "2082108948505674112",
            "display_text": "Context for the video.",
            "author": {"screen_name": "leoxbtt"},
            "media_playable_url": "https://video.twimg.com/clip.mp4",
        }
    )
    downloader = TwitterDownloader(request_func=requester)
    downloader.download_file = lambda *args, **kwargs: "/tmp/twitter-test.mp4"
    cache = type(
        "_Cache",
        (),
        {
            "get_cache": lambda self, **kwargs: None,
            "update_task_status": lambda self, *args, **kwargs: True,
            "update_task_progress": lambda self, *args, **kwargs: True,
        },
    )()
    local_calls = []
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: _Router())
    monkeypatch.setattr(
        transcription,
        "_submit_local_link_asr",
        lambda **kwargs: local_calls.append(kwargs)
        or {"status": "processing", "message": "local_asr_queued"},
    )

    result = transcription.process_transcription(
        "task-x",
        "https://x.com/leoxbtt/status/2082108948505674112/video/1?s=46",
        source_type="wechat_mp_article",
        analysis_intent="deep_learning",
        include_comments=True,
        transcription_strategy="local",
    )

    assert result["status"] == "processing"
    assert len(local_calls) == 1
    call = local_calls[0]
    assert call["source_type"] == "social_post"
    assert call["content_kind"] == "video"
    assert call["analysis_intent"] == "deep_learning"
    assert call["include_comments"] is False
    assert call["description"] == "Context for the video."
    assert len(requester.calls) == 1


def test_x_video_download_failure_does_not_fall_back_to_post_text(monkeypatch):
    requester = _DetailRequester(
        {
            "id": "2082108948505674112",
            "display_text": "Context must not mask a video download failure.",
            "author": {"screen_name": "leoxbtt"},
            "media_playable_url": "https://video.twimg.com/clip.mp4",
        }
    )
    downloader = TwitterDownloader(request_func=requester)
    downloader.download_file = lambda *args, **kwargs: None
    cache = type(
        "_Cache",
        (),
        {
            "get_cache": lambda self, **kwargs: None,
            "update_task_status": lambda self, *args, **kwargs: True,
            "update_task_progress": lambda self, *args, **kwargs: True,
        },
    )()
    text_helper_calls = []
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: _Router())
    monkeypatch.setattr(
        transcription,
        "_queue_twitter_text_deep_learning",
        lambda **kwargs: text_helper_calls.append(kwargs),
    )

    result = transcription.process_transcription(
        "task-x",
        "https://x.com/leoxbtt/status/2082108948505674112/video/1?s=46",
        analysis_intent="deep_learning",
        transcription_strategy="local",
    )

    assert result["status"] == "failed"
    assert "下载文件失败" in result["message"]
    assert text_helper_calls == []


def test_partial_x_cache_disables_comments_and_skips_detail_fetch(
    tmp_path, monkeypatch
):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    queue = _Queue()
    x_url = (
        "https://x.com/leoxbtt/status/"
        "2082108948505674112/video/1?s=46"
    )
    task = cache.create_task(
        url=x_url,
        platform="twitter",
        media_id="2082108948505674112",
    )
    cache.save_cache(
        platform="twitter",
        url=x_url,
        media_id="2082108948505674112",
        use_speaker_recognition=False,
        transcript_data="cached X video transcript",
        transcript_type="capswriter",
        title="Cached X video",
        author="leoxbtt",
        description="tweet context",
    )
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: _Router())
    monkeypatch.setattr(
        transcription,
        "create_downloader",
        lambda url: (_ for _ in ()).throw(
            AssertionError("cached task must not fetch X detail")
        ),
    )

    result = transcription.process_transcription(
        task["task_id"],
        x_url,
        source_type="wechat_mp_article",
        include_comments=True,
        analysis_intent="deep_learning",
    )

    assert result["status"] == "success"
    assert len(queue.items) == 1
    payload = queue.items[0]
    assert payload["include_comments"] is False
    assert payload["comment_only"] is False
    assert payload["source_type"] == "social_post"
    assert payload["analysis_intent"] == "deep_learning"


def test_full_x_cache_skips_detail_fetch_and_new_llm_work(tmp_path, monkeypatch):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    queue = _Queue()
    x_url = (
        "https://x.com/leoxbtt/status/"
        "2082108948505674112/video/1?s=46"
    )
    task = cache.create_task(
        url=x_url,
        platform="twitter",
        media_id="2082108948505674112",
    )
    cache.save_cache(
        platform="twitter",
        url=x_url,
        media_id="2082108948505674112",
        use_speaker_recognition=False,
        transcript_data="cached X video transcript",
        transcript_type="capswriter",
        title="Cached X video",
        author="leoxbtt",
        description="tweet context",
    )
    cache.save_llm_result(
        "twitter",
        "2082108948505674112",
        False,
        "calibrated",
        "calibrated X transcript",
    )
    cache.save_llm_result(
        "twitter",
        "2082108948505674112",
        False,
        "summary",
        "deep-learning summary",
    )
    monkeypatch.setattr(transcription, "cache_manager", cache)
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(transcription, "get_notification_router", lambda: _Router())
    monkeypatch.setattr(
        transcription,
        "create_downloader",
        lambda url: (_ for _ in ()).throw(
            AssertionError("full cache must not fetch X detail")
        ),
    )

    result = transcription.process_transcription(
        task["task_id"],
        x_url,
        include_comments=True,
        analysis_intent="deep_learning",
    )

    assert result["status"] == "success"
    assert result["data"]["cached"] is True
    assert queue.items == []
