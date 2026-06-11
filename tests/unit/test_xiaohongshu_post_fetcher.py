"""Unit tests for XhsPostFetcher. Fixture mirrors real get_note_info_v7 shape
(data[0].note_list[0].title/.desc/.user) verified 2026-06-09. No network."""

import pytest

from src.video_transcript_api.comments.xiaohongshu_post import XhsPost, XhsPostFetcher


class _FakeDownloader:
    def __init__(self, response):
        self._response = response

    def make_api_request(self, endpoint, params=None):
        return self._response


NOTE_INFO_V7 = {
    "code": 0,
    "success": True,
    "data": [
        {
            "note_list": [
                {
                    "title": "分享我学习AI的方法",
                    "desc": "1. 不刷信息流产品，多看长内容。我获取信息的主要方式是 newsletter 和 YouTube。",
                    "user": {"nickname": "张咋啦"},
                }
            ]
        }
    ],
}


def _fetcher(response):
    return XhsPostFetcher(downloader_factory=lambda url: _FakeDownloader(response))


URL = "https://www.xiaohongshu.com/discovery/item/67c04c23000000000e006204"


def test_extracts_title_desc_author():
    post = _fetcher(NOTE_INFO_V7).fetch(URL, "67c04c23000000000e006204")
    assert isinstance(post, XhsPost)
    assert post.title == "分享我学习AI的方法"
    assert post.author == "张咋啦"
    assert "不刷信息流产品" in post.thread_text
    assert post.comments == []  # v1: content-only


def test_falls_back_to_recursive_find():
    # Unknown wrapper shape, but a note dict with title/desc exists somewhere.
    weird = {"code": 200, "data": {"x": {"y": {"title": "标题", "desc": "正文内容在这里"}}}}
    post = _fetcher(weird).fetch(URL, "abc")
    assert post.title == "标题"
    assert "正文内容在这里" in post.thread_text


def test_invalid_response_raises():
    with pytest.raises(ValueError):
        _fetcher("not-a-dict").fetch(URL, "abc")


def test_no_content_raises():
    with pytest.raises(ValueError):
        _fetcher({"code": 200, "data": [{"note_list": [{}]}]}).fetch(URL, "abc")
