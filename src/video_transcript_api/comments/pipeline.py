"""Pipeline for optional hot-comment insight generation."""

from dataclasses import asdict
from typing import Any

from .fetcher import TikHubCommentFetcher
from .selector import CommentItem, select_high_value_comments


def _comment_to_dict(comment: CommentItem) -> dict[str, Any]:
    return asdict(comment)


def generate_comment_insight(
    *,
    url: str,
    platform: str | None,
    media_id: str | None,
    title: str,
    author: str,
    summary_text: str | None,
    fetch_limit: int = 100,
    analysis_limit: int = 50,
    fetcher: Any | None = None,
    analyzer: Any | None = None,
) -> dict[str, Any] | None:
    """Fetch, filter and analyze a bounded hot-comment window.

    Comment insight is optional enrichment. The caller decides whether failures
    should be swallowed or propagated.
    """
    if analyzer is None:
        raise ValueError("analyzer is required")

    comment_fetcher = fetcher or TikHubCommentFetcher()
    comments = comment_fetcher.fetch_hot_comments(
        url=url,
        platform=platform,
        media_id=media_id,
        limit=fetch_limit,
    )
    selected_comments = select_high_value_comments(
        comments,
        max_items=analysis_limit,
    )
    if not selected_comments:
        return None

    insight_text = analyzer.analyze(
        title=title,
        author=author,
        summary_text=summary_text,
        comments=selected_comments,
    )
    if not insight_text:
        return None

    return {
        "insight_text": insight_text,
        "samples": [_comment_to_dict(comment) for comment in selected_comments],
        "fetched_count": len(comments),
        "selected_count": len(selected_comments),
    }
