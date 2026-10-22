"""Regression coverage for current App V2 contracts and upstream failures."""
from unittest.mock import Mock, patch

import pytest

from video_transcript_api.downloaders.xiaohongshu import XiaohongshuDownloader
from video_transcript_api.flywheel.text_acquisition import fetch_note_detail, _media_type
from video_transcript_api.flywheel.models import MediaType
from video_transcript_api.comments.xiaohongshu_post import XhsPostFetcher
from video_transcript_api.utils.xiaohongshu_api import response_data, APP_VIDEO_DETAIL, APP_NOTE_DETAIL

NOTE_ID = "6acdddd50000000018010acb"
URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}"


def envelope(note):
    return {"code": 200, "data": {"code": 0, "success": True, "data": [note]}}


def downloader():
    with patch("video_transcript_api.downloaders.base.load_config", return_value={"tikhub": {}}):
        return XiaohongshuDownloader()


def test_app_v2_video_works_without_web_signature():
    dl = downloader()
    note = {"id": NOTE_ID, "type": "video", "title": "Original video", "desc": "Caption",
            "user": {"nickname": "Author"}, "video_info_v2": {"media": {"stream": {
                "h264": [{"master_url": "https://cdn.example/video.mp4"}],
                "h265": [{"master_url": "https://cdn.example/backup.mp4"}],
            }}}}
    with patch.object(dl, "make_api_request", return_value=envelope(note)) as request:
        result = dl.get_video_info(URL)
    request.assert_called_once_with(APP_VIDEO_DETAIL, {"note_id": NOTE_ID})
    assert result["video_title"] == "Original video"
    assert result["author"] == "Author"
    assert result["download_url"] == "https://cdn.example/video.mp4"


def test_unsigned_failure_does_not_call_web_endpoint_without_required_token():
    dl = downloader()
    with patch.object(dl, "make_api_request", side_effect=ValueError("Upstream unavailable")) as request:
        with pytest.raises(ValueError, match="All xiaohongshu API endpoints failed"):
            dl.get_video_info(URL)
    request.assert_called_once_with(APP_VIDEO_DETAIL, {"note_id": NOTE_ID})


@pytest.mark.parametrize("note_type,expected", [("video", MediaType.VIDEO), ("normal", MediaType.ARTICLE)])
def test_app_v2_classification_with_cover_only(note_type, expected):
    calls = []
    def request(endpoint, params):
        calls.append((endpoint, params))
        return envelope({"title": "Title", "desc": "Full caption", "type": note_type,
                         "images_list": [{"url": "https://cdn.example/cover.jpg"}]})
    result = fetch_note_detail(URL, api_request=request)
    assert result.media_type is expected
    assert result.body_text == "Full caption"
    assert calls == [(APP_NOTE_DETAIL, {"note_id": NOTE_ID})]


def test_video_stream_is_not_misclassified_when_type_missing():
    assert _media_type({"video_info_v2": {"media": {"stream": {}}}}) is MediaType.VIDEO


@pytest.mark.parametrize("response", [
    {"code": 400, "data": {"title": "Error title"}},
    {"code": 200, "data": {"success": False, "code": -1, "data": {"title": "Error title"}}},
    {"code": 200, "data": {"success": False, "data": {"title": "Error title"}}},
])
def test_http_200_does_not_turn_upstream_errors_into_content(response):
    with pytest.raises(ValueError):
        response_data(response)
    with pytest.raises(ValueError):
        XiaohongshuDownloader._validate_response(response, "test")
    with pytest.raises(ValueError):
        XhsPostFetcher._data(response)


def test_error_envelope_falls_back_instead_of_saving_error_text_as_article():
    calls = []
    def request(endpoint, params):
        calls.append(endpoint)
        if endpoint == APP_NOTE_DETAIL:
            return {"code": 200, "data": {"code": -1, "success": False,
                                           "data": {"title": "Error title", "desc": "Service error"}}}
        return {"code": 200, "data": {"title": "Real article", "desc": "Complete body", "type": "normal"}}
    result = fetch_note_detail(URL + "?xsec_token=test", api_request=request)
    assert result.title == "Real article"
    assert len(calls) == 2


def test_invalid_note_url_never_reaches_paid_api():
    request = Mock()
    with pytest.raises(ValueError, match="note_id"):
        fetch_note_detail("https://www.xiaohongshu.com/login?token=arbitrary", api_request=request)
    request.assert_not_called()
