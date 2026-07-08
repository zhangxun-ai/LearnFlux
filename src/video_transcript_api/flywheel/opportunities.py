"""Opportunity scoring for already analyzed flywheel content."""

from __future__ import annotations

from datetime import datetime
from math import sqrt
from typing import Any

from .models import Content

_TYPE_PATTERNS = {
    "product": ("工具", "软件", "插件", "脚本", "自动化", "api", "产品", "入口"),
    "template": ("模板", "清单", "步骤", "框架", "公式", "复制"),
}


def build_opportunity(
    content: Content,
    analysis_result: dict[str, Any] | None,
    *,
    blogger_handle: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a ranked opportunity card from persisted content + analysis."""
    result = analysis_result or {}
    text = _analysis_text(result)
    engagement_score = _engagement_score(content)
    analysis_score = _analysis_score(result, text)
    recency_score = _recency_score(content, now or datetime.now())
    score = min(100, engagement_score + analysis_score + recency_score)

    return {
        "content_id": content.id,
        "blogger_id": content.blogger_id,
        "blogger_handle": blogger_handle,
        "platform": content.platform,
        "media_type": content.media_type.value,
        "title": content.title,
        "original_url": content.original_url,
        "score": score,
        "level": _level(score),
        "opportunity_type": _opportunity_type(text),
        "reason": _reason(content, analysis_score, recency_score),
        "evidence": _evidence(result),
        "next_action": _next_action(result, content),
        "stats": {
            "like_count": content.like_count,
            "collect_count": content.collect_count,
            "comment_count": content.comment_count,
            "share_count": content.share_count,
        },
        "published_at": content.published_at.isoformat() if content.published_at else None,
    }


def _engagement_score(content: Content) -> int:
    weighted = (
        max(content.like_count, 0)
        + max(content.collect_count, 0) * 2
        + max(content.comment_count, 0) * 3
        + max(content.share_count, 0) * 2
    )
    return min(45, int(sqrt(weighted) * 0.55))


def _analysis_score(result: dict[str, Any], text: str) -> int:
    score = 0
    if (result.get("one_thing") or "").strip():
        score += 18
    if "可复制" in text or "模板" in text:
        score += 15
    if "下一条" in text or "下一篇" in text or "选题" in text:
        score += 12
    if "机会" in text or "需求" in text:
        score += 10
    return min(score, 35)


def _recency_score(content: Content, now: datetime) -> int:
    if not content.published_at:
        return 0
    age_days = max((now - content.published_at).days, 0)
    if age_days <= 7:
        return 20
    if age_days <= 30:
        return 12
    if age_days <= 90:
        return 6
    return 0


def _analysis_text(result: dict[str, Any]) -> str:
    parts = [str(result.get("one_thing") or "")]
    for section in result.get("sections") or []:
        if isinstance(section, dict):
            parts.append(str(section.get("title") or ""))
            parts.append(str(section.get("body") or ""))
    return "\n".join(parts).casefold()


def _opportunity_type(text: str) -> str:
    scores = {
        name: sum(1 for pattern in patterns if pattern.casefold() in text)
        for name, patterns in _TYPE_PATTERNS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "content_angle"


def _level(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _reason(content: Content, analysis_score: int, recency_score: int) -> str:
    reasons = []
    if content.collect_count:
        reasons.append(f"收藏 {content.collect_count}，说明有复用/保存价值")
    if content.comment_count:
        reasons.append(f"评论 {content.comment_count}，说明有讨论或需求信号")
    if analysis_score >= 25:
        reasons.append("解析结果包含可复制模板或下一条方向")
    if recency_score >= 12:
        reasons.append("发布时间较近，适合快速跟进")
    return "；".join(reasons) or "互动和解析信号较弱，适合观察不急于跟进"


def _evidence(result: dict[str, Any]) -> str:
    for section in result.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "")
        body = str(section.get("body") or "")
        if any(key in title for key in ("对标价值", "机会", "可复制", "下一条", "下一篇")):
            return body[:180]
    return str(result.get("one_thing") or "")[:180]


def _next_action(result: dict[str, Any], content: Content) -> str:
    one_thing = str(result.get("one_thing") or "").strip()
    if one_thing:
        return one_thing
    kind = "下一条视频" if content.media_type.value == "video" else "下一篇图文"
    return f"先打开解析结果，基于这条内容整理一个可复用的{kind}选题。"
