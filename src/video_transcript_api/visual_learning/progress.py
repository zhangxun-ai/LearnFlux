"""Compose source and generation progress into one monotonic workflow."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


_GENERATION_STARTS = {
    "analyzing_outline": 55.0,
    "selecting_evidence": 70.0,
    "generating_visual": 75.0,
    "planning_visual": 70.0,
    "validating": 95.0,
    "completed": 100.0,
}


def _units(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    completed = payload.get("completed_units")
    total = payload.get("total_units")
    if completed is None or total is None:
        evidence = payload.get("evidence") or {}
        completed = evidence.get("completed_segments")
        total = evidence.get("total_segments")
    if not isinstance(completed, (int, float)) or not isinstance(total, (int, float)):
        return None, None
    if total <= 0:
        return None, None
    return int(completed), int(total)


def _fraction(completed: int | None, total: int | None) -> float | None:
    if completed is None or total is None or total <= 0:
        return None
    return max(0.0, min(1.0, completed / total))


def _parse_updated_at(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _soft_llm_stage_percent(base: float, payload: dict[str, Any], *, ceiling: float = 93.5) -> float:
    """Gently advance during long LLM stages so the UI is not frozen at a fixed percent.

    This never claims completion: it asymptotes below ``ceiling`` until a real
    stage transition (validating/completed) arrives.
    """
    started = _parse_updated_at(payload.get("updated_at"))
    if started is None:
        return base
    elapsed = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
    # ~2 minutes to approach the soft ceiling for typical multi-page diagrams.
    advanced = base + ((ceiling - base) * (1.0 - math.exp(-elapsed / 120.0)))
    return min(ceiling, max(base, advanced))


def _generation_percent(stage: str, payload: dict[str, Any]) -> float:
    effective_stage = payload.get("previous_stage") if stage == "failed" else stage
    start = _GENERATION_STARTS.get(str(effective_stage), 55.0)
    completed, total = _units(payload)
    fraction = _fraction(completed, total)
    if effective_stage == "selecting_evidence" and fraction is not None:
        return 70.0 + (5.0 * fraction)
    if effective_stage == "validating" and fraction is not None:
        return 95.0 + (4.0 * fraction)
    # Long-running LLM call: keep progress moving so clients do not appear stuck.
    if str(effective_stage) == "generating_visual":
        return _soft_llm_stage_percent(start, payload, ceiling=93.5)
    if str(effective_stage) == "planning_visual":
        return _soft_llm_stage_percent(start, payload, ceiling=74.0)
    return start


def compose_workflow_progress(
    phase: str,
    source_progress: dict[str, Any] | None,
    generation_progress: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return one bounded workflow progress payload without time-based guesses."""
    source = source_progress or {}
    generation = generation_progress or {}
    payload = generation if generation else source
    stage = str(payload.get("stage") or phase or "source_processing")
    completed, total = _units(payload)
    fraction = _fraction(completed, total)

    if phase == "completed" or stage == "completed":
        overall = 100.0
        stage = "completed"
    elif generation:
        overall = _generation_percent(stage, generation)
    elif stage == "ready_for_generation" or phase == "ready_for_generation":
        overall = 55.0
        stage = "ready_for_generation"
    elif stage == "waiting_analysis":
        overall = 18.0 + (37.0 * fraction if fraction is not None else 0.0)
    elif stage == "assessing_quality":
        overall = 15.0 + (3.0 * fraction if fraction is not None else 0.0)
    elif stage in {"failed", "canceled"}:
        overall = 18.0
    else:
        raw_percent = source.get("percent")
        if isinstance(raw_percent, (int, float)):
            overall = 5.0 + (10.0 * max(0.0, min(94.0, raw_percent)) / 94.0)
        else:
            overall = 5.0

    return {
        "stage": stage,
        "stage_label": payload.get("stage_label")
        or payload.get("message")
        or "正在处理",
        "overall_percent": round(max(0.0, min(100.0, overall)), 1),
        "phase_percent": round(fraction * 100, 1) if fraction is not None else None,
        "completed_units": completed,
        "total_units": total,
        "updated_at": payload.get("updated_at"),
        "basis": payload.get("basis") or (
            "measured_units" if fraction is not None else "stage_transition"
        ),
    }
