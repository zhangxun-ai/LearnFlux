"""Unit tests for TwitterPostFetcher.

Fixtures mirror the REAL TikHub /api/v1/twitter/web/fetch_post_comments shape
verified on 2026-06-09 (main tweet at data top-level; data.thread is the
conversation chain; author self-thread items share the root author's screen_name).
No network: a fake downloader returns canned responses.
"""

import pytest

from src.video_transcript_api.comments.twitter_post import (
    TwitterPost,
    TwitterPostFetcher,
)


class _FakeDownloader:
    def __init__(self, response):
        self._response = response

    def make_api_request(self, endpoint, params=None):
        return self._response


def _fetcher(response):
    return TwitterPostFetcher(downloader_factory=lambda url: _FakeDownloader(response))


# Author self-thread (Naval "How to Get Rich"): every thread item is the author.
SELF_THREAD_RESPONSE = {
    "code": 200,
    "data": {
        "id": "1002103360646823936",
        "text": "How to Get Rich (without getting lucky):",
        "display_text": "How to Get Rich (without getting lucky):",
        "likes": 500000,
        "replies": 9999,
        "author": {"screen_name": "naval", "name": "Naval"},
        "conversation_id": "1002103360646823936",
        "thread": [
            {
                "id": "2",
                "text": "Seek wealth, not money or status.",
                "display_text": "Seek wealth, not money or status.",
                "likes": 1000,
                "replies": 5,
                "author": {"screen_name": "naval", "name": "Naval"},
            },
            {
                "id": "3",
                "text": "Understand that ethical wealth creation is possible.",
                "display_text": "Understand that ethical wealth creation is possible.",
                "likes": 800,
                "replies": 3,
                "author": {"screen_name": "naval", "name": "Naval"},
            },
        ],
        "cursor": "ABC",
    },
}

# Standalone tweet (jack id=20): thread items are OTHER users' replies.
STANDALONE_RESPONSE = {
    "code": 200,
    "data": {
        "id": "20",
        "text": "just setting up my twttr",
        "display_text": "just setting up my twttr",
        "likes": 309695,
        "replies": 17925,
        "author": {"screen_name": "jack", "name": "jack"},
        "thread": [
            {
                "id": "100",
                "text": "@jack congrats on the first tweet",
                "display_text": "congrats on the first tweet",
                "likes": 321,
                "replies": 4,
                "author": {"screen_name": "carol", "name": "Carol"},
            },
            {
                "id": "101",
                "text": "@jack historic moment",
                "display_text": "historic moment",
                "likes": 50,
                "replies": 0,
                "author": {"screen_name": "dave", "name": "Dave"},
            },
        ],
    },
}


class TestTwitterPostFetcher:
    def test_self_thread_becomes_content_no_replies(self):
        post = _fetcher(SELF_THREAD_RESPONSE).fetch(
            "https://x.com/naval/status/1002103360646823936",
            "1002103360646823936",
        )
        assert isinstance(post, TwitterPost)
        assert post.author == "naval"
        # root + both author continuation tweets are merged into the content
        assert "How to Get Rich" in post.thread_text
        assert "Seek wealth" in post.thread_text
        assert "ethical wealth creation" in post.thread_text
        # all thread items were authored by the root -> no third-party replies
        assert post.comments == []
        assert post.title  # non-empty

    def test_standalone_tweet_keeps_replies_as_comments(self):
        post = _fetcher(STANDALONE_RESPONSE).fetch(
            "https://twitter.com/jack/status/20", "20"
        )
        assert post.author == "jack"
        # no author self-thread -> content is just the root tweet
        assert post.thread_text == "just setting up my twttr"
        assert len(post.comments) == 2

    def test_reply_field_mapping(self):
        post = _fetcher(STANDALONE_RESPONSE).fetch(
            "https://twitter.com/jack/status/20", "20"
        )
        first = post.comments[0]
        # display_text preferred over text (strips leading @mention)
        assert first.text == "congrats on the first tweet"
        assert first.like_count == 321
        assert first.reply_count == 4
        assert first.user_nickname == "carol"
        assert first.comment_id == "100"
        assert first.platform_rank == 0

    def test_non_success_code_raises(self):
        with pytest.raises(ValueError):
            _fetcher({"code": 400, "message": "bad request"}).fetch(
                "https://x.com/a/status/1", "1"
            )

    def test_invalid_response_raises(self):
        with pytest.raises(ValueError):
            _fetcher("not-a-dict").fetch("https://x.com/a/status/1", "1")


class _RoutingDownloader:
    """Returns different responses per endpoint (post_comments vs tweet_detail)."""

    def __init__(self, by_endpoint):
        self._by_endpoint = by_endpoint
        self.calls = []

    def make_api_request(self, endpoint, params=None):
        self.calls.append(endpoint)
        for key, resp in self._by_endpoint.items():
            if key in endpoint:
                return resp
        raise AssertionError(f"unexpected endpoint: {endpoint}")


# X long-form Article: post_comments returns only a t.co link as body + replies;
# the real article body lives in tweet_detail data.article.full_text (verified 2026-06-09).
ARTICLE_POST_COMMENTS = {
    "code": 200,
    "data": {
        "id": "2046082879109959807",
        "text": "https://t.co/R7jxglREBs",
        "display_text": "https://t.co/R7jxglREBs",
        "likes": 2100,
        "replies": 59,
        "author": {"screen_name": "Khazix0918", "name": "卡兹克"},
        "thread": [
            {"id": "r1", "text": "教程说用国产模型替换Claude原生模型效果也很好",
             "display_text": "教程说用国产模型替换Claude原生模型效果也很好",
             "likes": 88, "replies": 2, "author": {"screen_name": "reader1"}},
            {"id": "r2", "text": "用国产模型效果差很多",
             "display_text": "用国产模型效果差很多",
             "likes": 50, "replies": 1, "author": {"screen_name": "reader2"}},
        ],
    },
}
ARTICLE_DETAIL = {
    "code": 200,
    "data": {
        "id": "2046082879109959807",
        "text": "https://t.co/R7jxglREBs",
        "author": {"screen_name": "Khazix0918"},
        "article": {
            "title": "从0开始，在国内用上Claude Code的终极保姆教程来了。",
            "preview_text": "最近很多朋友都在问我...",
            "full_text": (
                "最近很多朋友都在问我，能不能出一期Claude Code的小白教程。\n\n"
                "他们也想用上这个世界上最牛逼的Agent产品。\n\n"
                "而且其实很多人不太知道，Agent产品一般是Agent框架+模型组成的。"
            ),
        },
    },
}


# Regression: Article main tweet is only t.co, but author also posted short
# conversation replies. Merged thread_text is NOT thin — old logic skipped detail.
JXNL_ARTICLE_POST_COMMENTS = {
    "code": 200,
    "data": {
        "id": "2057153744630890620",
        "text": "https://t.co/9KkXEINuIj",
        "display_text": "https://t.co/9KkXEINuIj",
        "likes": 2800,
        "replies": 69,
        "author": {"screen_name": "jxnlco", "name": "Jason Liu"},
        "thread": [
            {
                "id": "r_author_1",
                "text": "They are sending me a windows computer\n@dkundel I will be dogfoodign",
                "display_text": "They are sending me a windows computer\n@dkundel I will be dogfoodign",
                "likes": 10,
                "replies": 0,
                "author": {"screen_name": "jxnlco", "name": "Jason Liu"},
            },
            {
                "id": "r_other",
                "text": "Such a great article",
                "display_text": "Such a great article",
                "likes": 5,
                "replies": 0,
                "author": {"screen_name": "reader1"},
            },
            {
                "id": "r_author_2",
                "text": "we're noticing an issue, and working on a resolution!",
                "display_text": "we're noticing an issue, and working on a resolution!",
                "likes": 3,
                "replies": 0,
                "author": {"screen_name": "jxnlco", "name": "Jason Liu"},
            },
        ],
    },
}
JXNL_ARTICLE_DETAIL = {
    "code": 200,
    "data": {
        "id": "2057153744630890620",
        "text": "x.com/i/article/2057…",
        "author": {"screen_name": "jxnlco"},
        "article": {
            "title": "Getting the most out of Codex",
            "preview_text": "Most developers first use coding agents for code...",
            "full_text": (
                "Most developers first use coding agents for code: inspect a repository, "
                "make a diff, run tests, and open a pull request.\n\n"
                "That's still the center of gravity for Codex. But much of the work on a "
                "computer is already mediated by code."
            ),
        },
    },
}

DETAIL_NO_ARTICLE = {
    "code": 200,
    "data": {
        "id": "1002103360646823936",
        "text": "How to Get Rich (without getting lucky):",
        "author": {"screen_name": "naval"},
    },
}


class TestTwitterArticle:
    def test_article_full_text_becomes_content(self):
        downloader = _RoutingDownloader({
            "fetch_post_comments": ARTICLE_POST_COMMENTS,
            "fetch_tweet_detail": ARTICLE_DETAIL,
        })
        post = TwitterPostFetcher(downloader_factory=lambda url: downloader).fetch(
            "https://x.com/Khazix0918/status/2046082879109959807",
            "2046082879109959807",
        )
        # 长文正文被取到（不再只是 t.co 链接）
        assert "最近很多朋友都在问我" in post.thread_text
        assert "Agent框架+模型" in post.thread_text
        # 用文章标题
        assert post.title.startswith("从0开始")
        assert post.author == "Khazix0918"
        # 回复仍来自 post_comments
        assert len(post.comments) == 2
        # 确实补取了 tweet_detail
        assert any("fetch_tweet_detail" in c for c in downloader.calls)

    def test_article_not_masked_by_author_conversation_replies(self):
        """Main=t.co + author chat replies must still use Article full_text."""
        downloader = _RoutingDownloader({
            "fetch_post_comments": JXNL_ARTICLE_POST_COMMENTS,
            "fetch_tweet_detail": JXNL_ARTICLE_DETAIL,
        })
        post = TwitterPostFetcher(downloader_factory=lambda url: downloader).fetch(
            "https://x.com/jxnlco/status/2057153744630890620",
            "2057153744630890620",
        )
        assert post.title == "Getting the most out of Codex"
        assert "coding agents for code" in post.thread_text
        assert "center of gravity for Codex" in post.thread_text
        # Must NOT use author conversation stubs as deep-learning body
        assert "windows computer" not in post.thread_text.lower()
        assert "dogfoodign" not in post.thread_text
        assert "working on a resolution" not in post.thread_text
        # Third-party replies still available as comments
        assert any(c.user_nickname == "reader1" for c in post.comments)
        assert any("fetch_tweet_detail" in c for c in downloader.calls)

    def test_substantive_tweet_keeps_thread_when_detail_has_no_article(self):
        # Always probes detail; without article, keep author self-thread content.
        downloader = _RoutingDownloader({
            "fetch_post_comments": SELF_THREAD_RESPONSE,
            "fetch_tweet_detail": DETAIL_NO_ARTICLE,
        })
        post = TwitterPostFetcher(downloader_factory=lambda url: downloader).fetch(
            "https://x.com/naval/status/1002103360646823936", "1002103360646823936"
        )
        assert any("fetch_tweet_detail" in c for c in downloader.calls)
        assert "How to Get Rich" in post.thread_text
        assert "Seek wealth" in post.thread_text
        assert "ethical wealth creation" in post.thread_text
