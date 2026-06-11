"""Unit tests for the post-insight orchestration service (no network/LLM)."""

import pytest

from src.video_transcript_api.api.services.post_insight import (
    PostInsightResult,
    generate_post_insight,
)
from src.video_transcript_api.comments.selector import CommentItem
from src.video_transcript_api.comments.twitter_post import TwitterPost


class _FakeAnalyzer:
    def __init__(self, out="## 正文核心主张\n要点"):
        self.out = out
        self.last = None

    def analyze(self, title, author, summary_text, comments):
        self.last = dict(
            title=title, author=author, summary_text=summary_text, comments=comments
        )
        return self.out


class _FakeFetcher:
    def __init__(self, post):
        self.post = post
        self.called_with = None

    def fetch(self, url, tweet_id, max_comments=80):
        self.called_with = (url, tweet_id)
        return self.post


_TWEET_URL = "https://x.com/naval/status/1002103360646823936"


def _post(comments):
    return TwitterPost(
        title="How to Get Rich",
        author="naval",
        thread_text="Seek wealth, not money or status.",
        comments=comments,
        main_tweet_id="1002103360646823936",
    )


def test_generates_result_with_comments():
    post = _post(
        [
            CommentItem(text="这条回复有具体的信息量和论据", like_count=99, platform_rank=0),
            CommentItem(text="另一条值得参考的高赞回复内容", like_count=50, platform_rank=1),
        ]
    )
    analyzer = _FakeAnalyzer()
    fetcher = _FakeFetcher(post)

    result = generate_post_insight(_TWEET_URL, analyzer=analyzer, post_fetcher=fetcher)

    assert isinstance(result, PostInsightResult)
    assert result.platform == "twitter"
    assert result.author == "naval"
    assert result.insight_markdown == "## 正文核心主张\n要点"
    assert result.fetched_comment_count == 2
    assert len(result.comment_samples) == 2
    # fetcher received the parsed tweet id
    assert fetcher.called_with[1] == "1002103360646823936"
    # analyzer received the author thread as content
    assert analyzer.last["summary_text"] == "Seek wealth, not money or status."


def test_generates_result_without_comments():
    analyzer = _FakeAnalyzer()
    result = generate_post_insight(
        _TWEET_URL, analyzer=analyzer, post_fetcher=_FakeFetcher(_post([]))
    )
    assert result.fetched_comment_count == 0
    assert result.comment_samples == []
    assert result.insight_markdown  # content-only analysis still produced
    assert analyzer.last["comments"] == []


def test_unsupported_platform_raises():
    # A non-twitter URL must be rejected before any fetch happens.
    with pytest.raises(ValueError):
        generate_post_insight(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ", analyzer=_FakeAnalyzer()
        )


def test_empty_insight_raises():
    with pytest.raises(ValueError):
        generate_post_insight(
            _TWEET_URL,
            analyzer=_FakeAnalyzer(out=""),
            post_fetcher=_FakeFetcher(_post([])),
        )
