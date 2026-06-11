"""Orchestrate X / Twitter post insight.

Pipeline: parse URL -> fetch author thread + replies -> select high-value
replies -> credibility-aware LLM analysis. This is an independent flow that
reuses leaf units (selector, analyzer infra); it does NOT touch the video
transcription pipeline.
"""

from dataclasses import asdict, dataclass
from typing import Any, Optional

from ...comments.post_analyzer import PostInsightAnalyzer
from ...comments.selector import CommentItem, select_high_value_comments
from ...comments.twitter_post import TwitterPostFetcher
from ...comments.weixin_post import WeixinPostFetcher
from ...comments.xiaohongshu_post import XhsPostFetcher
from ...utils.logging import setup_logger
from ...utils.url_parser import URLParser

logger = setup_logger("post_insight_service")

# Platform → fetcher class. Each fetcher.fetch(url, media_id) returns an object
# exposing title / author / thread_text / comments. Add platforms here.
_FETCHERS = {
    "twitter": TwitterPostFetcher,
    "xiaohongshu": XhsPostFetcher,
    "weixin": WeixinPostFetcher,
}
_SUPPORTED_PLATFORMS = set(_FETCHERS)


@dataclass(frozen=True)
class PostInsightResult:
    """Result of analyzing a social post and its replies."""

    platform: str
    source_url: str
    author: str
    title: str
    thread_text: str
    insight_markdown: str
    comment_samples: list[dict[str, Any]]
    fetched_comment_count: int


def generate_post_insight(
    url: str,
    *,
    analyzer: PostInsightAnalyzer,
    post_fetcher: Optional[TwitterPostFetcher] = None,
    url_parser: Optional[URLParser] = None,
    analysis_limit: int = 50,
) -> PostInsightResult:
    """Analyze an X post (author thread + high-value replies).

    Args:
        url: Original post URL.
        analyzer: Configured PostInsightAnalyzer (LLM client + model injected by caller).
        post_fetcher: Injectable fetcher (defaults to TikHub-backed TwitterPostFetcher).
        url_parser: Injectable URL parser.
        analysis_limit: Max replies kept for analysis (LLM cost control).

    Returns:
        PostInsightResult with the rendered insight markdown and reply samples.

    Raises:
        ValueError: Unsupported platform, or the analyzer produced no insight.
    """
    parser = url_parser or URLParser()
    parsed = parser.parse(url)
    if parsed.platform not in _SUPPORTED_PLATFORMS:
        raise ValueError(
            f"Post insight is not supported for platform: {parsed.platform}"
        )

    fetcher = post_fetcher or _FETCHERS[parsed.platform]()
    post = fetcher.fetch(parsed.normalized_url, parsed.video_id)

    selected = select_high_value_comments(post.comments, max_items=analysis_limit)

    # PostInsightAnalyzer tolerates an empty reply list: a post with no replies
    # is still analyzed on its content alone.
    insight = analyzer.analyze(
        title=post.title,
        author=post.author,
        summary_text=post.thread_text,
        comments=selected,
    )
    if not insight:
        raise ValueError("Failed to generate post insight")

    logger.info(
        f"Post insight generated: platform={parsed.platform}, author=@{post.author}, "
        f"fetched={len(post.comments)}, analyzed={len(selected)}"
    )
    return PostInsightResult(
        platform=parsed.platform,
        source_url=parsed.normalized_url,
        author=post.author,
        title=post.title,
        thread_text=post.thread_text,
        insight_markdown=insight,
        comment_samples=[_comment_to_dict(c) for c in selected],
        fetched_comment_count=len(post.comments),
    )


def _comment_to_dict(comment: CommentItem) -> dict[str, Any]:
    return asdict(comment)
