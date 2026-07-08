"""Shared data structures for the trend radar pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RawSignal:
    """A normalized social signal from X, Xiaohongshu or Douyin."""

    platform: str
    topic_id: str
    topic_label: str
    title: str
    text: str
    url: str = ""
    author: str = ""
    published_at: str | None = None
    metrics: dict[str, int] = field(default_factory=dict)
    source_endpoint: str = ""
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "topic_id": self.topic_id,
            "topic_label": self.topic_label,
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "author": self.author,
            "published_at": self.published_at,
            "metrics": dict(self.metrics),
            "source_endpoint": self.source_endpoint,
            "captured_at": self.captured_at.isoformat(),
        }


@dataclass(frozen=True)
class TopicSeed:
    """Keyword bundle used to sample a trend area across platforms."""

    id: str
    label: str
    x_keywords: tuple[str, ...]
    chinese_keywords: tuple[str, ...]


DEFAULT_TOPIC_SEEDS = (
    TopicSeed(
        id="agentic-workflow",
        label="AI 业务流程智能体",
        x_keywords=(
            "AI agent workflow",
            "agentic procurement",
            "enterprise AI agents",
        ),
        chinese_keywords=("AI 智能体 工作流", "AI 采购", "企业智能体"),
    ),
    TopicSeed(
        id="consumer-ai",
        label="消费级 AI 新入口",
        x_keywords=("consumer AI app", "personal AI memory", "AI companion"),
        chinese_keywords=("AI 陪伴", "个人 AI 记忆", "AI 工具"),
    ),
    TopicSeed(
        id="robotics",
        label="具身智能与机器人",
        x_keywords=("home robot teleoperation", "embodied AI", "robotics data"),
        chinese_keywords=("具身智能", "家庭机器人", "机器人 远程操控"),
    ),
    TopicSeed(
        id="glp1-lifestyle",
        label="GLP-1 后生活方式",
        x_keywords=("GLP-1 lifestyle", "GLP-1 nutrition", "weight loss drugs market"),
        chinese_keywords=("GLP-1", "减重针 饮食", "司美格鲁肽"),
    ),
)
