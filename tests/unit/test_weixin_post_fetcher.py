"""WeChat article acquisition and deep-learning routing, with offline TikHub responses."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.video_transcript_api.comments.weixin_post import WeixinPost, WeixinPostFetcher


class _RoutingClient:
    def __init__(self, by_endpoint):
        self._by = by_endpoint
        self.calls = []

    def post(self, endpoint, payload, **kwargs):
        self.calls.append((endpoint, payload))
        return self._by[endpoint]


DETAIL = "/api/v1/wechat_mp/v2/fetch_article_detail_h5"
COMMENT_LIST = "/api/v1/wechat_mp/v2/fetch_article_comments"
ARTICLE = {
    "code": 200,
    "data": {
        "content": {
            "title": "Article title",
            "author": "Article author",
            "content_text": "Opening paragraph.\n\nClosing paragraph.",
            "comment_id": 1234567890123456789,
            "_content_type": "article",
        },
    }
}
COMMENTS = {
    "data": {"elected_comment": [
        {"content": "First comment", "nick_name": "First reader", "content_id": "111", "like_num": 8},
        {"content": "Second comment", "nick_name": "Second reader", "content_id": "112"},
    ]},
}
MEDIA_ID = "zoS7GlReWPhfCjENGxXCdg"
URL = f"https://mp.weixin.qq.com/s/{MEDIA_ID}?scene=1&click_id=2039325459"


def test_extracts_article_and_comments():
    client = _RoutingClient({DETAIL: ARTICLE, COMMENT_LIST: COMMENTS})
    post = WeixinPostFetcher(client).fetch(URL)
    assert isinstance(post, WeixinPost)
    assert post.title == "Article title"
    assert post.author == "Article author"
    assert post.thread_text == "Opening paragraph.\n\nClosing paragraph."
    assert len(post.comments) == 2
    assert post.comments[0].text == "First comment"
    assert post.comments[0].user_nickname == "First reader"
    assert post.comments[0].like_count == 8
    assert client.calls == [(DETAIL, {"url": URL, "raw": False}),
                            (COMMENT_LIST, {"url": URL, "comment_id": "1234567890123456789"})]


@pytest.mark.parametrize("response", ["not-a-dict", {"data": None}, {"data": {"content": {"title": "Title only"}}}])
def test_invalid_or_empty_response_raises(response):
    fetcher = WeixinPostFetcher(_RoutingClient({DETAIL: response}))
    with pytest.raises(ValueError, match="公众号"):
        fetcher.fetch(URL)


def test_article_identity_distinguishes_long_links_from_the_same_publisher():
    from src.video_transcript_api.utils.url_parser import URLParser

    parser = URLParser()
    long_url = "https://mp.weixin.qq.com/s?__biz=publisher%3D%3D&mid=123&idx=1&sn=signature"
    article = parser.parse(long_url)
    assert article.platform == "weixin"
    assert parser.parse(long_url + "&scene=1").video_id == article.video_id
    assert parser.parse(long_url.replace("idx=1", "idx=2")).video_id != article.video_id
    assert parser.parse(long_url.replace("mid=123", "mid=124")).video_id != article.video_id
    assert parser.parse("https://weixin.qq.com/sph/AUqdQVIvFa").platform != "weixin"
    assert parser.parse("https://other.example/mp.weixin.qq.com/s/id").platform != "weixin"


def test_article_uses_deep_learning_without_media_download_or_comments(monkeypatch, tmp_path):
    from src.video_transcript_api.api.services import transcription
    from src.video_transcript_api.cache.cache_manager import CacheManager
    from src.video_transcript_api.comments import weixin_post

    client = _RoutingClient({DETAIL: ARTICLE})
    monkeypatch.setattr(weixin_post, "TikHubClient", lambda _: client)
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr(transcription, "cache_manager", cache)
    queue = Mock()
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "get_notification_router", Mock())
    monkeypatch.setattr(transcription, "get_config", lambda: {
        "storage": {"source_files_dir": str(tmp_path / "sources")},
    })
    downloader = Mock(side_effect=AssertionError("Article entered the media path"))
    monkeypatch.setattr(transcription, "create_downloader", downloader)
    task = cache.create_task(url=URL, platform="weixin", media_id=MEDIA_ID)

    result = transcription.process_transcription(
        task["task_id"], URL, transcription_strategy="cloud", preserve_source_file=True,
    )

    assert result["status"] == "success", result
    assert result["data"]["media_type"] == "article"
    source = ARTICLE["data"]["content"]["content_text"]
    assert cache.get_cache("weixin", MEDIA_ID, False)["transcript_data"] == source
    saved_task = cache.get_task_by_id(task["task_id"])
    assert saved_task["status"] == "calibrating"
    assert source in Path(saved_task["source_file_path"]).read_text()
    queue.put.assert_called_once()
    assert queue.put.call_args.args[0]["transcript"] == source
    assert client.calls == [(DETAIL, {"url": URL, "raw": False})]
    downloader.assert_not_called()
