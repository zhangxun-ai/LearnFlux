"""Fetch WeChat Official Account text and optional comments via TikHub."""

from dataclasses import dataclass, field
from typing import Any

from ..tikhub import TikHubClient
from ..utils.logging import load_config, setup_logger
from .selector import CommentItem

logger = setup_logger("weixin_post_fetcher")

_ARTICLE_ENDPOINT = "/api/v1/wechat_mp/v2/fetch_article_detail_h5"
_COMMENTS_ENDPOINT = "/api/v1/wechat_mp/v2/fetch_article_comments"


@dataclass(frozen=True)
class WeixinPost:
    """Normalized 公众号 article (shares the post fetcher attribute surface)."""

    title: str
    author: str
    thread_text: str
    comments: list[CommentItem] = field(default_factory=list)
    main_tweet_id: str = ""


class WeixinPostFetcher:
    """Share article acquisition between deep learning and post insight."""

    def __init__(self, client: TikHubClient | None = None):
        self.client = client if client is not None else TikHubClient(load_config().get("tikhub"))

    def fetch(self, url: str, media_id: str = "", max_comments: int = 80) -> WeixinPost:
        data = self._data(self.client.post(_ARTICLE_ENDPOINT, {"url": url, "raw": False}, min_timeout=30))
        article = data.get("content")
        if not isinstance(article, dict):
            raise ValueError("公众号接口未返回文章正文")

        title = self._text(article.get("title"))
        author = self._text(article.get("author")) or self._text(article.get("nick_name")) or "unknown"
        full_text = self._text(article.get("content_text"))
        if not full_text or article.get("_content_type") in {"unknown", "video"}:
            raise ValueError("公众号文章没有可读取的正文")

        comments = self._fetch_comments(url, article.get("comment_id"), max_comments) if max_comments > 0 else []
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
    def _data(response: Any) -> dict:
        if not isinstance(response, dict):
            raise ValueError("公众号 API 返回无效响应")
        if response.get("code") not in (None, 0, 200) or response.get("success") is False:
            raise ValueError(response.get("message_zh") or response.get("message") or "公众号 API 返回错误")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ValueError("公众号 API 未返回有效内容")
        return data

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _fetch_comments(self, url: str, comment_id: Any, max_comments: int) -> list[CommentItem]:
        """Fetch the first page of selected comments, if available."""
        try:
            payload = {"url": url}
            if comment_id:
                payload["comment_id"] = str(comment_id)
            data = self._data(self.client.post(_COMMENTS_ENDPOINT, payload))
            raw = self._find_comment_list(data)
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
