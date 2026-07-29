"""Comment-free X/Twitter source adapter for deep-learning acquisition."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from .base import BaseDownloader
from .models import DownloadInfo, VideoMetadata


_DETAIL_ENDPOINT = "/api/v1/twitter/web/fetch_tweet_detail"
_ALLOWED_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
_STATUS_PATH = re.compile(
    r"^/[^/]+/status/(?P<tweet_id>\d+)(?:/video/\d+)?/?$",
    re.IGNORECASE,
)


class TwitterDownloader(BaseDownloader):
    """Acquire tweet text and optional playable video without fetching replies."""

    def __init__(
        self,
        request_func: Optional[
            Callable[[str, dict[str, Any]], dict[str, Any]]
        ] = None,
    ) -> None:
        super().__init__()
        self._request_func = request_func or self.make_api_request
        self._detail_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def is_canonical_status_url(url: str) -> bool:
        """Return whether *url* is an allowed canonical status URL."""
        try:
            parsed = urlsplit(url)
        except (TypeError, ValueError):
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if (parsed.hostname or "").lower() not in _ALLOWED_HOSTS:
            return False
        return _STATUS_PATH.fullmatch(parsed.path) is not None

    def can_handle(self, url: str) -> bool:
        return self.is_canonical_status_url(url)

    def extract_video_id(self, url: str) -> str:
        if not self.is_canonical_status_url(url):
            raise ValueError("Unsupported X/Twitter status URL")
        match = _STATUS_PATH.fullmatch(urlsplit(url).path)
        if match is None:  # pragma: no cover - guarded above
            raise ValueError("Missing X/Twitter status id")
        return match.group("tweet_id")

    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        detail = self._get_detail(video_id)
        text = self._content_text(detail)
        video_url = self._video_url(detail)
        article = detail.get("article")
        article_title = (
            str(article.get("title") or "").strip()
            if isinstance(article, dict)
            else ""
        )
        title = article_title or self._short_title(text)
        author = self._author(detail)
        content_kind = "video" if video_url else ("social_text" if text else "empty")
        return VideoMetadata(
            video_id=video_id,
            platform="twitter",
            title=title,
            author=author,
            description=text,
            extra={
                "content_kind": content_kind,
                "source_type": "social_post",
            },
        )

    def _fetch_download_info(self, url: str, video_id: str) -> DownloadInfo:
        detail = self._get_detail(video_id)
        video_url = self._video_url(detail)
        return DownloadInfo(
            download_url=video_url,
            file_ext=".mp4" if video_url else None,
            filename=f"twitter_{video_id}.mp4" if video_url else None,
            extra={
                "content_kind": "video" if video_url else (
                    "social_text" if self._content_text(detail) else "empty"
                ),
            },
        )

    def get_subtitle(self, url: str) -> None:
        return None

    def _get_detail(self, tweet_id: str) -> dict[str, Any]:
        cached = self._detail_cache.get(tweet_id)
        if cached is not None:
            return cached
        response = self._request_func(_DETAIL_ENDPOINT, {"tweet_id": tweet_id})
        detail = self._unwrap(response)
        self._detail_cache[tweet_id] = detail
        return detail

    @staticmethod
    def _unwrap(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise ValueError("Twitter detail API returned invalid response")
        if response.get("code") not in (None, 0, 200):
            raise ValueError(
                str(response.get("message") or "Twitter detail API returned error")
            )
        data = response.get("data", response)
        if not isinstance(data, dict):
            raise ValueError("Twitter detail API returned no data")
        return data

    @staticmethod
    def _content_text(detail: dict[str, Any]) -> str:
        article = detail.get("article")
        if isinstance(article, dict):
            article_text = str(article.get("full_text") or "").strip()
            if article_text:
                return article_text
        for key in ("display_text", "full_text", "text"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _author(detail: dict[str, Any]) -> str:
        author = detail.get("author")
        if isinstance(author, dict):
            return str(
                author.get("screen_name") or author.get("name") or ""
            ).strip()
        if isinstance(author, str):
            return author.strip()
        return ""

    @staticmethod
    def _short_title(text: str) -> str:
        first_line = (text or "").splitlines()[0].strip() if text else ""
        if not first_line:
            return "X content"
        return first_line if len(first_line) <= 120 else first_line[:117].rstrip() + "..."

    @classmethod
    def _video_url(cls, detail: dict[str, Any]) -> Optional[str]:
        direct = detail.get("media_playable_url")
        if cls._is_explicit_video_url(direct):
            return str(direct)

        media_items: list[Any] = []
        for container in (
            detail,
            detail.get("extended_entities"),
            detail.get("entities"),
        ):
            if not isinstance(container, dict):
                continue
            media = container.get("media")
            if isinstance(media, list):
                media_items.extend(media)
            elif isinstance(media, dict):
                media_items.append(media)

        candidates: list[tuple[int, str]] = []
        for item in media_items:
            if not isinstance(item, dict):
                continue
            media_type = str(item.get("type") or "").lower()
            if media_type in {"photo", "image"}:
                continue
            item_url = item.get("url") or item.get("media_url")
            item_mime = str(
                item.get("content_type") or item.get("mime_type") or ""
            ).lower()
            if cls._is_video_candidate(item_url, media_type, item_mime):
                candidates.append((int(item.get("bitrate") or 0), str(item_url)))

            video_info = item.get("video_info")
            variants = (
                video_info.get("variants")
                if isinstance(video_info, dict)
                else item.get("variants")
            )
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_url = variant.get("url")
                variant_mime = str(variant.get("content_type") or "").lower()
                if not cls._is_video_candidate(
                    variant_url, media_type or "video", variant_mime
                ):
                    continue
                bitrate = variant.get("bitrate")
                candidates.append(
                    (
                        int(bitrate) if isinstance(bitrate, int) else 0,
                        str(variant_url),
                    )
                )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @classmethod
    def _is_video_candidate(
        cls,
        url: Any,
        media_type: str,
        mime_type: str,
    ) -> bool:
        if not cls._is_http_url(url):
            return False
        if mime_type == "video/mp4":
            return True
        if media_type not in {"video", "animated_gif"}:
            return False
        return cls._has_mp4_path(str(url))

    @classmethod
    def _is_explicit_video_url(cls, url: Any) -> bool:
        return cls._is_http_url(url) and cls._has_mp4_path(str(url))

    @staticmethod
    def _is_http_url(url: Any) -> bool:
        if not isinstance(url, str) or not url:
            return False
        try:
            return urlsplit(url).scheme in {"http", "https"}
        except ValueError:
            return False

    @staticmethod
    def _has_mp4_path(url: str) -> bool:
        try:
            suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
        except ValueError:
            return False
        return suffix == ".mp4"
