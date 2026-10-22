"""Regression cases for Xiaohongshu login-wrapped share redirects."""

from urllib.parse import quote
from unittest.mock import patch

import pytest

from video_transcript_api.downloaders.xiaohongshu import XiaohongshuDownloader
from video_transcript_api.flywheel.text_acquisition import normalize_note_url
from video_transcript_api.utils.url_parser import URLParser


NOTE_ID = "6acdddd50000000018010acb"
CONTENT = f"https://www.xiaohongshu.com/discovery/item/{NOTE_ID}?xsec_token=test%2Btoken%3D&xsec_source=app_share&type=video"
LOGIN = "https://www.xiaohongshu.com/login?redirectPath=" + quote(CONTENT, safe="")


def test_url_parser_preserves_identity_and_signature_through_login_redirect():
    parser = URLParser()
    with patch.object(parser, "_resolve_short_url", return_value=LOGIN):
        parsed = parser.parse("https://xhslink.cn/o/SwGMwr6MCI")
    assert parsed.platform == "xiaohongshu"
    assert parsed.video_id == NOTE_ID
    assert parsed.normalized_url == CONTENT


def test_downloader_unwraps_before_extracting_id():
    with patch("video_transcript_api.downloaders.base.load_config", return_value={"tikhub": {}}):
        downloader = XiaohongshuDownloader()
    with patch.object(downloader, "resolve_short_url", return_value=LOGIN):
        assert downloader.extract_note_id("https://xhslink.cn/o/SwGMwr6MCI") == NOTE_ID


def test_article_and_video_classification_get_same_unwrapped_url():
    assert normalize_note_url(LOGIN) == CONTENT


@pytest.mark.parametrize("target", [CONTENT, quote(CONTENT, safe=""), quote(quote(CONTENT, safe=""), safe="")])
def test_nested_encoding_keeps_the_signed_query_intact(target):
    from video_transcript_api.utils.xiaohongshu_url import normalize_xiaohongshu_url
    from urllib.parse import parse_qs, urlsplit
    wrapped = "https://www.xiaohongshu.com/login?redirectPath=" + quote(target, safe="")
    result = normalize_xiaohongshu_url(wrapped)
    assert result == CONTENT
    assert parse_qs(urlsplit(result).query)["xsec_token"] == ["test+token="]


def test_nested_login_and_relative_note_targets():
    from video_transcript_api.utils.xiaohongshu_url import normalize_xiaohongshu_url
    assert normalize_xiaohongshu_url("https://www.xiaohongshu.com/login?redirectPath=" + quote(LOGIN, safe="")) == CONTENT
    relative = CONTENT.replace("https://www.xiaohongshu.com", "")
    assert normalize_xiaohongshu_url("https://www.xiaohongshu.com/login?redirectPath=" + quote(relative, safe="")) == CONTENT


@pytest.mark.parametrize("target", [
    "https://evil.example/explore/" + NOTE_ID,
    "https://xiaohongshu.com.evil.example/explore/" + NOTE_ID,
    "https://www.xiaohongshu.com@evil.example/explore/" + NOTE_ID,
    "http://127.0.0.1/explore/" + NOTE_ID,
    "javascript:alert(1)",
])
def test_untrusted_login_targets_are_never_promoted(target):
    from video_transcript_api.utils.xiaohongshu_url import normalize_xiaohongshu_url, xiaohongshu_note_id
    wrapped = "https://www.xiaohongshu.com/login?redirectPath=" + quote(target, safe="")
    assert normalize_xiaohongshu_url(wrapped) == wrapped
    assert xiaohongshu_note_id(wrapped) == ""


def test_note_ids_in_arbitrary_query_strings_are_not_accepted():
    from video_transcript_api.utils.xiaohongshu_url import xiaohongshu_note_id
    assert xiaohongshu_note_id("https://evil.example/path/" + NOTE_ID) == ""
    assert xiaohongshu_note_id("https://www.xiaohongshu.com/login?token=" + NOTE_ID) == ""


def test_short_link_is_resolved_once_per_downloader():
    with patch("video_transcript_api.downloaders.base.load_config", return_value={"tikhub": {}}):
        downloader = XiaohongshuDownloader()
    with patch.object(downloader, "resolve_short_url", return_value=LOGIN) as resolve:
        for _ in range(3):
            assert downloader.extract_note_id("https://xhslink.cn/o/SwGMwr6MCI") == NOTE_ID
        assert resolve.call_count == 1


def test_post_endpoint_candidates_keep_unwrapped_share_and_signature():
    from video_transcript_api.comments.xiaohongshu_post import XhsPostFetcher
    candidates = XhsPostFetcher._endpoint_candidates(LOGIN, NOTE_ID)
    assert candidates[0] == ("/api/v1/xiaohongshu/app_v2/get_image_note_detail", {"note_id": NOTE_ID})
    assert candidates[1][1] == {"note_id": NOTE_ID, "xsec_token": "test+token="}


@pytest.mark.parametrize("url", [
    "https://evil.example/path?target=https://www.xiaohongshu.com/explore/" + NOTE_ID,
    "https://xiaohongshu.com.evil.example/explore/" + NOTE_ID,
    "https://www.xiaohongshu.com/login?target=/explore/" + NOTE_ID,
])
def test_parser_does_not_reintroduce_untrusted_note_id_after_normalization(url):
    assert URLParser()._extract_platform_and_id(url)[0] == "generic"
