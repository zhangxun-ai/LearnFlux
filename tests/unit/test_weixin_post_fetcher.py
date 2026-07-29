"""Unit tests for the versioned WeChat Official Account post fetcher."""

import pytest

from src.video_transcript_api.comments.weixin_post import WeixinPost, WeixinPostFetcher


class _RoutingDownloader:
    def __init__(self, by_endpoint):
        self._by = by_endpoint
        self.calls = []

    def post_api_request(self, endpoint, payload, *, min_timeout=None):
        self.calls.append((endpoint, payload, min_timeout))
        for key, resp in self._by.items():
            if key in endpoint:
                return resp
        raise AssertionError(f"unexpected endpoint: {endpoint}")


ARTICLE_V2 = {
    "code": 200,
    "data": {
        "content": {
            "title": "我在Claude Code和Codex做了实测",
            "author": "",
            "nick_name": "AI 实验室",
            "content_text": (
                "老粉都知道，Claude Code、Cursor、Codex 这些工具我都用过……"
                "跨五个文件的复杂任务它就会出问题。"
            ),
        },
    },
}
COMMENTS_V2 = {
    "code": 200,
    "data": {
        "comments": [
            {
                "content": "挺好的，不是在hook中强注入呀",
                "nick_name": "云飞哥",
                "content_id": "111",
                "like_num": 8,
                "reply_total": 2,
            },
            {
                "content": "VIBECODING用的skill吗？",
                "nick_name": "读者B",
                "content_id": "112",
                "like_num": 3,
                "reply_new": {"reply_total_cnt": 4},
            },
        ],
    },
}
URL = "https://mp.weixin.qq.com/s/r5aDx2ntV9E1QWM3oHe3kw"


def _fetcher():
    downloader = _RoutingDownloader(
        {
            "fetch_article_detail": ARTICLE_V2,
            "fetch_article_comments": COMMENTS_V2,
        }
    )
    return (
        WeixinPostFetcher(
            downloader_factory=lambda url: downloader,
            config={"tikhub": {"wechat_mp_api_version": "v2"}},
        ),
        downloader,
    )


def test_extracts_article_and_comments():
    fetcher, downloader = _fetcher()
    post = fetcher.fetch(URL)
    assert isinstance(post, WeixinPost)
    assert post.title.startswith("我在Claude Code")
    assert post.author == "AI 实验室"
    assert "跨五个文件的复杂任务" in post.thread_text
    assert len(post.comments) == 2
    assert post.comments[0].text == "挺好的，不是在hook中强注入呀"
    assert post.comments[0].user_nickname == "云飞哥"
    assert post.comments[0].like_count == 8
    assert post.comments[0].reply_count == 2
    assert post.comments[1].reply_count == 4
    assert downloader.calls == [
        (
            "/api/v1/wechat_mp/v2/fetch_article_detail",
            {"url": URL, "raw": False},
            30,
        ),
        (
            "/api/v1/wechat_mp/v2/fetch_article_comments",
            {"url": URL, "buffer": "", "raw": False},
            30,
        ),
    ]


def test_fetch_article_only_does_not_request_comments():
    fetcher, downloader = _fetcher()

    article = fetcher.fetch_article(URL)

    assert article.title.startswith("我在Claude Code")
    assert article.author == "AI 实验室"
    assert "跨五个文件的复杂任务" in article.text
    assert downloader.calls == [
        (
            "/api/v1/wechat_mp/v2/fetch_article_detail",
            {"url": URL, "raw": False},
            30,
        )
    ]


def test_allows_title_only_v2_article():
    article = {
        "code": 200,
        "data": {
            "content": {
                "title": "T",
                "nick_name": "A",
                "content_text": "",
            }
        },
    }
    fetcher = WeixinPostFetcher(
        downloader_factory=lambda url: _RoutingDownloader(
            {
                "fetch_article_detail": article,
                "fetch_article_comments": {
                    "code": 200,
                    "data": {"comments": []},
                },
            }
        ),
    )
    post = fetcher.fetch(URL)
    assert post.title == "T"
    assert post.thread_text == ""
    assert post.comments == []


def test_invalid_response_raises():
    fetcher = WeixinPostFetcher(
        downloader_factory=lambda url: _RoutingDownloader(
            {"fetch_article_detail": "not-a-dict"}
        )
    )
    with pytest.raises(ValueError):
        fetcher.fetch(URL)


def test_v2_error_response_raises():
    fetcher = WeixinPostFetcher(
        downloader_factory=lambda url: _RoutingDownloader(
            {
                "fetch_article_detail": {
                    "code": 500,
                    "message": "upstream error",
                }
            }
        )
    )

    with pytest.raises(ValueError, match="upstream error"):
        fetcher.fetch(URL)


def test_defaults_to_v2_adapter():
    fetcher, downloader = _fetcher()
    fetcher.config = {"tikhub": {}}

    fetcher.fetch(URL)

    assert downloader.calls[0][0] == "/api/v1/wechat_mp/v2/fetch_article_detail"


def test_unknown_adapter_version_fails_without_request():
    downloader = _RoutingDownloader({})
    factory_calls = []
    fetcher = WeixinPostFetcher(
        downloader_factory=lambda url: factory_calls.append(url) or downloader,
        config={"tikhub": {"wechat_mp_api_version": "v9"}},
    )

    with pytest.raises(ValueError, match="Unsupported WeChat MP API version: v9"):
        fetcher.fetch(URL)

    assert downloader.calls == []
    assert factory_calls == []
