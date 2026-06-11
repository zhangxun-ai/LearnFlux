"""Fetch a Xiaohongshu 图文 (image-text) note as a post for insight analysis.

The note's textual content (title + desc) is available via TikHub
`web/get_note_info_v7` (verified 2026-06-09: data[0].note_list[0].desc / .title).
Image-embedded text (OCR) is NOT provided by the API — that would require
downloading images and running OCR/vision, deferred as a future enhancement.

Returns the same shape as TwitterPost so it plugs into generate_post_insight.
"""

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..downloaders import create_downloader
from ..utils.logging import setup_logger
from .selector import CommentItem

logger = setup_logger("xiaohongshu_post_fetcher")


def _xsec_token(url: str) -> str:
    try:
        return parse_qs(urlparse(url).query).get("xsec_token", [""])[0]
    except Exception:
        return ""


@dataclass(frozen=True)
class XhsPost:
    """Normalized Xiaohongshu note (shares TwitterPost's attribute surface)."""

    title: str
    author: str
    thread_text: str  # the note body (desc) used as analysis content
    comments: list[CommentItem] = field(default_factory=list)
    main_tweet_id: str = ""


class XhsPostFetcher:
    """Fetch a Xiaohongshu note's title + body text for post insight."""

    def __init__(self, downloader_factory: Callable[[str], Any] = create_downloader):
        self.downloader_factory = downloader_factory

    def fetch(self, url: str, note_id: str, max_comments: int = 80) -> XhsPost:
        """Fetch note title + body, trying multiple endpoints for resilience.

        TikHub's XHS note endpoints are individually flaky (some 400 for a given
        note while others succeed), so we try several and take the first that
        yields content. ``fetch_note_detail`` (note_id + xsec_token) is the most
        reliable in testing and goes first. Comments are not fetched in v1
        (the comment endpoints are unstable); the analyzer handles empty comments.
        """
        downloader = self.downloader_factory(url)
        candidates = self._endpoint_candidates(url, note_id)

        last_error: Exception | None = None
        for endpoint, params in candidates:
            try:
                response = downloader.make_api_request(endpoint, params)
                note = self._extract_note(response)
                title = (self._first_str(note, ("title",)) or "").strip()
                desc = (self._first_str(note, ("desc", "description")) or "").strip()
                if not title and not desc:
                    continue
                author = self._author_of(note)
                logger.info(
                    f"Fetched xhs note via {endpoint}: id={note_id}, "
                    f"author=@{author}, title_len={len(title)}, desc_len={len(desc)}"
                )
                return XhsPost(
                    title=title or f"小红书笔记 {note_id}",
                    author=author,
                    thread_text=desc,
                    comments=self._fetch_comments(downloader, note_id, max_comments),
                    main_tweet_id=note_id,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(f"xhs endpoint failed: {endpoint}, error={exc}")
                continue

        raise ValueError(f"无法获取小红书笔记内容（已尝试多个接口）: {last_error}")

    @staticmethod
    def _endpoint_candidates(url: str, note_id: str) -> list[tuple[str, dict[str, Any]]]:
        """Ordered endpoints. fetch_note_detail (xsec) first — most reliable."""
        xsec = _xsec_token(url)
        candidates: list[tuple[str, dict[str, Any]]] = []
        if xsec:
            candidates.append(
                ("/api/v1/xiaohongshu/web_v3/fetch_note_detail",
                 {"note_id": note_id, "xsec_token": xsec})
            )
        candidates.append(
            ("/api/v1/xiaohongshu/web/get_note_info_v7",
             {"note_id": note_id, "share_text": url})
        )
        candidates.append(
            ("/api/v1/xiaohongshu/app_v2/get_image_note_detail",
             {"note_id": note_id, "share_text": url})
        )
        candidates.append(
            ("/api/v1/xiaohongshu/web/get_note_info_v4",
             {"note_id": note_id, "share_text": url})
        )
        return candidates

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _data(response: Any) -> Any:
        if not isinstance(response, dict):
            raise ValueError("小红书 API 返回无效响应")
        if response.get("code") not in (None, 0, 200) and not response.get("success", True):
            raise ValueError(response.get("msg") or "小红书 API 返回错误")
        return response.get("data", response)

    def _extract_note(self, response: Any) -> dict[str, Any]:
        """Locate the note dict across known response shapes."""
        data = self._data(response)
        # get_note_info_v7: data[0].note_list[0]
        if isinstance(data, list) and data and isinstance(data[0], dict):
            note_list = data[0].get("note_list")
            if isinstance(note_list, list) and note_list and isinstance(note_list[0], dict):
                return note_list[0]
        # fetch_note_detail fallback: data.items[0].noteCard
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list) and items and isinstance(items[0], dict):
                card = items[0].get("noteCard")
                if isinstance(card, dict):
                    return card
        # generic: recursively find a dict that has both title and desc
        found = self._find_note_dict(data)
        if found:
            return found
        raise ValueError("无法解析小红书笔记结构")

    def _find_note_dict(self, obj: Any) -> dict[str, Any] | None:
        if isinstance(obj, dict):
            if "desc" in obj or "title" in obj:
                return obj
            for v in obj.values():
                found = self._find_note_dict(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj[:8]:
                found = self._find_note_dict(v)
                if found:
                    return found
        return None

    def _fetch_comments(self, downloader: Any, note_id: str, max_comments: int) -> list[CommentItem]:
        """Best-effort hot comments via web_v2/fetch_note_comments; [] on failure.

        The analyzer tolerates an empty list, so comment-fetch problems never
        fail the whole insight — content analysis still proceeds.
        """
        try:
            response = downloader.make_api_request(
                "/api/v1/xiaohongshu/web_v2/fetch_note_comments",
                {"note_id": note_id, "cursor": ""},
            )
            data = self._data(response)
            raw = self._find_comment_list(data)
            items: list[CommentItem] = []
            for rank, c in enumerate(raw[:max_comments]):
                if not isinstance(c, dict):
                    continue
                text = self._first_str(c, ("content", "text"))
                if not text:
                    continue
                items.append(
                    CommentItem(
                        text=text,
                        like_count=self._as_int(
                            c.get("like_count")
                            or c.get("liked_count")
                            or c.get("like_num")
                            or c.get("digg_count")
                        ),
                        reply_count=self._as_int(
                            c.get("sub_comment_count") or c.get("reply_count")
                        ),
                        user_nickname=self._comment_author(c),
                        comment_id=str(c.get("id") or c.get("comment_id") or ""),
                        platform_rank=rank,
                    )
                )
            logger.info(f"Fetched xhs comments: note={note_id}, count={len(items)}")
            return items
        except Exception as exc:
            logger.warning(f"xhs comments fetch failed: note={note_id}, error={exc}")
            return []

    def _find_comment_list(self, obj: Any) -> list[dict[str, Any]]:
        """Locate the list of comment dicts (each having a content/text field)."""
        if isinstance(obj, dict):
            for key in ("comments", "comment_list", "list", "items", "data"):
                value = obj.get(key)
                if isinstance(value, list) and any(
                    isinstance(x, dict) and ("content" in x or "text" in x) for x in value
                ):
                    return [x for x in value if isinstance(x, dict)]
            for value in obj.values():
                found = self._find_comment_list(value)
                if found:
                    return found
        elif isinstance(obj, list):
            if any(isinstance(x, dict) and ("content" in x or "text" in x) for x in obj):
                return [x for x in obj if isinstance(x, dict)]
            for value in obj[:8]:
                found = self._find_comment_list(value)
                if found:
                    return found
        return []

    @staticmethod
    def _as_int(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return 0

    @staticmethod
    def _comment_author(comment: dict[str, Any]) -> str:
        user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
        return str(
            comment.get("nick_name")
            or comment.get("nickname")
            or user.get("nickname")
            or user.get("nickName")
            or "anonymous"
        ).strip()

    @staticmethod
    def _first_str(note: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = note.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @staticmethod
    def _author_of(note: dict[str, Any]) -> str:
        user = note.get("user") if isinstance(note.get("user"), dict) else {}
        return str(
            user.get("nickname")
            or user.get("nickName")
            or user.get("name")
            or note.get("nickname")
            or note.get("nickName")
            or "unknown"
        ).strip()
