"""Fetch an X / Twitter post and its replies via TikHub.

One TikHub endpoint (`/api/v1/twitter/web/fetch_post_comments`) returns both the
main tweet (response ``data`` top-level) and the conversation chain (``data.thread``).
For an author self-thread the chain items share the root author's ``screen_name``;
for a standalone tweet they are other users' replies. We therefore split the chain
by author: the author's own tweets extend the post content, everyone else becomes a
comment. Verified against real responses on 2026-06-09.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..downloaders import create_downloader
from ..utils.logging import setup_logger
from .selector import CommentItem

logger = setup_logger("twitter_post_fetcher")

# TikHub endpoint returning main tweet + conversation chain in one call.
_POST_COMMENTS_ENDPOINT = "/api/v1/twitter/web/fetch_post_comments"
# Tweet detail endpoint — carries X long-form Article body in data.article.full_text.
_TWEET_DETAIL_ENDPOINT = "/api/v1/twitter/web/fetch_tweet_detail"

# Title length cap (characters) derived from the first line of the main tweet.
_TITLE_MAX_LENGTH = 80


@dataclass(frozen=True)
class TwitterPost:
    """Normalized X post.

    Attributes:
        title: Short title (first line of the main tweet, truncated).
        author: Root author screen_name (display form).
        thread_text: Main tweet + author self-thread merged, as analysis content.
        comments: Third-party replies normalized as CommentItem (hot order preserved).
        main_tweet_id: Resolved id of the main tweet.
    """

    title: str
    author: str
    thread_text: str
    comments: list[CommentItem]
    main_tweet_id: str = ""


class TwitterPostFetcher:
    """Fetch a tweet's author thread (content) and third-party replies (comments)."""

    def __init__(self, downloader_factory: Callable[[str], Any] = create_downloader):
        # Injectable for tests; defaults to the project's TikHub-backed factory.
        self.downloader_factory = downloader_factory

    def fetch(self, url: str, tweet_id: str, max_comments: int = 80) -> TwitterPost:
        """Fetch and normalize a single X post.

        Args:
            url: Original tweet URL (used to build the downloader).
            tweet_id: Numeric tweet id extracted by URLParser.
            max_comments: Upper bound on third-party replies kept (cost control).

        Returns:
            TwitterPost with merged author content and normalized replies.

        Raises:
            ValueError: API response is missing/invalid or returns an error code.
        """
        downloader = self.downloader_factory(url)
        response = downloader.make_api_request(
            _POST_COMMENTS_ENDPOINT, {"tweet_id": tweet_id, "cursor": ""}
        )
        data = self._unwrap(response)

        root_author = self._screen_name(data.get("author"))
        root_key = root_author.lower()

        author_thread: list[dict[str, Any]] = []
        replies: list[dict[str, Any]] = []
        for item in data.get("thread") or []:
            if not isinstance(item, dict):
                continue
            if root_key and self._screen_name(item.get("author")).lower() == root_key:
                author_thread.append(item)
            else:
                replies.append(item)

        thread_text = self._build_thread_text(data, author_thread)
        comments = [
            comment
            for rank, item in enumerate(replies[:max_comments])
            if (comment := self._to_comment(item, rank)).text
        ]

        title = self._build_title(data)
        author = root_author or "Unknown"

        # X 长文（Article）：正文不在 text/display_text（那里只是 t.co 链接），而在
        # fetch_tweet_detail 的 data.article.full_text。仅当当前正文"很薄"（为空或
        # 只是一个链接）时才补取一次，避免给普通推文/thread 多打一次请求。
        is_article = False
        if self._looks_thin(thread_text):
            article = self._fetch_article(downloader, tweet_id)
            if article and article.get("full_text"):
                thread_text = article["full_text"].strip()
                if article.get("title"):
                    title = article["title"].strip()[:120]
                is_article = True

        logger.info(
            f"Fetched twitter post: id={tweet_id}, author=@{author}, "
            f"article={is_article}, thread_parts={len(author_thread)}, replies={len(comments)}"
        )
        return TwitterPost(
            title=title,
            author=author,
            thread_text=thread_text,
            comments=comments,
            main_tweet_id=str(data.get("id") or tweet_id),
        )

    # --- helpers -----------------------------------------------------------

    def _fetch_article(self, downloader: Any, tweet_id: str) -> Optional[dict[str, str]]:
        """Fetch X long-form Article body via tweet detail; None if not an article."""
        try:
            response = downloader.make_api_request(
                _TWEET_DETAIL_ENDPOINT, {"tweet_id": tweet_id}
            )
            data = self._unwrap(response)
            article = data.get("article")
            if isinstance(article, dict):
                return {
                    "title": str(article.get("title") or ""),
                    "full_text": str(article.get("full_text") or ""),
                }
        except Exception as exc:
            logger.warning(f"Fetch tweet article failed: id={tweet_id}, error={exc}")
        return None

    @staticmethod
    def _looks_thin(text: str) -> bool:
        """True when content is empty or just a single URL (likely an Article/link)."""
        stripped = (text or "").strip()
        return (not stripped) or bool(re.match(r"^https?://\S+$", stripped))

    @staticmethod
    def _unwrap(response: Any) -> dict[str, Any]:
        """Validate the API envelope and return the ``data`` payload."""
        if not isinstance(response, dict):
            raise ValueError("Twitter API returned invalid response")
        if response.get("code") not in (None, 0, 200):
            raise ValueError(response.get("message") or "Twitter API returned error")
        data = response.get("data", response)
        if not isinstance(data, dict):
            raise ValueError("Twitter API returned no post data")
        return data

    @staticmethod
    def _screen_name(author: Any) -> str:
        """Extract a stable author handle from a tweet/reply author field."""
        if isinstance(author, dict):
            return str(author.get("screen_name") or author.get("name") or "").strip()
        if isinstance(author, str):
            return author.strip()
        return ""

    @staticmethod
    def _text_of(item: dict[str, Any]) -> str:
        """Prefer display_text (mention-stripped) over raw text."""
        for key in ("display_text", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _as_int(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return 0

    def _build_thread_text(
        self, data: dict[str, Any], author_thread: list[dict[str, Any]]
    ) -> str:
        parts = [self._text_of(data)]
        parts.extend(self._text_of(item) for item in author_thread)
        return "\n\n".join(part for part in parts if part)

    def _build_title(self, data: dict[str, Any]) -> str:
        main = self._text_of(data)
        if not main:
            return "X 帖子"
        first_line = main.splitlines()[0]
        if len(first_line) > _TITLE_MAX_LENGTH:
            return first_line[:_TITLE_MAX_LENGTH].rstrip() + "..."
        return first_line

    def _to_comment(self, item: dict[str, Any], rank: int) -> CommentItem:
        return CommentItem(
            text=self._text_of(item),
            like_count=self._as_int(item.get("likes")),
            reply_count=self._as_int(item.get("replies")),
            user_nickname=self._screen_name(item.get("author")),
            comment_id=str(item.get("id") or ""),
            platform_rank=rank,
        )
