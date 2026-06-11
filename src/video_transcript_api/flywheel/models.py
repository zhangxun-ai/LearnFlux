"""Domain models for the creation flywheel.

Immutable (frozen dataclasses) and storage-agnostic. ``platform`` is a plain
string so new platforms (weixin / douyin / bilibili / youtube / reddit ...)
need no model change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class MediaType(str, Enum):
    """Content modality. Video and article never get mixed downstream."""
    VIDEO = "video"
    ARTICLE = "article"


class AnalysisStatus(str, Enum):
    """Async analysis lifecycle for one piece of content."""
    PENDING = "pending"        # 待解析
    PROCESSING = "processing"  # 解析中
    SUCCESS = "success"        # 解析成功
    FAILED = "failed"          # 解析失败


class ContentSource(str, Enum):
    """How a content row entered the system."""
    FEED = "feed"      # 来自订阅博主的内容流
    ADHOC = "adhoc"    # 临时解析的单条（博主未必订阅）


@dataclass(frozen=True)
class Blogger:
    """A creator we learn from. Subscribed or merely referenced (adhoc)."""
    id: Optional[int]
    platform: str
    platform_user_id: str
    handle: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    follower_count: int = 0
    media_types: tuple[MediaType, ...] = ()
    is_subscribed: bool = False
    pinned: bool = False
    last_post_at: Optional[datetime] = None
    subscribed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class Content:
    """One post (video or article) plus its public engagement stats."""
    id: Optional[int]
    blogger_id: int
    platform: str
    platform_item_id: str
    media_type: MediaType
    title: str
    original_url: str
    cover_url: Optional[str] = None
    published_at: Optional[datetime] = None
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    stats_synced_at: Optional[datetime] = None
    source: ContentSource = ContentSource.FEED
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING
    latest_analysis_id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class Analysis:
    """A single content's structured breakdown (video or article)."""
    id: Optional[int]
    content_id: int
    media_type: MediaType
    status: AnalysisStatus
    result_json: dict            # {"markdown": str, "sections": [...], "one_thing": str}
    error_message: Optional[str] = None
    prompt_version: Optional[int] = None
    model: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class AnalysisCost:
    """One ledger entry per analysis (estimated). Aggregated by period / blogger."""
    id: Optional[int]
    analysis_id: int
    content_id: int
    blogger_id: Optional[int]
    in_tokens: int
    out_tokens: int
    total_cost: float
    currency: str = "CNY"
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class PromptTemplate:
    """Editable analysis prompt, one active version per media type."""
    id: Optional[int]
    media_type: MediaType
    version: int
    body: str
    is_active: bool = True
    updated_at: Optional[datetime] = None
