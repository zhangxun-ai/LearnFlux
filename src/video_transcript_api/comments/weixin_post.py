"""Fetch WeChat Official Account articles through versioned TikHub adapters."""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from ..downloaders import create_downloader
from ..utils.logging import load_config, setup_logger
from .selector import CommentItem

logger = setup_logger("weixin_post_fetcher")

_V2_ARTICLE_ENDPOINT = "/api/v1/wechat_mp/v2/fetch_article_detail"
_V2_COMMENTS_ENDPOINT = "/api/v1/wechat_mp/v2/fetch_article_comments"
_DEFAULT_API_VERSION = "v2"


@dataclass(frozen=True)
class WeixinPost:
    """Normalized 公众号 article (shares the post fetcher attribute surface)."""

    title: str
    author: str
    thread_text: str
    comments: list[CommentItem] = field(default_factory=list)
    main_tweet_id: str = ""


@dataclass(frozen=True)
class WeixinArticlePayload:
    """Stable article fields returned by all Official Account API adapters."""

    title: str
    author: str
    text: str


class WeixinPostApiAdapter(Protocol):
    """Version-specific TikHub adapter for Official Account article data."""

    def fetch_article(self, downloader: Any, url: str) -> WeixinArticlePayload:
        """Fetch and normalize one article."""

    def fetch_comments(self, downloader: Any, url: str) -> list[dict[str, Any]]:
        """Fetch and normalize one page of comments."""


class WeixinV2PostApiAdapter:
    """TikHub WeChat Media Platform V2 contract."""

    def fetch_article(self, downloader: Any, url: str) -> WeixinArticlePayload:
        response = downloader.post_api_request(
            _V2_ARTICLE_ENDPOINT,
            {"url": url, "raw": False},
            min_timeout=30,
        )
        data = self._data(response)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, dict):
            raise ValueError("公众号文章详情缺少 content 对象")

        title = self._text(content.get("title"))
        author = (
            self._text(content.get("author"))
            or self._text(content.get("nick_name"))
            or self._text(content.get("user_name"))
            or "unknown"
        )
        text = self._text(content.get("content_text"))
        if not title and not text:
            raise ValueError("无法获取公众号文章正文")
        return WeixinArticlePayload(
            title=title or "公众号文章",
            author=author,
            text=text,
        )

    def fetch_comments(self, downloader: Any, url: str) -> list[dict[str, Any]]:
        response = downloader.post_api_request(
            _V2_COMMENTS_ENDPOINT,
            {"url": url, "buffer": "", "raw": False},
            min_timeout=30,
        )
        data = self._data(response)
        comments = data.get("comments") if isinstance(data, dict) else None
        if not isinstance(comments, list):
            return []
        return [comment for comment in comments if isinstance(comment, dict)]

    @staticmethod
    def _data(response: Any) -> Any:
        if not isinstance(response, dict):
            raise ValueError("公众号 API 返回无效响应")
        if response.get("code") not in (None, 0, 200):
            raise ValueError(
                response.get("message")
                or response.get("msg")
                or "公众号 API 返回错误"
            )
        return response.get("data", response)

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""


_API_ADAPTERS: dict[str, type[WeixinPostApiAdapter]] = {
    "v2": WeixinV2PostApiAdapter,
}


class WeixinPostFetcher:
    """Fetch a 公众号 article body + 留言 for post insight."""

    def __init__(
        self,
        downloader_factory: Callable[[str], Any] = create_downloader,
        config: Optional[dict[str, Any]] = None,
        adapter_resolver: Optional[Callable[[str], WeixinPostApiAdapter]] = None,
    ):
        self.downloader_factory = downloader_factory
        self.config = config
        self.adapter_resolver = adapter_resolver

    def fetch(
        self,
        url: str,
        media_id: str = "",
        max_comments: int = 80,
    ) -> WeixinPost:
        adapter = self._resolve_adapter()
        downloader = self.downloader_factory(url)
        article = adapter.fetch_article(downloader, url)
        comments = self._fetch_comments(adapter, downloader, url, max_comments)
        logger.info(
            f"Fetched weixin article: author=@{article.author}, "
            f"text_len={len(article.text)}, comments={len(comments)}"
        )
        return WeixinPost(
            title=article.title,
            author=article.author,
            thread_text=article.text,
            comments=comments,
            main_tweet_id=media_id,
        )

    def fetch_article(self, url: str) -> WeixinArticlePayload:
        """Fetch only the article body for non-social analysis flows."""
        adapter = self._resolve_adapter()
        downloader = self.downloader_factory(url)
        article = adapter.fetch_article(downloader, url)
        logger.info(
            f"Fetched weixin article body: author=@{article.author}, "
            f"text_len={len(article.text)}"
        )
        return article

    def _resolve_adapter(self) -> WeixinPostApiAdapter:
        config = self.config if self.config is not None else load_config()
        version = str(
            (config.get("tikhub", {}) or {}).get(
                "wechat_mp_api_version",
                _DEFAULT_API_VERSION,
            )
        ).strip().lower() or _DEFAULT_API_VERSION
        if self.adapter_resolver is not None:
            return self.adapter_resolver(version)
        adapter_class = _API_ADAPTERS.get(version)
        if adapter_class is None:
            raise ValueError(f"Unsupported WeChat MP API version: {version}")
        return adapter_class()

    def _fetch_comments(
        self,
        adapter: WeixinPostApiAdapter,
        downloader: Any,
        url: str,
        max_comments: int,
    ) -> list[CommentItem]:
        """Fetch comments as a best-effort enhancement to article analysis."""
        try:
            raw = adapter.fetch_comments(downloader, url)
            items: list[CommentItem] = []
            for rank, comment in enumerate(raw[:max_comments]):
                content = comment.get("content")
                text = content.strip() if isinstance(content, str) else ""
                if not text:
                    continue
                reply_count = comment.get("reply_total")
                if reply_count is None and isinstance(
                    comment.get("reply_new"),
                    dict,
                ):
                    reply_count = comment["reply_new"].get("reply_total_cnt")
                items.append(
                    CommentItem(
                        text=text,
                        like_count=self._as_int(
                            comment.get("like_num")
                            or comment.get("like_count")
                        ),
                        reply_count=self._as_int(reply_count),
                        user_nickname=str(
                            comment.get("nick_name")
                            or comment.get("nickname")
                            or "anonymous"
                        ).strip(),
                        comment_id=str(
                            comment.get("content_id")
                            or comment.get("id")
                            or ""
                        ),
                        platform_rank=rank,
                    )
                )
            logger.info(f"Fetched weixin comments: count={len(items)}")
            return items
        except Exception as exc:
            logger.warning(f"weixin comments fetch failed: {exc}")
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
