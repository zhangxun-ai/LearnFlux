"""Unit tests for Douyin downloader media and metadata selection."""

from __future__ import annotations

from video_transcript_api.downloaders.douyin import DouyinDownloader


VIDEO_URL = "https://www.douyin.com/video/7663234068816907554"
MUSIC_URL = "https://cdn.example.com/background.m4a"
VIDEO_PLAY_URL = "https://cdn.example.com/original-video.mp4"


def _video_response(desc: str) -> dict:
    return {
        "code": 200,
        "data": {
            "aweme_detail": {
                "desc": desc,
                "author": {"nickname": "思维共生体"},
                "music": {"play_url": {"uri": MUSIC_URL, "url_list": [MUSIC_URL]}},
                "video": {
                    "play_addr": {"url_list": [VIDEO_PLAY_URL]},
                    "play_addr_h264": {"url_list": []},
                    "download_addr": {"url_list": []},
                },
            }
        },
    }


def _downloader(monkeypatch, tmp_path: object, response: dict) -> DouyinDownloader:
    downloader = DouyinDownloader()
    monkeypatch.setattr(downloader, "make_api_request", lambda *args: response)
    monkeypatch.setattr(downloader, "_first_reachable_url", lambda urls: urls[0])
    monkeypatch.setattr(
        "video_transcript_api.downloaders.douyin.DEBUG_DIR", str(tmp_path)
    )
    return downloader


def test_get_video_info_prefers_video_audio_over_attached_music(monkeypatch, tmp_path):
    """The transcribed source must be the video stream, not its music asset."""
    downloader = _downloader(monkeypatch, tmp_path, _video_response("A video"))

    info = downloader.get_video_info(VIDEO_URL)

    assert info["download_url"] == VIDEO_PLAY_URL
    assert info["filename"].endswith(".mp4")


def test_get_video_info_removes_hashtags_from_title(monkeypatch, tmp_path):
    """Douyin hashtags belong to the description, not the displayed title."""
    downloader = _downloader(
        monkeypatch,
        tmp_path,
        _video_response("钱要找对人，人要对得起钱 #交易员 #干货分享 #个人观点仅供参考"),
    )

    info = downloader.get_video_info(VIDEO_URL)

    assert info["video_title"] == "钱要找对人，人要对得起钱"
    assert "#交易员" in info["description"]
