"""Service facade for manual trend radar reports."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from ..tikhub import (
    TikHubAuthError,
    TikHubClient,
    TikHubPaymentRequiredError,
    TikHubRateLimitError,
)
from ..utils.logging import load_config, setup_logger
from .budget import BudgetLedger
from .collector import TikHubTrendCollector
from .synthesizer import TrendRadarSynthesizer

logger = setup_logger("trend_radar_service")

_PLACEHOLDER_KEYS = {
    "",
    "your-tikhub-api-key-here",
    "your-llm-api-key-here",
    "请替换为您的实际API密钥",
}
_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trend-radar")
_JOB_LOCK = Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 20


class TrendRadarConfigError(ValueError):
    """Trend radar cannot run because required config is missing."""


def start_report_job(*, budget_usd: float = 5.0, mode: str = "standard") -> dict[str, Any]:
    job_id = f"trend-job-{uuid4().hex[:12]}"
    job = {
        "job_id": job_id,
        "status": "queued",
        "budget_usd": float(budget_usd),
        "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _JOB_LOCK:
        _JOBS[job_id] = job
        _prune_jobs()
    _JOB_EXECUTOR.submit(_run_report_job, job_id, float(budget_usd), mode)
    return _public_job(job)


def get_report_job(job_id: str) -> dict[str, Any] | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return _public_job(job) if job else None


def run_report(*, budget_usd: float = 5.0, mode: str = "standard") -> dict[str, Any]:
    config = load_config()
    radar_config = config.get("trend_radar", {})
    max_budget = float(radar_config.get("max_run_budget_usd", 5.0))
    budget = float(budget_usd or max_budget)
    if budget > max_budget:
        raise TrendRadarConfigError(f"单次趋势雷达预算不能超过 ${max_budget:g}")

    tikhub_config = config.get("tikhub", {})
    if not _configured_key(tikhub_config.get("api_key")):
        raise TrendRadarConfigError("TikHub API key 未配置，无法触发真实趋势采集")

    llm_reserved = _llm_reserved_budget(config, radar_config, budget)
    request_cost = float(radar_config.get("request_cost_usd", 0.01))
    ledger = BudgetLedger(
        limit_usd=budget,
        request_cost_usd=request_cost,
        llm_reserved_usd=llm_reserved,
    )
    client = TikHubClient(tikhub_config)
    collector = TikHubTrendCollector(client, ledger, _collector_config(radar_config, mode))
    signals = collector.collect()
    budget_info = ledger.to_dict()
    budget_info["budget_exhausted"] = collector.budget_exhausted
    if collector.warnings:
        budget_info["collection_warnings"] = collector.warnings[:20]
    report = _build_synthesizer(config, radar_config).build_report(
        signals,
        budget=budget_info,
        generated_at=datetime.now(timezone.utc),
    )
    _save_report(report, _report_dir(radar_config))
    return report


def _run_report_job(job_id: str, budget_usd: float, mode: str) -> None:
    _update_job(
        job_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        report = run_report(budget_usd=budget_usd, mode=mode)
    except Exception as exc:
        logger.exception("Trend radar background job failed: %s", job_id)
        _update_job(
            job_id,
            status="failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
            status_code=_job_error_status(exc),
        )
        return
    _update_job(
        job_id,
        status="completed",
        finished_at=datetime.now(timezone.utc).isoformat(),
        report_id=report.get("report_id"),
        report=report,
        budget=report.get("budget") or {},
    )


def _update_job(job_id: str, **changes: Any) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(changes)


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in job.items()
        if key not in {"report"}
    }
    if job.get("status") == "completed" and isinstance(job.get("report"), dict):
        public["report"] = job["report"]
    return public


def _prune_jobs() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    ordered = sorted(_JOBS.values(), key=lambda item: str(item.get("created_at") or ""))
    for job in ordered[: max(0, len(_JOBS) - _MAX_JOBS)]:
        _JOBS.pop(str(job.get("job_id")), None)


def _job_error_status(exc: Exception) -> int:
    if isinstance(exc, TrendRadarConfigError):
        return 400
    if isinstance(exc, TikHubAuthError):
        return 401
    if isinstance(exc, TikHubPaymentRequiredError):
        return 402
    if isinstance(exc, TikHubRateLimitError):
        return 429
    return 502


def latest_report() -> dict[str, Any] | None:
    radar_config = load_config().get("trend_radar", {})
    latest = _report_dir(radar_config) / "latest.json"
    if not latest.exists():
        return None
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Trend radar latest report is invalid JSON: %s", latest)
        return None
    return data if isinstance(data, dict) else None


def list_reports(limit: int = 10) -> dict[str, Any]:
    radar_config = load_config().get("trend_radar", {})
    report_dir = _report_dir(radar_config)
    reports = []
    if not report_dir.exists():
        return {"items": [], "total": 0}

    for path in report_dir.glob("trend-*.json"):
        report = _read_report_path(path)
        if not report:
            continue
        items = report.get("items") if isinstance(report.get("items"), list) else []
        reports.append(
            {
                "report_id": report.get("report_id") or path.stem,
                "generated_at": report.get("generated_at"),
                "summary": report.get("summary") or {},
                "metrics": report.get("metrics") or {},
                "budget": report.get("budget") or {},
                "raw_signal_count": report.get("raw_signal_count", 0),
                "top_titles": [
                    item.get("title")
                    for item in items[:3]
                    if isinstance(item, dict) and item.get("title")
                ],
            }
        )

    reports.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    safe_limit = max(1, min(int(limit or 10), 30))
    return {"items": reports[:safe_limit], "total": len(reports)}


def read_report(report_id: str) -> dict[str, Any] | None:
    if not report_id or "/" in report_id or "\\" in report_id:
        return None
    radar_config = load_config().get("trend_radar", {})
    path = _report_dir(radar_config) / f"{report_id}.json"
    return _read_report_path(path)


def _collector_config(radar_config: dict[str, Any], mode: str) -> dict[str, Any]:
    defaults = {
        "sources": ("x", "xiaohongshu", "douyin"),
        "max_keywords_per_topic": 3 if mode == "standard" else 2,
        "max_items_per_call": 25 if mode == "standard" else 12,
        "x_country": "UnitedStates",
    }
    merged = {**defaults, **(radar_config.get("collector") or {})}
    if radar_config.get("topics"):
        merged["topics"] = radar_config["topics"]
    return merged


def _build_synthesizer(config: dict[str, Any], radar_config: dict[str, Any]) -> TrendRadarSynthesizer:
    llm_config = config.get("llm", {})
    if not _configured_key(llm_config.get("api_key")) or not llm_config.get("base_url"):
        return TrendRadarSynthesizer()
    try:
        from ..api.context import get_llm_coordinator

        coord = get_llm_coordinator()
        return TrendRadarSynthesizer(
            llm_client=coord.llm_client,
            model=radar_config.get("llm_model") or coord.config.summary_model,
            reasoning_effort=radar_config.get("llm_reasoning_effort")
            or getattr(coord.config, "summary_reasoning_effort", None),
        )
    except Exception as exc:
        logger.warning("Trend radar LLM unavailable, using heuristic synthesis: %s", exc)
    return TrendRadarSynthesizer()


def _llm_reserved_budget(
    config: dict[str, Any],
    radar_config: dict[str, Any],
    budget: float,
) -> float:
    llm_config = config.get("llm", {})
    if not _configured_key(llm_config.get("api_key")) or not llm_config.get("base_url"):
        return 0.0
    configured = float(radar_config.get("llm_reserved_usd", 0.2))
    ratio_cap = float(radar_config.get("llm_reserved_max_ratio", 0.1))
    return round(min(configured, max(budget * ratio_cap, 0.1), budget), 4)


def _save_report(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_id = str(report.get("report_id") or "latest")
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    (report_dir / f"{report_id}.json").write_text(payload, encoding="utf-8")
    (report_dir / "latest.json").write_text(payload, encoding="utf-8")


def _read_report_path(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Trend radar report is invalid JSON: %s", path)
        return None
    return data if isinstance(data, dict) else None


def _report_dir(radar_config: dict[str, Any]) -> Path:
    return Path(radar_config.get("report_dir") or "./data/trend_radar/reports")


def _configured_key(value: Any) -> bool:
    return str(value or "").strip() not in _PLACEHOLDER_KEYS
