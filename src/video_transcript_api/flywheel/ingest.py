"""Ingest service: fetch a blogger's posts and persist them.

Orchestrates fetcher -> repositories. Depends only on the repository Protocols
and a ``fetch`` callable (both injectable), so it is unit-testable without
network and storage-agnostic.

Key rule (per spec): subscribing pulls the feed but does NOT auto-analyze —
every content row lands as ``pending``; the user decides what to analyze.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..utils.logging import setup_logger
from .fetchers import FetchedItem, FetchResult
from .fetchers import fetch_blogger as default_fetch
from .models import Blogger, Content, ContentSource
from .repositories import BloggerRepository, ContentRepository

logger = setup_logger("flywheel_ingest")


@dataclass(frozen=True)
class IngestResult:
    blogger: Blogger
    ingested: int


def _to_content(item: FetchedItem, blogger: Blogger, source: ContentSource) -> Content:
    return Content(
        id=None,
        blogger_id=blogger.id,
        platform=blogger.platform,
        platform_item_id=item.platform_item_id,
        media_type=item.media_type,
        title=item.title,
        original_url=item.original_url,
        cover_url=item.cover_url,
        published_at=item.published_at,
        like_count=item.like_count,
        collect_count=item.collect_count,
        comment_count=item.comment_count,
        share_count=item.share_count,
        source=source,
    )


def ingest_blogger(
    url: str,
    *,
    subscribe: bool,
    blogger_repo: BloggerRepository,
    content_repo: ContentRepository,
    max_items: int = 20,
    fetch=default_fetch,
) -> IngestResult:
    """Fetch ``url``'s blogger + recent posts and upsert them.

    ``subscribe=True`` marks the blogger subscribed and content as ``feed``;
    ``subscribe=False`` is a one-off (``adhoc``). Content is never auto-analyzed.
    """
    result: FetchResult = fetch(url, max_items=max_items)
    blogger = blogger_repo.upsert(replace(result.blogger, is_subscribed=subscribe))
    source = ContentSource.FEED if subscribe else ContentSource.ADHOC

    ingested = 0
    for item in result.items:
        content_repo.upsert(_to_content(item, blogger, source))
        ingested += 1

    logger.info(f"ingested blogger={blogger.platform_user_id}, items={ingested}, "
                f"subscribe={subscribe}")
    return IngestResult(blogger=blogger, ingested=ingested)
