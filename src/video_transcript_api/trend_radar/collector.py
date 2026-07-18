"""TikHub-backed social signal collection for trend radar."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import sqrt
from typing import Any
from urllib.parse import quote

from ..tikhub import (
    TikHubAuthError,
    TikHubClient,
    TikHubPaymentRequiredError,
    TikHubRateLimitError,
    TikHubRequestError,
)
from .budget import BudgetExceeded, BudgetLedger
from .models import DEFAULT_TOPIC_SEEDS, RawSignal, TopicSeed

_X_SEARCH = "/api/v1/twitter/web/fetch_search_timeline"
_X_TRENDING = "/api/v1/twitter/web/fetch_trending"
_X_USER_POSTS = "/api/v1/twitter/web/fetch_user_post_tweet"
_XHS_SEARCH = "/api/v1/xiaohongshu/app_v2/search_notes"
_DY_SEARCH = "/api/v1/douyin/search/fetch_general_search_v2"
_DY_HOT_TOTAL = "/api/v1/douyin/billboard/fetch_hot_total_list"
_DY_HOT_RISE = "/api/v1/douyin/billboard/fetch_hot_rise_list"

_TITLE_KEYS = (
    "title",
    "note_title",
    "desc",
    "description",
    "full_text",
    "text",
    "content",
    "display_text",
)
_TEXT_KEYS = _TITLE_KEYS + ("summary", "caption", "name")
_URL_KEYS = ("url", "web_url", "share_url", "note_url", "tweet_url", "aweme_url", "expanded_url")
_AUTHOR_KEYS = ("author", "nickname", "screen_name", "user_name", "name")
_DATE_KEYS = ("created_at", "publish_time", "published_at", "time")
_ID_KEYS = ("tweet_id", "aweme_id", "note_id", "id_str", "rest_id", "id")
_METRIC_KEYS = (
    "like_count",
    "digg_count",
    "favorite_count",
    "favorites",
    "collect_count",
    "comment_count",
    "comments_count",
    "reply_count",
    "replies",
    "share_count",
    "retweets",
    "bookmarks",
    "repost_count",
    "view_count",
    "views",
    "play_count",
)


class TikHubTrendCollector:
    """Collect a bounded sample from X, Xiaohongshu and Douyin."""

    def __init__(
        self,
        client: TikHubClient,
        ledger: BudgetLedger,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.ledger = ledger
        self.config = config or {}
        self.now = datetime.now(timezone.utc)
        self.warnings: list[str] = []
        self.budget_exhausted = False

    def collect(self) -> list[RawSignal]:
        topics = self._topics()
        signals: list[RawSignal] = []
        sources = self.config.get("sources") or ("x", "xiaohongshu", "douyin")
        if "x" in sources:
            signals.extend(self._collect_x(topics))
            if self.budget_exhausted:
                return self._dedupe(signals)
        if "xiaohongshu" in sources:
            signals.extend(self._collect_xiaohongshu(topics))
            if self.budget_exhausted:
                return self._dedupe(signals)
        if "douyin" in sources:
            signals.extend(self._collect_douyin(topics))
        return self._dedupe(signals)

    def _collect_x(self, topics: list[TopicSeed]) -> list[RawSignal]:
        signals: list[RawSignal] = []
        country = self.config.get("x_country", "UnitedStates")
        search_type = self.config.get("x_search_type", "Latest")
        trending = self._get("x", _X_TRENDING, {"country": country})
        signals.extend(self._normalize_response("x", "x-trending", "X 热门趋势", _X_TRENDING, trending))
        if self.budget_exhausted:
            return signals

        prefer_fresh = str(search_type).casefold() == "latest"
        for topic in topics:
            for keyword in self._limit_keywords(topic.x_keywords):
                payload = self._get(
                    "x",
                    _X_SEARCH,
                    {"keyword": keyword, "search_type": search_type},
                )
                signals.extend(
                    self._normalize_response(
                        "x",
                        topic.id,
                        topic.label,
                        _X_SEARCH,
                        payload,
                        prefer_fresh=prefer_fresh,
                    )
                )
                if self.budget_exhausted:
                    return signals

        for screen_name in self.config.get("x_elite_accounts", [])[:30]:
            payload = self._get("x", _X_USER_POSTS, {"screen_name": screen_name})
            signals.extend(
                self._normalize_response(
                    "x",
                    "elite-account",
                    f"英文 X 精英账号 @{screen_name}",
                    _X_USER_POSTS,
                    payload,
                )
            )
            if self.budget_exhausted:
                return signals
        return signals

    def _collect_xiaohongshu(self, topics: list[TopicSeed]) -> list[RawSignal]:
        signals: list[RawSignal] = []
        for topic in topics:
            for keyword in self._limit_keywords(topic.chinese_keywords):
                payload = self._get(
                    "xiaohongshu",
                    _XHS_SEARCH,
                    {"keyword": keyword, "page": 1},
                )
                signals.extend(
                    self._normalize_response(
                        "xiaohongshu", topic.id, topic.label, _XHS_SEARCH, payload
                    )
                )
                if self.budget_exhausted:
                    return signals
        return signals

    def _collect_douyin(self, topics: list[TopicSeed]) -> list[RawSignal]:
        signals: list[RawSignal] = []
        hot_total = self._get(
            "douyin",
            _DY_HOT_TOTAL,
            {"page": 1, "page_size": 30, "type": 0},
        )
        signals.extend(self._normalize_response("douyin", "douyin-hot", "抖音热榜", _DY_HOT_TOTAL, hot_total))
        if self.budget_exhausted:
            return signals

        hot_rise = self._get(
            "douyin",
            _DY_HOT_RISE,
            {"page": 1, "page_size": 30, "order": 0},
        )
        signals.extend(self._normalize_response("douyin", "douyin-hot", "抖音热榜", _DY_HOT_RISE, hot_rise))
        if self.budget_exhausted:
            return signals

        for topic in topics:
            for keyword in self._limit_keywords(topic.chinese_keywords):
                payload = self._post(
                    "douyin",
                    _DY_SEARCH,
                    {
                        "keyword": keyword,
                        "cursor": 0,
                        "sort_type": "0",
                        "publish_time": "7",
                    },
                )
                signals.extend(self._normalize_response("douyin", topic.id, topic.label, _DY_SEARCH, payload))
                if self.budget_exhausted:
                    return signals
        return signals

    def _get(self, source: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self._record_budget(source, endpoint):
            return None
        try:
            return self.client.get(endpoint, params)
        except (TikHubAuthError, TikHubPaymentRequiredError, TikHubRateLimitError):
            raise
        except TikHubRequestError as exc:
            self._warn(f"{source} {endpoint} skipped: {exc}")
            return None

    def _post(self, source: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self._record_budget(source, endpoint):
            return None
        try:
            return self.client.post(endpoint, payload)
        except (TikHubAuthError, TikHubPaymentRequiredError, TikHubRateLimitError):
            raise
        except TikHubRequestError as exc:
            self._warn(f"{source} {endpoint} skipped: {exc}")
            return None

    def _record_budget(self, source: str, endpoint: str) -> bool:
        try:
            self.ledger.record_api_request(source, endpoint)
            return True
        except BudgetExceeded as exc:
            self.budget_exhausted = True
            self._warn(str(exc))
            return False

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _topics(self) -> list[TopicSeed]:
        configured = self.config.get("topics")
        if not configured:
            return list(DEFAULT_TOPIC_SEEDS)
        topics = []
        for item in configured:
            topics.append(
                TopicSeed(
                    id=str(item.get("id") or item.get("label") or "topic"),
                    label=str(item.get("label") or item.get("id") or "趋势"),
                    x_keywords=tuple(item.get("x_keywords") or ()),
                    chinese_keywords=tuple(item.get("chinese_keywords") or ()),
                )
            )
        return topics or list(DEFAULT_TOPIC_SEEDS)

    def _limit_keywords(self, keywords: tuple[str, ...]) -> tuple[str, ...]:
        limit = int(self.config.get("max_keywords_per_topic", 3))
        return tuple(keywords[:max(1, limit)])

    def _normalize_response(
        self,
        platform: str,
        topic_id: str,
        topic_label: str,
        endpoint: str,
        payload: Any,
        *,
        prefer_fresh: bool = False,
    ) -> list[RawSignal]:
        records = _extract_records(payload, prefer_fresh=prefer_fresh)
        limit = int(self.config.get("max_items_per_call", 25))
        signals: list[RawSignal] = []
        for record in records[:limit]:
            title = _first_string(record, _TITLE_KEYS)
            text = _first_string(record, _TEXT_KEYS)
            if not title and not text:
                continue
            metrics = _metrics(record)
            fallback_url = _first_string(record, _URL_KEYS)
            signals.append(
                RawSignal(
                    platform=platform,
                    topic_id=topic_id,
                    topic_label=topic_label,
                    title=title or text[:80],
                    text=text or title,
                    url=_source_url(platform, record, fallback_url),
                    author=_first_string(record, _AUTHOR_KEYS),
                    published_at=_first_string(record, _DATE_KEYS) or None,
                    metrics=metrics,
                    source_endpoint=endpoint,
                    captured_at=self.now,
                )
            )
        return signals

    @staticmethod
    def _dedupe(signals: list[RawSignal]) -> list[RawSignal]:
        seen: set[tuple[str, str, str]] = set()
        result: list[RawSignal] = []
        for signal in signals:
            key = (signal.platform, signal.url, signal.title[:80])
            if key in seen:
                continue
            seen.add(key)
            result.append(signal)
        return result


def _extract_records(payload: Any, *, prefer_fresh: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 8 or len(records) >= 1000:
            return
        if isinstance(node, dict):
            if _looks_like_record(node):
                records.append(node)
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(payload)
    records.sort(key=_record_sort_key(prefer_fresh), reverse=True)
    return records


def _record_sort_key(prefer_fresh: bool):
    if prefer_fresh:
        return lambda item: (_record_freshness(item), _record_weight(item))
    return _record_weight


def _looks_like_record(item: dict[str, Any]) -> bool:
    direct_text = _first_direct_string(item, _TEXT_KEYS)
    if not direct_text:
        return False
    has_identity = any(_find_value(item, key) is not None for key in _ID_KEYS)
    has_metric = bool(_metrics(item))
    return len(direct_text) >= 8 or has_identity or has_metric


def _record_weight(item: dict[str, Any]) -> float:
    metrics = _metrics(item)
    return (
        sqrt(max(metrics.get("like_count", 0), 0))
        + sqrt(max(metrics.get("comment_count", 0), 0)) * 2
        + sqrt(max(metrics.get("share_count", 0), 0))
    )


def _record_freshness(item: dict[str, Any]) -> int:
    published = _first_string(item, _DATE_KEYS)
    parsed = _parse_datetime(published)
    if not parsed:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() // 3600))
    if age_hours <= 24:
        return 1000
    if age_hours <= 72:
        return 850
    if age_hours <= 168:
        return 650
    if age_hours <= 720:
        return 250
    return 1


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _first_string(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and key in _TITLE_KEYS:
            return str(value)
    for value in item.values():
        if isinstance(value, dict):
            found = _first_string(value, keys)
            if found:
                return found
    return ""


def _first_direct_string(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and key in _TITLE_KEYS:
            return str(value)
    return ""


def _source_url(platform: str, item: dict[str, Any], fallback: str = "") -> str:
    if platform == "x":
        tweet_id = _first_id(item, ("tweet_id", "id_str", "rest_id"))
        screen_name = _first_string(item, ("screen_name", "user_name"))
        if tweet_id and screen_name:
            return f"https://x.com/{screen_name}/status/{tweet_id}"
        if "/status/" in fallback:
            return fallback
    if platform == "xiaohongshu":
        note_id = _first_id(item, ("note_id", "id"))
        if note_id:
            token = _first_string(item, ("xsec_token",))
            url = f"https://www.xiaohongshu.com/explore/{note_id}"
            if token:
                url += f"?xsec_token={quote(token, safe='')}"
            return url
    if platform == "douyin":
        aweme_id = _first_id(item, ("aweme_id", "id"))
        if aweme_id:
            return f"https://www.douyin.com/video/{aweme_id}"
    return fallback if fallback.startswith("http") else ""


def _first_id(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _find_value(item, key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def _metrics(item: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in _METRIC_KEYS:
        value = _find_value(item, key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            result[_normalize_metric_key(key)] = int(value)
        elif isinstance(value, str) and value.isdigit():
            result[_normalize_metric_key(key)] = int(value)
    return result


def _find_value(item: dict[str, Any], key: str) -> Any:
    if key in item:
        return item[key]
    for value in item.values():
        if isinstance(value, dict):
            found = _find_value(value, key)
            if found is not None:
                return found
    return None


def _normalize_metric_key(key: str) -> str:
    if key in {"digg_count", "favorite_count", "favorites"}:
        return "like_count"
    if key in {"reply_count", "replies", "comments_count"}:
        return "comment_count"
    if key in {"retweets", "repost_count"}:
        return "share_count"
    if key == "bookmarks":
        return "collect_count"
    if key in {"views", "play_count"}:
        return "view_count"
    return key
