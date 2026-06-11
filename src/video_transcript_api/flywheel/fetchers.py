"""Content-source fetchers: blogger homepage URL -> normalized blogger + posts.

Platform-agnostic by design. Each platform implements ``ContentSourceFetcher``
and registers in ``FETCHERS``; adding a platform = adding a fetcher, nothing
else changes. The TikHub call is an injectable ``api_request`` callable so the
mapping is unit-testable without network (prod uses the project's downloader).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Protocol
from urllib.parse import parse_qs, urlparse

from ..utils.logging import setup_logger
from .models import Blogger, MediaType

logger = setup_logger("flywheel_fetcher")

# (endpoint, params) -> raw response dict
ApiRequest = Callable[[str, dict], dict]


@dataclass(frozen=True)
class FetchedItem:
    """A normalized post before it is tied to a persisted blogger row."""
    platform_item_id: str
    media_type: MediaType
    title: str
    original_url: str
    cover_url: Optional[str]
    published_at: Optional[datetime]
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0


@dataclass(frozen=True)
class FetchResult:
    blogger: Blogger              # id=None, ready to upsert
    items: tuple[FetchedItem, ...]


class ContentSourceFetcher(Protocol):
    platform: str
    def fetch_blogger(self, url: str, *, max_items: int = 20) -> FetchResult: ...


# --------------------------------------------------------------------------- #
# Shared parsing helpers (defensive, mirroring comments/* style)
# --------------------------------------------------------------------------- #

def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = value.strip().replace(",", "")
        if digits.isdigit():
            return int(digits)
    return 0


def _first(d: dict, keys: tuple[str, ...], default: Any = "") -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _to_datetime(value: Any) -> Optional[datetime]:
    ts = _as_int(value)
    if ts <= 0:
        return None
    if ts > 1_000_000_000_000:  # milliseconds
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Xiaohongshu
# --------------------------------------------------------------------------- #

class XiaohongshuUserFetcher:
    """Fetch a 小红书 blogger's profile + recent notes via TikHub."""

    platform = "xiaohongshu"
    _ENDPOINT = "/api/v1/xiaohongshu/app_v2/get_user_posted_notes"

    def __init__(self, api_request: Optional[ApiRequest] = None):
        self._api_request = api_request

    def fetch_blogger(self, url: str, *, max_items: int = 20) -> FetchResult:
        request = self._api_request or self._default_request(url)
        user_id = self._user_id_from_url(url)
        xsec = self._xsec_from_url(url)

        raw_notes: list[dict] = []
        last_user: dict = {}
        cursor = ""
        while len(raw_notes) < max_items:
            resp = request(self._ENDPOINT,
                           {"user_id": user_id, "share_text": url, "cursor": cursor})
            data = self._data(resp)
            last_user = data.get("user") if isinstance(data.get("user"), dict) else last_user
            page_notes = self._find_notes(data)
            if not page_notes:
                break
            raw_notes.extend(page_notes)
            if not data.get("has_more"):
                break
            cursor = str(data.get("cursor") or "")
            if not cursor:
                break

        raw_notes = raw_notes[:max_items]
        items = tuple(self._to_item(n, xsec) for n in raw_notes)
        blogger = self._to_blogger(last_user, user_id, items)
        logger.info(f"fetched xhs blogger user_id={blogger.platform_user_id}, items={len(items)}")
        return FetchResult(blogger=blogger, items=items)

    # --- request plumbing --------------------------------------------------
    def _default_request(self, url: str) -> ApiRequest:
        from ..downloaders import create_downloader  # lazy: avoid heavy import in unit tests
        downloader = create_downloader(url)
        return downloader.make_api_request

    @staticmethod
    def _data(resp: Any) -> dict:
        if not isinstance(resp, dict):
            raise ValueError("小红书 API 返回无效响应")
        if resp.get("code") not in (None, 0, 200) and not resp.get("success", True):
            raise ValueError(resp.get("msg") or "小红书 API 返回错误")
        data = resp.get("data", resp)
        return data if isinstance(data, dict) else {"notes": data}

    @staticmethod
    def _find_notes(data: dict) -> list[dict]:
        for key in ("notes", "note_list", "list", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [n for n in value if isinstance(n, dict)]
        return []

    # --- url parsing -------------------------------------------------------
    @staticmethod
    def _user_id_from_url(url: str) -> str:
        m = re.search(r"/user/profile/([0-9a-zA-Z]+)", url)
        if m:
            return m.group(1)
        return parse_qs(urlparse(url).query).get("user_id", [""])[0]

    @staticmethod
    def _xsec_from_url(url: str) -> str:
        return parse_qs(urlparse(url).query).get("xsec_token", [""])[0]

    # --- mapping -----------------------------------------------------------
    def _to_item(self, note: dict, xsec: str) -> FetchedItem:
        note_id = str(_first(note, ("note_id", "id"), ""))
        note_type = str(_first(note, ("type", "note_type"), "normal")).lower()
        media_type = MediaType.VIDEO if note_type == "video" else MediaType.ARTICLE
        interact = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else note
        cover = note.get("cover") if isinstance(note.get("cover"), dict) else {}
        explore = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec:
            explore += f"?xsec_token={xsec}"
        return FetchedItem(
            platform_item_id=note_id,
            media_type=media_type,
            title=str(_first(note, ("display_title", "title", "desc"), f"笔记 {note_id}")),
            original_url=explore,
            cover_url=_first(cover, ("url", "url_default"), None) or _first(note, ("cover_url",), None),
            published_at=_to_datetime(_first(note, ("time", "create_time", "published_at"), 0)),
            like_count=_as_int(_first(interact, ("liked_count", "like_count", "likes"), 0)),
            collect_count=_as_int(_first(interact, ("collected_count", "collect_count"), 0)),
            comment_count=_as_int(_first(interact, ("comment_count", "comments"), 0)),
            share_count=_as_int(_first(interact, ("share_count", "shared_count"), 0)),
        )

    @staticmethod
    def _to_blogger(user: dict, fallback_uid: str, items: tuple[FetchedItem, ...]) -> Blogger:
        media_types: tuple[MediaType, ...] = ()
        for it in items:
            if it.media_type not in media_types:
                media_types = media_types + (it.media_type,)
        return Blogger(
            id=None,
            platform="xiaohongshu",
            platform_user_id=str(_first(user, ("user_id", "id"), fallback_uid)),
            handle=str(_first(user, ("nickname", "nick_name", "name"), "unknown")),
            avatar_url=_first(user, ("avatar", "avatar_url", "image"), None) or None,
            bio=_first(user, ("desc", "description", "bio"), None) or None,
            follower_count=_as_int(_first(user, ("fans", "follower_count", "fans_count"), 0)),
            media_types=media_types,
        )


# --------------------------------------------------------------------------- #
# Registry — add a platform = add a fetcher here
# --------------------------------------------------------------------------- #

FETCHERS: dict[str, type] = {
    "xiaohongshu": XiaohongshuUserFetcher,
    # "weixin": WeixinUserFetcher,
    # "douyin": DouyinUserFetcher,
    # "youtube": YoutubeUserFetcher,
}


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "xiaohongshu" in host or "xhslink" in host:
        return "xiaohongshu"
    if "weixin" in host or "mp.weixin" in host:
        return "weixin"
    if "douyin" in host:
        return "douyin"
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    raise ValueError(f"无法识别平台: {url}")


def get_fetcher(platform: str, *, api_request: Optional[ApiRequest] = None) -> ContentSourceFetcher:
    cls = FETCHERS.get(platform)
    if cls is None:
        raise ValueError(f"平台暂不支持: {platform}（已支持: {', '.join(FETCHERS)}）")
    return cls(api_request=api_request)


def fetch_blogger(url: str, *, max_items: int = 20,
                  api_request: Optional[ApiRequest] = None) -> FetchResult:
    """Convenience: pick the fetcher by URL and fetch."""
    return get_fetcher(detect_platform(url), api_request=api_request).fetch_blogger(
        url, max_items=max_items)
