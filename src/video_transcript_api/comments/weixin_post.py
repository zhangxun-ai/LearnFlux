"""Fetch a WeChat Official Account (公众号) article + 留言 via TikHub wechat_mp.

Verified 2026-06-09 against a real article:
- `fetch_mp_article_detail_json` -> data.title / data.author / data.content.article.full_text
- `fetch_mp_article_comment_list` -> list of {content, nick_name, content_id, reply_new...}

Returns the same shape as TwitterPost / XhsPost so it plugs into generate_post_insight.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from ..downloaders import create_downloader
from ..utils.logging import setup_logger
from .selector import CommentItem

logger = setup_logger("weixin_post_fetcher")

_ARTICLE_ENDPOINT = "/api/v1/wechat_mp/web/fetch_mp_article_detail_json"
_COMMENTS_ENDPOINT = "/api/v1/wechat_mp/web/fetch_mp_article_comment_list"


@dataclass(frozen=True)
class WeixinPost:
    """Normalized 公众号 article (shares the post fetcher attribute surface)."""

    title: str
    author: str
    thread_text: str
    comments: list[CommentItem] = field(default_factory=list)
    main_tweet_id: str = ""


class WeixinPostFetcher:
    """Fetch a 公众号 article body + 留言 for post insight."""

    def __init__(self, downloader_factory: Callable[[str], Any] = create_downloader):
        self.downloader_factory = downloader_factory

    def fetch(self, url: str, media_id: str = "", max_comments: int = 80) -> WeixinPost:
        downloader = self.downloader_factory(url)
        data = self._data(downloader.make_api_request(_ARTICLE_ENDPOINT, {"url": url}))

        title = (self._dig(data, ("title",)) or "").strip()
        author = (
            self._dig(data, ("author",))
            or self._dig(data, ("content", "article", "author"))
            or "unknown"
        ).strip()
        full_text = (self._dig(data, ("content", "article", "full_text")) or "").strip()
        if not full_text:
            full_text = self._join_sections(data)

        if not full_text and not title:
            raise ValueError("无法获取公众号文章正文")

        comments = self._fetch_comments(downloader, url, max_comments)
        logger.info(
            f"Fetched weixin article: author=@{author}, "
            f"text_len={len(full_text)}, comments={len(comments)}"
        )
        return WeixinPost(
            title=title or "公众号文章",
            author=author,
            thread_text=full_text,
            comments=comments,
            main_tweet_id=media_id,
        )

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _data(response: Any) -> Any:
        if not isinstance(response, dict):
            raise ValueError("公众号 API 返回无效响应")
        if response.get("code") not in (None, 0, 200) and not response.get("success", True):
            raise ValueError(response.get("message") or response.get("msg") or "公众号 API 返回错误")
        return response.get("data", response)

    @staticmethod
    def _dig(obj: Any, path: tuple[str, ...]) -> Any:
        cur = obj
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur if isinstance(cur, str) else (cur if cur is not None else None)

    def _join_sections(self, data: Any) -> str:
        """Fallback: assemble body from content.article.sections[].text."""
        article = data.get("content", {}).get("article", {}) if isinstance(data, dict) else {}
        sections = article.get("sections") if isinstance(article, dict) else None
        if not isinstance(sections, list):
            return ""
        parts = []
        for sec in sections:
            if isinstance(sec, dict):
                t = sec.get("title")
                body = sec.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
                if isinstance(body, str) and body.strip():
                    parts.append(body.strip())
        return "\n\n".join(parts)

    def _fetch_comments(self, downloader: Any, url: str, max_comments: int) -> list[CommentItem]:
        """Best-effort 留言 via fetch_mp_article_comment_list; [] on failure."""
        try:
            response = downloader.make_api_request(_COMMENTS_ENDPOINT, {"url": url})
            data = response.get("data", response) if isinstance(response, dict) else response
            raw = data if isinstance(data, list) else self._find_comment_list(data)
            items: list[CommentItem] = []
            for rank, c in enumerate(raw[:max_comments]):
                if not isinstance(c, dict):
                    continue
                text = (c.get("content") or "").strip() if isinstance(c.get("content"), str) else ""
                if not text:
                    continue
                items.append(
                    CommentItem(
                        text=text,
                        like_count=self._as_int(c.get("like_num") or c.get("like_count")),
                        reply_count=self._as_int(
                            (c.get("reply_new") or {}).get("reply_total_cnt")
                            if isinstance(c.get("reply_new"), dict) else 0
                        ),
                        user_nickname=str(c.get("nick_name") or c.get("nickname") or "anonymous").strip(),
                        comment_id=str(c.get("content_id") or c.get("id") or ""),
                        platform_rank=rank,
                    )
                )
            logger.info(f"Fetched weixin comments: count={len(items)}")
            return items
        except Exception as exc:
            logger.warning(f"weixin comments fetch failed: {exc}")
            return []

    def _find_comment_list(self, obj: Any) -> list[dict[str, Any]]:
        if isinstance(obj, dict):
            for key in ("comments", "comment_list", "list", "data", "items"):
                value = obj.get(key)
                if isinstance(value, list) and any(isinstance(x, dict) and "content" in x for x in value):
                    return [x for x in value if isinstance(x, dict)]
            for value in obj.values():
                found = self._find_comment_list(value)
                if found:
                    return found
        elif isinstance(obj, list):
            if any(isinstance(x, dict) and "content" in x for x in obj):
                return [x for x in obj if isinstance(x, dict)]
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
