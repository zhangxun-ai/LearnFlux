"""Long-running task progress reminders."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..context import (
    get_cache_manager,
    get_config,
    get_llm_queue,
    get_logger,
    get_transcription_control_database,
    get_workspace_dir,
)
from .post_asr import dispatch_pending_post_asr
from ...utils.notifications import get_notification_router
from ...utils.rendering import get_base_url

logger = get_logger()

DEFAULT_THRESHOLDS_MINUTES = [10, 30, 60]
DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_STALE_TASK_TIMEOUT_MINUTES = 120


def _parse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_minutes(task: dict, now: datetime) -> Optional[float]:
    created_at = _parse_datetime(task.get("created_at"))
    if not created_at:
        return None
    elapsed = now.astimezone(timezone.utc) - created_at
    return max(0.0, elapsed.total_seconds() / 60)


def due_reminder_marker(
    task: dict,
    *,
    now: Optional[datetime] = None,
    thresholds_minutes: Optional[Iterable[int]] = None,
) -> Optional[str]:
    """Return the highest due, unsent reminder marker for a task."""
    current_time = now or datetime.now(timezone.utc)
    elapsed = _elapsed_minutes(task, current_time)
    if elapsed is None:
        return None

    sent = set(task.get("progress_reminders") or [])
    thresholds = sorted(thresholds_minutes or DEFAULT_THRESHOLDS_MINUTES)
    due = [minutes for minutes in thresholds if elapsed >= minutes]
    if not due:
        return None

    for minutes in reversed(due):
        marker = f"{minutes}m"
        if marker not in sent:
            return marker
    return None


def _has_feishu_channel(router) -> bool:
    return any(
        getattr(channel, "name", None) == "feishu"
        for channel in getattr(router, "channels", [])
    )


def _format_minutes(minutes: float) -> str:
    rounded = int(minutes)
    if rounded < 60:
        return f"{rounded} 分钟"
    hours = rounded // 60
    rest = rounded % 60
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"


def _format_eta(progress: dict) -> str:
    eta = progress.get("eta_seconds")
    if eta is None:
        return "暂无可靠估计"
    seconds = int(eta)
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    rest = seconds % 60
    return f"{minutes} 分 {rest} 秒" if rest else f"{minutes} 分"


def format_progress_reminder(task: dict, marker: str, *, now: datetime) -> str:
    progress = task.get("progress") or {}
    elapsed = _elapsed_minutes(task, now) or 0
    view_token = task.get("view_token")
    view_url = f"{get_base_url()}/view/{view_token}" if view_token else ""
    stage = progress.get("stage_label") or progress.get("stage") or task.get("status")
    percent = progress.get("percent")
    percent_text = f"{percent}%" if percent is not None else "暂无百分比"

    lines = [
        "【视频转录长任务提醒】",
        f"阈值：{marker}",
        f"已运行：{_format_minutes(elapsed)}",
        f"标题：{task.get('title') or '未命名任务'}",
        f"当前阶段：{stage}（{percent_text}）",
        f"进度依据：{progress.get('basis') or 'stage_transition'}",
        f"置信度：{progress.get('confidence') or 'low'}",
        f"预计剩余：{_format_eta(progress)}",
    ]
    if view_url:
        lines.append(f"查看链接：{view_url}")
    if task.get("url"):
        lines.append(f"原始链接：{task.get('url')}")
    return "\n".join(lines)


def send_due_progress_reminders(
    *,
    cache_manager,
    router,
    now: Optional[datetime] = None,
    thresholds_minutes: Optional[Iterable[int]] = None,
) -> int:
    """Send due Feishu reminders and mark successful markers as sent."""
    if not _has_feishu_channel(router):
        return 0

    current_time = now or datetime.now(timezone.utc)
    sent_count = 0
    for task in cache_manager.list_active_tasks_for_progress_reminders():
        marker = due_reminder_marker(
            task,
            now=current_time,
            thresholds_minutes=thresholds_minutes,
        )
        if not marker:
            continue

        content = format_progress_reminder(task, marker, now=current_time)
        results = router.send_text(
            content,
            channel_name="feishu",
            allow_fallback=False,
        )
        if results.get("feishu"):
            cache_manager.mark_progress_reminder_sent(task["task_id"], marker)
            sent_count += 1

    return sent_count


def recover_stale_tasks_if_enabled(
    cache_manager, timeout_minutes, *, protected_task_ids=()
) -> int:
    """Recover stuck active tasks when heartbeat timeout is enabled."""
    try:
        timeout = int(timeout_minutes)
    except (TypeError, ValueError):
        timeout = 0
    if timeout <= 0:
        return 0
    return cache_manager.recover_stale_tasks(
        timeout, protected_task_ids=protected_task_ids
    )


def _get_reminder_settings():
    progress_config = get_config().get("task_progress", {})
    thresholds = progress_config.get(
        "reminder_threshold_minutes",
        DEFAULT_THRESHOLDS_MINUTES,
    )
    poll_interval = progress_config.get(
        "reminder_poll_interval_seconds",
        DEFAULT_POLL_INTERVAL_SECONDS,
    )
    stale_timeout = progress_config.get(
        "stale_task_timeout_minutes",
        DEFAULT_STALE_TASK_TIMEOUT_MINUTES,
    )
    enabled = progress_config.get("feishu_reminders_enabled", True)
    return enabled, thresholds, poll_interval, stale_timeout


async def process_progress_reminders():
    """Background loop for Feishu long-running task reminders."""
    logger.info("启动任务进度提醒处理器")
    while True:
        try:
            enabled, thresholds, poll_interval, stale_timeout = _get_reminder_settings()
            cache_manager = get_cache_manager()
            from ...transcriber.usage_repository import UsageEventRepository

            usage_repository = UsageEventRepository(
                get_transcription_control_database(cache_manager)
            )
            protected_task_ids = usage_repository.list_protected_task_ids()
            recover_stale_tasks_if_enabled(
                cache_manager,
                stale_timeout,
                protected_task_ids=protected_task_ids,
            )
            dispatch_pending_post_asr(
                repository=usage_repository,
                output_dir=get_workspace_dir(),
                cache_manager=cache_manager,
                llm_queue=get_llm_queue(),
            )
            if enabled:
                send_due_progress_reminders(
                    cache_manager=cache_manager,
                    router=get_notification_router(),
                    thresholds_minutes=thresholds,
                )
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("任务进度提醒处理器已停止")
            raise
        except Exception as exc:
            logger.exception(f"任务进度提醒处理器异常: {exc}")
            await asyncio.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
