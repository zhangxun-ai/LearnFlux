"""Unit tests for the platform-agnostic content-source fetcher (mock TikHub).

These lock the raw-JSON -> domain mapping contract. The sample response mirrors
TikHub xiaohongshu get_user_posted_notes; when a real token is plugged in, only
the field-path assumptions (kept defensive) may need a tweak — the mapping shape
is verified here without network.
"""
import pytest

from src.video_transcript_api.flywheel.models import MediaType
from src.video_transcript_api.flywheel.fetchers import (
    XiaohongshuUserFetcher, detect_platform, get_fetcher,
)


def _page(notes, cursor="", has_more=False):
    return {
        "code": 200,
        "data": {
            "user": {"user_id": "u1", "nickname": "@阿K", "avatar": "http://a",
                     "fans": "280000", "desc": "分享 AI 工具实测"},
            "notes": notes,
            "cursor": cursor,
            "has_more": has_more,
        },
    }


VIDEO_NOTE = {
    "note_id": "n1", "type": "video", "display_title": "别再花钱买AI课了",
    "cover": {"url": "http://cover1"}, "time": 1718000000,
    "interact_info": {"liked_count": "1200", "collected_count": "4200",
                      "comment_count": "890", "share_count": "30"},
}
IMAGE_NOTE = {
    "note_id": "n2", "type": "normal", "display_title": "3个AI工具",
    "cover": {"url": "http://cover2"}, "time": 1718100000,
    "interact_info": {"liked_count": "8600", "collected_count": "3000",
                      "comment_count": "360", "share_count": "12"},
}


@pytest.mark.unit
def test_detect_platform_xiaohongshu():
    assert detect_platform("https://www.xiaohongshu.com/user/profile/u1?xsec_token=x") == "xiaohongshu"
    assert detect_platform("http://xhslink.com/abc") == "xiaohongshu"


@pytest.mark.unit
def test_get_fetcher_returns_xhs_for_xiaohongshu():
    assert isinstance(get_fetcher("xiaohongshu"), XiaohongshuUserFetcher)


@pytest.mark.unit
def test_fetch_maps_blogger_fields():
    f = XiaohongshuUserFetcher(api_request=lambda ep, p: _page([VIDEO_NOTE]))
    r = f.fetch_blogger("https://www.xiaohongshu.com/user/profile/u1?xsec_token=x")
    assert r.blogger.platform == "xiaohongshu"
    assert r.blogger.platform_user_id == "u1"
    assert r.blogger.handle == "@阿K"
    assert r.blogger.follower_count == 280000
    assert r.blogger.bio == "分享 AI 工具实测"


@pytest.mark.unit
def test_fetch_maps_video_item():
    f = XiaohongshuUserFetcher(api_request=lambda ep, p: _page([VIDEO_NOTE]))
    item = f.fetch_blogger("https://www.xiaohongshu.com/user/profile/u1").items[0]
    assert item.platform_item_id == "n1"
    assert item.media_type is MediaType.VIDEO
    assert item.title == "别再花钱买AI课了"
    assert item.like_count == 1200
    assert item.collect_count == 4200
    assert item.comment_count == 890
    assert "n1" in item.original_url
    assert item.published_at is not None


@pytest.mark.unit
def test_media_type_detection_article():
    f = XiaohongshuUserFetcher(api_request=lambda ep, p: _page([IMAGE_NOTE]))
    item = f.fetch_blogger("https://www.xiaohongshu.com/user/profile/u1").items[0]
    assert item.media_type is MediaType.ARTICLE
    assert r_media_types(f) == (MediaType.ARTICLE,)


def r_media_types(f):
    return f.fetch_blogger("https://www.xiaohongshu.com/user/profile/u1").blogger.media_types


@pytest.mark.unit
def test_pagination_accumulates_until_max():
    pages = [_page([VIDEO_NOTE], cursor="c1", has_more=True),
             _page([IMAGE_NOTE], cursor="", has_more=False)]
    calls = {"i": 0}

    def fake(ep, params):
        page = pages[calls["i"]]
        calls["i"] += 1
        return page

    f = XiaohongshuUserFetcher(api_request=fake)
    r = f.fetch_blogger("https://www.xiaohongshu.com/user/profile/u1", max_items=10)
    assert [i.platform_item_id for i in r.items] == ["n1", "n2"]
    assert calls["i"] == 2  # followed has_more once


@pytest.mark.unit
def test_max_items_caps_results():
    f = XiaohongshuUserFetcher(api_request=lambda ep, p: _page([VIDEO_NOTE, IMAGE_NOTE]))
    r = f.fetch_blogger("https://www.xiaohongshu.com/user/profile/u1", max_items=1)
    assert len(r.items) == 1
