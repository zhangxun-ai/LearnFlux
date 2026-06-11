"""Unit tests for WeixinPostFetcher. Fixtures mirror real TikHub wechat_mp shapes
verified 2026-06-09 (detail_json: data.title/.author/.content.article.full_text;
comment_list: data is a list of {content, nick_name, content_id}). No network."""

import pytest

from src.video_transcript_api.comments.weixin_post import WeixinPost, WeixinPostFetcher


class _RoutingDownloader:
    def __init__(self, by_endpoint):
        self._by = by_endpoint

    def make_api_request(self, endpoint, params=None):
        for key, resp in self._by.items():
            if key in endpoint:
                return resp
        raise AssertionError(f"unexpected endpoint: {endpoint}")


ARTICLE = {
    "data": {
        "title": "我在Claude Code和Codex做了实测",
        "author": "老金带你玩AI",
        "content": {
            "article": {
                "full_text": "老粉都知道，Claude Code、Cursor、Codex 这些工具我都用过……跨五个文件的复杂任务它就会出问题。",
                "summary": "实测总结",
            }
        },
    }
}
COMMENTS = {
    "data": [
        {"content": "挺好的，不是在hook中强注入呀", "nick_name": "云飞哥", "content_id": "111", "like_num": 8},
        {"content": "VIBECODING用的skill吗？", "nick_name": "读者B", "content_id": "112"},
    ]
}
URL = "https://mp.weixin.qq.com/s/r5aDx2ntV9E1QWM3oHe3kw"


def _fetcher():
    return WeixinPostFetcher(downloader_factory=lambda url: _RoutingDownloader({
        "fetch_mp_article_detail_json": ARTICLE,
        "fetch_mp_article_comment_list": COMMENTS,
    }))


def test_extracts_article_and_comments():
    post = _fetcher().fetch(URL)
    assert isinstance(post, WeixinPost)
    assert post.title.startswith("我在Claude Code")
    assert post.author == "老金带你玩AI"
    assert "跨五个文件的复杂任务" in post.thread_text
    assert len(post.comments) == 2
    assert post.comments[0].text == "挺好的，不是在hook中强注入呀"
    assert post.comments[0].user_nickname == "云飞哥"
    assert post.comments[0].like_count == 8


def test_falls_back_to_sections_when_no_full_text():
    article = {"data": {"title": "T", "author": "A", "content": {"article": {
        "sections": [{"title": "小标题", "text": "段落正文内容"}]
    }}}}
    f = WeixinPostFetcher(downloader_factory=lambda url: _RoutingDownloader({
        "fetch_mp_article_detail_json": article,
        "fetch_mp_article_comment_list": {"data": []},
    }))
    post = f.fetch(URL)
    assert "段落正文内容" in post.thread_text
    assert post.comments == []


def test_invalid_response_raises():
    f = WeixinPostFetcher(downloader_factory=lambda url: _RoutingDownloader({
        "fetch_mp_article_detail_json": "not-a-dict",
    }))
    with pytest.raises(ValueError):
        f.fetch(URL)
