"""Fetch hot comments from platform APIs through TikHub."""

from typing import Any, Callable

from ..downloaders import create_downloader
from ..utils.logging import setup_logger
from ..utils.url_parser import URLParser
from .selector import CommentItem

logger = setup_logger("comment_fetcher")


class TikHubCommentFetcher:
    """Fetch and normalize a bounded hot-comment window."""

    def __init__(self, downloader_factory: Callable[[str], Any] = create_downloader):
        self.downloader_factory = downloader_factory

    def fetch_hot_comments(
        self,
        url: str,
        platform: str | None = None,
        media_id: str | None = None,
        limit: int = 100,
    ) -> list[CommentItem]:
        """Fetch first-page hot comments for supported platforms.

        The platform APIs are treated as the primary hot-ranking signal. This
        method intentionally keeps the window bounded and does not crawl all
        pages.
        """
        platform, media_id = self._resolve_platform_media(url, platform, media_id)
        endpoint, params = self._build_request(platform, media_id, url, limit)

        downloader = self.downloader_factory(url)
        response = downloader.make_api_request(endpoint, params)

        if not isinstance(response, dict):
            raise ValueError("Comment API returned invalid response")
        if response.get("code") not in (None, 0, 200):
            raise ValueError(response.get("message") or "Comment API returned error")

        raw_comments = self._extract_comment_list(response.get("data", response))
        comments = [
            self._normalize_comment(raw, rank)
            for rank, raw in enumerate(raw_comments[:limit])
            if isinstance(raw, dict)
        ]

        normalized = [item for item in comments if item.text]
        logger.info(
            f"Fetched comments: platform={platform}, media_id={media_id}, count={len(normalized)}"
        )
        return normalized

    def _resolve_platform_media(
        self,
        url: str,
        platform: str | None,
        media_id: str | None,
    ) -> tuple[str, str]:
        if platform and media_id:
            return platform, media_id

        parsed = URLParser().parse(url)
        return platform or parsed.platform, media_id or parsed.video_id

    def _build_request(
        self,
        platform: str,
        media_id: str,
        url: str,
        limit: int,
    ) -> tuple[str, dict[str, Any]]:
        count = max(1, min(limit, 50))

        if platform == "douyin":
            return (
                "/api/v1/douyin/web/fetch_video_comments",
                {"aweme_id": media_id, "cursor": 0, "count": count},
            )

        if platform == "youtube":
            return (
                "/api/v1/youtube/web/get_video_comments",
                {
                    "video_id": media_id,
                    "language_code": "zh-CN",
                    "country_code": "CN",
                    "sort_by": "top",
                    "need_format": "true",
                },
            )

        if platform == "xiaohongshu":
            return (
                "/api/v1/xiaohongshu/app_v2/get_note_comments",
                {
                    "note_id": media_id,
                    "share_text": url,
                    "cursor": "",
                    "sort_strategy": "hot",
                },
            )

        raise ValueError(f"Comment fetching is not supported for platform: {platform}")

    def _extract_comment_list(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []

        for key in (
            "comments",
            "comment_list",
            "items",
            "list",
            "data",
            "notes",
        ):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = self._extract_comment_list(value)
                if nested:
                    return nested
        return []

    def _normalize_comment(self, raw: dict[str, Any], rank: int) -> CommentItem:
        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        author = raw.get("author") if isinstance(raw.get("author"), dict) else {}

        return CommentItem(
            text=self._first_text(
                raw,
                ("text", "content", "comment", "comment_text", "comment_content"),
            ),
            like_count=self._first_int(
                raw,
                ("digg_count", "like_count", "liked_count", "likeCount", "likes"),
            ),
            reply_count=self._first_int(
                raw,
                (
                    "reply_comment_total",
                    "reply_count",
                    "replyCount",
                    "sub_comment_count",
                    "subCommentCount",
                ),
            ),
            user_nickname=(
                raw.get("user_nickname")
                or raw.get("nickname")
                or raw.get("author")
                or user.get("nickname")
                or user.get("name")
                or author.get("name")
                or author.get("text")
                or ""
            ),
            comment_id=str(
                raw.get("cid")
                or raw.get("comment_id")
                or raw.get("id")
                or raw.get("commentId")
                or ""
            ),
            platform_rank=rank,
        )

    def _first_text(self, raw: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                text = value.get("text") or value.get("content")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _first_int(self, raw: dict[str, Any], keys: tuple[str, ...]) -> int:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return 0
