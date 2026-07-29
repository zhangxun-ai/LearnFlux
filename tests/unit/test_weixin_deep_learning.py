"""Official Account article source behavior for single-study deep learning."""

import pytest
from unittest.mock import MagicMock

from video_transcript_api.api.services import transcription
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.comments.weixin_post import (
    WeixinArticlePayload,
    WeixinPostFetcher,
)
from video_transcript_api.utils.perf_tracker import PerfTracker
from video_transcript_api.utils.task_status import TaskStatus


ARTICLE_URL = "https://mp.weixin.qq.com/s/r5aDx2ntV9E1QWM3oHe3kw"


class _FakeQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _FakeNotifier:
    def notify_task_status(self, *args, **kwargs):
        return None


class _FakeRouter:
    def notify_task_status(self, *args, **kwargs):
        return None

    def send_text(self, *args, **kwargs):
        return None

    def send_long_text(self, *args, **kwargs):
        return None


def _install_cache_and_queue(monkeypatch, tmp_path):
    cache_manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    queue = _FakeQueue()
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    return cache_manager, queue


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (ARTICLE_URL, True),
        ("https://mp.weixin.qq.com/s?__biz=abc&mid=123", True),
        ("https://evil.example/mp.weixin.qq.com/s/token", False),
        ("https://mp.weixin.qq.com.evil.example/s/token", False),
        ("https://mp.weixin.qq.com@evil.example/s/token", False),
        ("https://sub.mp.weixin.qq.com/s/token", False),
        ("https://weixin.qq.com/sph/AUqdQVIvFa", False),
    ],
)
def test_official_account_predicate_uses_canonical_host_and_path(url, expected):
    assert transcription._is_weixin_official_account_article_url(url) is expected


def test_weixin_article_is_saved_and_queued_without_comment_analysis(
    tmp_path, monkeypatch
):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=ARTICLE_URL,
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
    )

    result = transcription._queue_weixin_article_deep_learning(
        task_id=task["task_id"],
        url=ARTICLE_URL,
        display_url=ARTICLE_URL,
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
        use_speaker_recognition=False,
        wechat_webhook=None,
        notification_channel=None,
        notification_webhooks={},
        preserve_source_file=False,
        tracker=PerfTracker(task_id=task["task_id"]),
        task_notifier=_FakeNotifier(),
        article_fetcher=lambda url: WeixinArticlePayload(
            title="一篇值得深度学习的文章",
            author="AI 实验室",
            text="这是公众号文章正文，应进入深度学习结果。",
        ),
    )

    assert result["status"] == "success"
    cached = cache_manager.get_cache(
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
        use_speaker_recognition=False,
    )
    assert cached["transcript_data"] == "这是公众号文章正文，应进入深度学习结果。"
    queued = queue.items[0]
    assert queued["analysis_intent"] == "deep_learning"
    assert queued["source_type"] == "wechat_mp_article"
    assert queued["include_comments"] is False
    assert queued["transcript"] == "这是公众号文章正文，应进入深度学习结果。"
    task_info = cache_manager.get_task_by_id(task["task_id"])
    assert task_info["status"] == TaskStatus.CALIBRATING


def test_weixin_title_only_article_fails_without_cache_or_llm_work(
    tmp_path, monkeypatch
):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=ARTICLE_URL,
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
    )

    with pytest.raises(ValueError, match="无法获取公众号文章正文"):
        transcription._queue_weixin_article_deep_learning(
            task_id=task["task_id"],
            url=ARTICLE_URL,
            display_url=ARTICLE_URL,
            media_id="r5aDx2ntV9E1QWM3oHe3kw",
            use_speaker_recognition=False,
            wechat_webhook=None,
            notification_channel=None,
            notification_webhooks={},
            preserve_source_file=False,
            tracker=PerfTracker(task_id=task["task_id"]),
            task_notifier=_FakeNotifier(),
            article_fetcher=lambda url: WeixinArticlePayload(
                title="只有标题",
                author="AI 实验室",
                text="",
            ),
        )

    assert queue.items == []
    assert cache_manager.get_cache(
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
        use_speaker_recognition=False,
    ) is None


def test_process_transcription_routes_only_canonical_article_to_helper(monkeypatch):
    cache_manager = MagicMock()
    cache_manager.get_cache.return_value = None
    helper_calls = []
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(
        transcription, "_safe_update_progress", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        transcription, "get_notification_router", lambda: _FakeRouter()
    )
    monkeypatch.setattr(
        transcription,
        "_queue_weixin_article_deep_learning",
        lambda **kwargs: helper_calls.append(kwargs)
        or {"status": "success", "message": "queued"},
    )

    result = transcription.process_transcription(
        "task-1",
        ARTICLE_URL,
        source_type="unknown",
        analysis_intent="deep_learning",
        include_comments=True,
    )

    assert result["status"] == "success"
    assert len(helper_calls) == 1
    assert helper_calls[0]["url"] == ARTICLE_URL


def test_forged_source_type_and_regex_platform_match_cannot_route_to_helper(
    monkeypatch,
):
    cache_manager = MagicMock()
    cache_manager.get_cache.return_value = None
    helper = MagicMock()
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(
        transcription, "_safe_update_progress", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        transcription, "get_notification_router", lambda: _FakeRouter()
    )
    monkeypatch.setattr(
        transcription, "_queue_weixin_article_deep_learning", helper
    )
    monkeypatch.setattr(
        transcription,
        "create_downloader",
        lambda url: (_ for _ in ()).throw(RuntimeError("stop after route check")),
    )
    lookalike = "https://evil.example/mp.weixin.qq.com/s/token"

    result = transcription.process_transcription(
        "task-2",
        lookalike,
        source_type="wechat_mp_article",
        analysis_intent="deep_learning",
    )

    assert result["status"] == "failed"
    helper.assert_not_called()


def test_partial_cache_ignores_requested_comment_analysis(tmp_path, monkeypatch):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=ARTICLE_URL,
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
    )
    cache_manager.save_cache(
        platform="weixin",
        url=ARTICLE_URL,
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
        use_speaker_recognition=False,
        transcript_data="已缓存的公众号正文",
        transcript_type="capswriter",
        title="缓存文章",
        author="作者",
        description="微信公众号文章正文",
    )
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(
        transcription, "_safe_update_progress", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        transcription, "get_notification_router", lambda: _FakeRouter()
    )

    result = transcription.process_transcription(
        task["task_id"],
        ARTICLE_URL,
        include_comments=True,
        analysis_intent="deep_learning",
    )

    assert result["status"] == "success"
    queued = queue.items[0]
    assert queued["include_comments"] is False
    assert queued["comment_only"] is False
    assert queued["source_type"] == "wechat_mp_article"
    assert queued["analysis_intent"] == "deep_learning"


def test_full_cache_serial_resubmission_skips_fetch_and_new_llm_work(
    tmp_path, monkeypatch
):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=ARTICLE_URL,
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
    )
    cache_manager.save_cache(
        platform="weixin",
        url=ARTICLE_URL,
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
        use_speaker_recognition=False,
        transcript_data="已缓存的公众号正文",
        transcript_type="capswriter",
        title="缓存文章",
        author="作者",
        description="微信公众号文章正文",
    )
    cache_manager.save_llm_result(
        "weixin",
        "r5aDx2ntV9E1QWM3oHe3kw",
        False,
        "calibrated",
        "校对正文",
    )
    cache_manager.save_llm_result(
        "weixin",
        "r5aDx2ntV9E1QWM3oHe3kw",
        False,
        "summary",
        "深度学习摘要",
    )
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(
        transcription, "_safe_update_progress", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        transcription, "get_notification_router", lambda: _FakeRouter()
    )
    fetch_article = MagicMock(side_effect=AssertionError("must not refetch"))
    monkeypatch.setattr(WeixinPostFetcher, "fetch_article", fetch_article)

    result = transcription.process_transcription(
        task["task_id"],
        ARTICLE_URL,
        include_comments=True,
        analysis_intent="deep_learning",
    )

    assert result["status"] == "success"
    assert result["data"]["cached"] is True
    assert queue.items == []
    fetch_article.assert_not_called()


def test_title_only_article_marks_process_task_failed(tmp_path, monkeypatch):
    cache_manager, queue = _install_cache_and_queue(monkeypatch, tmp_path)
    task = cache_manager.create_task(
        url=ARTICLE_URL,
        platform="weixin",
        media_id="r5aDx2ntV9E1QWM3oHe3kw",
    )
    monkeypatch.setattr(transcription, "_is_task_canceled", lambda task_id: False)
    monkeypatch.setattr(
        transcription, "_safe_update_progress", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        transcription, "get_notification_router", lambda: _FakeRouter()
    )
    monkeypatch.setattr(
        WeixinPostFetcher,
        "fetch_article",
        lambda self, url: WeixinArticlePayload(
            title="只有标题",
            author="作者",
            text="",
        ),
    )

    result = transcription.process_transcription(
        task["task_id"],
        ARTICLE_URL,
        analysis_intent="deep_learning",
    )

    assert result["status"] == "failed"
    assert "无法获取公众号文章正文" in result["message"]
    assert queue.items == []
    task_info = cache_manager.get_task_by_id(task["task_id"])
    assert task_info["status"] == TaskStatus.FAILED
