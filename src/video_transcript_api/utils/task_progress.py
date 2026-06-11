"""Task progress helpers.

Progress values are derived from explicit stage transitions or measurable
evidence such as downloaded bytes and ASR server progress. The helpers avoid
time-only fake progress.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


STAGE_RANGES = {
    "queued": (0, 0),
    "url_parsing": (2, 6),
    "cache_check": (6, 10),
    "metadata": (10, 12),
    "downloading": (12, 32),
    "transcribing": (30, 94),
    "calibrating": (94, 95),
    "comment_insight": (94, 95),
    "notifying": (95, 95),
    "completed": (100, 100),
    "failed": (0, 95),
}

DEFAULT_STAGE_LABELS = {
    "queued": "任务排队中",
    "url_parsing": "正在解析链接",
    "cache_check": "正在检查缓存",
    "metadata": "正在获取视频信息",
    "downloading": "正在下载音视频",
    "transcribing": "正在转录音视频",
    "calibrating": "正在校对和总结",
    "comment_insight": "正在生成评论洞察",
    "notifying": "正在发送通知",
    "completed": "任务已完成",
    "failed": "任务处理失败",
}


def clamp_fraction(fraction: Optional[float]) -> Optional[float]:
    """Clamp a progress fraction into [0, 1]."""
    if fraction is None:
        return None
    try:
        numeric = float(fraction)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, numeric))


def compose_overall_percent(stage: str, fraction: Optional[float]) -> int:
    """Map a stage-local fraction to the overall task percent."""
    start, end = STAGE_RANGES.get(stage, (0, 95))
    if stage == "completed":
        return 100

    local_fraction = clamp_fraction(fraction)
    if local_fraction is None:
        percent = start
    else:
        percent = start + (end - start) * local_fraction

    return int(round(min(95, percent)))


def estimate_eta_seconds(
    *,
    completed: Optional[float],
    total: Optional[float],
    elapsed_seconds: Optional[float],
) -> Optional[int]:
    """Estimate remaining seconds from measurable completed/total work."""
    if not completed or not total or not elapsed_seconds:
        return None
    if completed <= 0 or total <= 0 or completed > total:
        return None

    rate = completed / elapsed_seconds
    if rate <= 0:
        return None

    return int(round((total - completed) / rate))


def build_progress(
    *,
    stage: str,
    stage_label: Optional[str] = None,
    fraction: Optional[float] = None,
    basis: str = "stage_transition",
    confidence: str = "low",
    evidence: Optional[Dict[str, Any]] = None,
    eta_seconds: Optional[int] = None,
    message: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a normalized progress payload."""
    current_time = now or datetime.now(timezone.utc)
    progress: Dict[str, Any] = {
        "stage": stage,
        "stage_label": stage_label or DEFAULT_STAGE_LABELS.get(stage, stage),
        "percent": compose_overall_percent(stage, fraction),
        "basis": basis,
        "confidence": confidence,
        "updated_at": current_time.isoformat(),
    }

    if evidence:
        progress["evidence"] = evidence
    if eta_seconds is not None:
        progress["eta_seconds"] = eta_seconds
    if message:
        progress["message"] = message

    return progress
