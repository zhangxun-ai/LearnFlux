"""Unit tests for the comment-free X/Twitter source adapter."""

from __future__ import annotations

from typing import Any

import pytest

from video_transcript_api.downloaders.twitter import TwitterDownloader


X_VIDEO_URL = (
    "https://x.com/leoxbtt/status/2082108948505674112/video/1?s=46"
)


class _Requester:
    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((endpoint, params))
        return self.response


@pytest.mark.parametrize(
    "url",
    [
        X_VIDEO_URL,
        "https://www.x.com/user/status/123",
        "https://twitter.com/user/status/123",
        "https://www.twitter.com/user/status/123/video/2",
        "https://mobile.twitter.com/user/status/123",
    ],
)
def test_canonical_status_urls_are_supported(url):
    assert TwitterDownloader.is_canonical_status_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x.com/user/status/123",
        "https://x.com.evil.example/user/status/123",
        "https://api.x.com/user/status/123",
        "https://x.com@evil.example/user/status/123",
        "https://x.com/user/status/not-a-number",
        "https://x.com/user/status/123/photo/1",
        "javascript:https://x.com/user/status/123",
    ],
)
def test_noncanonical_or_lookalike_urls_are_rejected(url):
    assert not TwitterDownloader.is_canonical_status_url(url)


def test_extracts_id_and_reuses_one_detail_request_for_metadata_and_download():
    requester = _Requester(
        {
            "code": 200,
            "data": {
                "id": "2082108948505674112",
                "display_text": "A useful video about agent systems.",
                "author": {"screen_name": "leoxbtt"},
                "media_playable_url": "https://video.twimg.com/ext_tw_video/clip.mp4",
            },
        }
    )
    downloader = TwitterDownloader(request_func=requester)

    metadata = downloader.get_metadata(X_VIDEO_URL)
    download = downloader.get_download_info(X_VIDEO_URL)

    assert downloader.extract_video_id(X_VIDEO_URL) == "2082108948505674112"
    assert metadata.platform == "twitter"
    assert metadata.author == "leoxbtt"
    assert metadata.description == "A useful video about agent systems."
    assert metadata.extra["content_kind"] == "video"
    assert download.download_url == "https://video.twimg.com/ext_tw_video/clip.mp4"
    assert download.file_ext == ".mp4"
    assert len(requester.calls) == 1
    assert requester.calls[0][0].endswith("/fetch_tweet_detail")
    assert requester.calls[0][1] == {"tweet_id": "2082108948505674112"}
    assert all("fetch_post_comments" not in call[0] for call in requester.calls)


def test_article_body_is_exposed_as_text_when_there_is_no_video():
    requester = _Requester(
        {
            "code": 200,
            "data": {
                "id": "2046082879109959807",
                "text": "https://t.co/example",
                "author": {"screen_name": "writer"},
                "article": {
                    "title": "Agent architecture notes",
                    "full_text": "First principle.\n\nSecond principle.",
                },
            },
        }
    )
    downloader = TwitterDownloader(request_func=requester)

    metadata = downloader.get_metadata(
        "https://x.com/writer/status/2046082879109959807"
    )
    download = downloader.get_download_info(
        "https://x.com/writer/status/2046082879109959807"
    )

    assert metadata.title == "Agent architecture notes"
    assert metadata.description == "First principle.\n\nSecond principle."
    assert metadata.extra["content_kind"] == "social_text"
    assert download.download_url is None
    assert len(requester.calls) == 1


@pytest.mark.parametrize(
    ("media", "expected"),
    [
        (
            [
                {
                    "type": "video",
                    "video_info": {
                        "variants": [
                            {
                                "content_type": "application/x-mpegURL",
                                "url": "https://video.twimg.com/playlist.m3u8",
                            },
                            {
                                "content_type": "video/mp4",
                                "bitrate": 256000,
                                "url": "https://video.twimg.com/low.mp4",
                            },
                            {
                                "content_type": "video/mp4",
                                "bitrate": 2176000,
                                "url": "https://video.twimg.com/high.mp4",
                            },
                        ]
                    },
                }
            ],
            "https://video.twimg.com/high.mp4",
        ),
        (
            [{"type": "video", "url": "https://video.twimg.com/direct.mp4"}],
            "https://video.twimg.com/direct.mp4",
        ),
        (
            [{"type": "photo", "url": "https://pbs.twimg.com/photo.jpg"}],
            None,
        ),
        (
            [{"url": "https://cdn.example.com/ambiguous"}],
            None,
        ),
    ],
)
def test_media_candidates_accept_only_explicit_video(media, expected):
    requester = _Requester(
        {
            "code": 200,
            "data": {
                "id": "123",
                "text": "media",
                "author": {"screen_name": "author"},
                "media": media,
            },
        }
    )
    downloader = TwitterDownloader(request_func=requester)

    info = downloader.get_download_info("https://x.com/author/status/123")

    assert info.download_url == expected


def test_invalid_or_empty_detail_fails_without_comment_fallback():
    requester = _Requester({"code": 200, "data": {"id": "123"}})
    downloader = TwitterDownloader(request_func=requester)

    metadata = downloader.get_metadata("https://x.com/author/status/123")
    info = downloader.get_download_info("https://x.com/author/status/123")

    assert metadata.description == ""
    assert metadata.extra["content_kind"] == "empty"
    assert info.download_url is None
    assert len(requester.calls) == 1
