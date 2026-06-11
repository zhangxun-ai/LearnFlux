"""Unit tests for TikHub comment fetcher.

All console output must be in English only.
"""

from video_transcript_api.comments.fetcher import TikHubCommentFetcher


class FakeDownloader:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def make_api_request(self, endpoint, params=None):
        self.calls.append((endpoint, params or {}))
        return self.response


def test_fetch_douyin_comments_normalizes_hot_window():
    fake = FakeDownloader(
        {
            "code": 200,
            "data": {
                "comments": [
                    {
                        "cid": "c1",
                        "text": "这个工具实际使用门槛高吗？",
                        "digg_count": 120,
                        "reply_comment_total": 8,
                        "user": {"nickname": "alice"},
                    },
                    {
                        "cid": "c2",
                        "text": "种草了，想知道价格",
                        "digg_count": 80,
                        "reply_comment_total": 2,
                        "user": {"nickname": "bob"},
                    },
                ]
            },
        }
    )
    fetcher = TikHubCommentFetcher(downloader_factory=lambda url: fake)

    comments = fetcher.fetch_hot_comments(
        "https://www.douyin.com/video/123",
        platform="douyin",
        media_id="123",
        limit=2,
    )

    assert fake.calls[0][0] == "/api/v1/douyin/web/fetch_video_comments"
    assert fake.calls[0][1]["aweme_id"] == "123"
    assert fake.calls[0][1]["count"] == 2
    assert [item.text for item in comments] == [
        "这个工具实际使用门槛高吗？",
        "种草了，想知道价格",
    ]
    assert comments[0].like_count == 120
    assert comments[0].reply_count == 8
    assert comments[0].user_nickname == "alice"


def test_fetch_youtube_comments_uses_top_sort_and_common_fields():
    fake = FakeDownloader(
        {
            "code": 200,
            "data": {
                "comments": [
                    {
                        "comment_id": "yt1",
                        "content": "The export workflow is the most useful part.",
                        "like_count": 55,
                        "reply_count": 4,
                        "author": "carol",
                    }
                ]
            },
        }
    )
    fetcher = TikHubCommentFetcher(downloader_factory=lambda url: fake)

    comments = fetcher.fetch_hot_comments(
        "https://www.youtube.com/watch?v=abc",
        platform="youtube",
        media_id="abc",
        limit=50,
    )

    assert fake.calls[0][0] == "/api/v1/youtube/web/get_video_comments"
    assert fake.calls[0][1]["video_id"] == "abc"
    assert fake.calls[0][1]["sort_by"] == "top"
    assert comments[0].text == "The export workflow is the most useful part."
    assert comments[0].like_count == 55
