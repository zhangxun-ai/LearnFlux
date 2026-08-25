"""LLM 队列处理与任务执行模块

从 transcription.py 拆分而来，负责：
- LLM 队列消费 (process_llm_queue)
- 单个 LLM 任务处理 (_handle_llm_task)
  - 标题生成（通用下载器场景）
  - LLM 协调器调用（校对+总结）
  - 结果缓存保存
  - 企微通知发送
"""

import time
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from ..context import (
    get_cache_manager,
    get_config,
    get_llm_coordinator,
    get_llm_executor,
    get_llm_queue,
    get_logger,
    get_transcription_control_database,
    task_lock,
)
from ...comments import CommentInsightAnalyzer, generate_comment_insight
from ...llm import call_llm_api
from ...utils.notifications import (
    WechatNotifier,
    send_long_text_wechat,
    format_llm_config_markdown,
    get_notification_router,
)
from ...utils.notifications.channel import _clean_url, _apply_risk_control_safe
from ...utils.rendering import get_base_url, normalize_markdown_text
from ...utils.perf_tracker import PerfTracker
from ...utils.task_status import TaskStatus
from ...transcriber.usage_repository import UsageEventRepository

logger = get_logger()
config = get_config()
cache_manager = get_cache_manager()
llm_coordinator = get_llm_coordinator()
llm_task_queue = get_llm_queue()
llm_executor = get_llm_executor()

_SUMMARY_RETRY_DELAYS_SECONDS = (60, 300, 1800)


class _PostprocessHeartbeat:
    """Keep one durable postprocess claim alive while LLM work blocks."""

    def __init__(self, repository, event_id: str, owner: str) -> None:
        self.repository = repository
        self.event_id = event_id
        self.owner = owner
        self.stop_event = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(20):
            try:
                if not self.repository.heartbeat_postprocess(
                    self.event_id, self.owner, now=datetime.now(UTC)
                ):
                    self.lost.set()
                    return
            except Exception:
                self.lost.set()
                return

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()


def _safe_update_progress(task_id: str, **kwargs):
    """Best-effort task progress update; progress must not break LLM work."""
    try:
        return cache_manager.update_task_progress(task_id, **kwargs)
    except Exception as exc:
        logger.debug(f"task progress update failed: {task_id}, error={exc}")
        return None


def _document_quality_payload(llm_task: dict) -> dict | None:
    """Whitelist bounded document-quality fields before persistence."""
    raw = llm_task.get("document_quality")
    if not isinstance(raw, dict):
        return None
    metrics = raw.get("metrics")
    reasons = raw.get("reasons")
    return {
        "mode": str(raw.get("mode") or "fallback"),
        "reasons": [str(reason) for reason in reasons] if isinstance(reasons, list) else [],
        "metrics": dict(metrics) if isinstance(metrics, dict) else {},
    }


def _progress_evidence(llm_task: dict, **extra) -> dict:
    evidence = {}
    quality = _document_quality_payload(llm_task)
    if quality is not None:
        evidence["document_quality"] = quality
    evidence.update(extra)
    return evidence


def _fallback_stage_label(llm_task: dict, default: str) -> str:
    return (
        "检测到提取质量问题，正在进行完整校对"
        if _document_quality_payload(llm_task) is not None
        else default
    )


def _terminal_evidence(llm_task: dict) -> dict | None:
    quality = _document_quality_payload(llm_task)
    if quality is None:
        return None
    return {
        "analysis_mode": "document_fallback",
        "visual_ready": False,
        "quality": quality,
    }


def _is_task_canceled(task_id: str) -> bool:
    task_info = cache_manager.get_task_by_id(task_id) or {}
    return task_info.get("status") == TaskStatus.CANCELED


def _is_cloud_postprocess_terminal(task_id: str) -> bool:
    task_info = cache_manager.get_task_by_id(task_id) or {}
    return task_info.get("status") in {
        TaskStatus.CANCELED,
        TaskStatus.FAILED,
        TaskStatus.SUCCESS,
    }


def _schedule_summary_retry(llm_task: dict, attempt: int) -> int | None:
    """Enqueue one bounded summary-only retry after the configured delay."""
    if attempt < 1 or attempt > len(_SUMMARY_RETRY_DELAYS_SECONDS):
        return None

    delay = _SUMMARY_RETRY_DELAYS_SECONDS[attempt - 1]
    retry_task = {
        **llm_task,
        "summary_only_retry": True,
        "summary_retry_attempt": attempt,
        "skip_notification": True,
    }
    for transient_key in (
        "perf_tracker",
        "usage_event_id",
        "postprocess_key",
    ):
        retry_task.pop(transient_key, None)

    def _enqueue() -> None:
        try:
            llm_task_queue.put(retry_task)
            logger.info(
                f"summary retry enqueued: {retry_task.get('task_id')}, "
                f"attempt={attempt}"
            )
        except Exception as exc:
            logger.error(
                f"summary retry enqueue failed: {retry_task.get('task_id')}, "
                f"attempt={attempt}, error={exc}"
            )

    timer = threading.Timer(delay, _enqueue)
    timer.daemon = True
    timer.start()
    logger.info(
        f"summary retry scheduled: {llm_task.get('task_id')}, "
        f"attempt={attempt}, delay={delay}s"
    )
    return delay


def _existing_progress_evidence(task_id: str) -> dict:
    task_info = cache_manager.get_task_by_id(task_id) or {}
    progress = task_info.get("progress") or {}
    evidence = progress.get("evidence") or {}
    return dict(evidence) if isinstance(evidence, dict) else {}


def _handle_summary_only_retry(llm_task: dict) -> None:
    """Retry only summary generation from the saved calibrated transcript."""
    task_id = llm_task["task_id"]
    platform = llm_task.get("platform")
    media_id = llm_task.get("media_id")
    use_speaker_recognition = bool(
        llm_task.get("use_speaker_recognition", False)
    )
    attempt = int(llm_task.get("summary_retry_attempt") or 1)
    cache_snapshot = (
        cache_manager.get_cache(
            platform,
            media_id,
            use_speaker_recognition=use_speaker_recognition,
        )
        if platform and media_id
        else None
    ) or {}
    calibrated_text = str(cache_snapshot.get("llm_calibrated") or "").strip()
    summary_text = None
    summary_error = None

    if not calibrated_text:
        summary_error = "saved calibrated transcript is unavailable"
    else:
        try:
            summary_text = llm_coordinator.summary_processor.process(
                text=calibrated_text,
                title=llm_task.get("video_title") or "",
                author=llm_task.get("author") or "",
                description=llm_task.get("description") or "",
                speaker_count=2 if use_speaker_recognition else 0,
                transcription_data=None,
                selected_models=llm_coordinator.config.get_models(),
            )
            if not summary_text:
                summary_error = "summary generation returned empty"
        except Exception as exc:
            summary_error = str(exc)
            logger.exception(
                f"summary-only retry failed: {task_id}, attempt={attempt}"
            )

    evidence = _existing_progress_evidence(task_id)
    if summary_text and platform and media_id:
        summary_saved = cache_manager.save_llm_result(
            platform=platform,
            media_id=media_id,
            use_speaker_recognition=use_speaker_recognition,
            llm_type="summary",
            content=normalize_markdown_text(summary_text),
        )
        if summary_saved:
            evidence.update(
                {
                    "summary_pending": False,
                    "summary_fallback_exhausted": False,
                    "summary_retry_scheduled": False,
                    "summary_retry_attempt": attempt,
                }
            )
            cache_manager.update_task_status(
                task_id,
                TaskStatus.SUCCESS,
                platform=platform,
                media_id=media_id,
                title=llm_task.get("video_title") or "",
                author=llm_task.get("author") or "",
                terminal_evidence=evidence,
                stage_label="AI 解读已恢复",
                force=True,
            )
            logger.info(
                f"summary-only retry succeeded: {task_id}, attempt={attempt}"
            )
            return
        summary_error = "summary persistence failed"

    next_attempt = attempt + 1
    retry_delay = _schedule_summary_retry(llm_task, next_attempt)
    evidence.update(
        {
            "summary_pending": True,
            "summary_error": summary_error or "summary retry failed",
            "summary_fallback_exhausted": True,
            "summary_retry_scheduled": retry_delay is not None,
            "summary_retry_attempt": next_attempt if retry_delay else attempt,
        }
    )
    if retry_delay is not None:
        evidence["summary_retry_in_seconds"] = retry_delay
    else:
        evidence.pop("summary_retry_in_seconds", None)
    cache_manager.update_task_status(
        task_id,
        TaskStatus.SUCCESS,
        platform=platform,
        media_id=media_id,
        title=llm_task.get("video_title") or "",
        author=llm_task.get("author") or "",
        terminal_evidence=evidence,
        stage_label=(
            "AI 解读失败，等待自动重试"
            if retry_delay is not None
            else "AI 解读失败（自动重试已用尽）"
        ),
        force=True,
    )


def process_llm_queue():
    """处理LLM队列的后台任务"""
    logger.info("启动LLM队列处理器")

    while True:
        try:
            llm_task = llm_task_queue.get()
            try:
                logger.info(
                    f"LLM任务出队: {llm_task.get('task_id')}，"
                    f"提交到线程池（当前队列任务完成数: {getattr(llm_task_queue, 'completed', '未知')}）"
                )
                llm_executor.submit(_handle_llm_task, llm_task)
            except Exception as exc:
                logger.exception(f"提交LLM任务失败: {exc}")
                llm_task_queue.task_done()
        except Exception as exc:
            logger.exception(f"LLM队列处理器异常: {exc}")
            time.sleep(1)


def _handle_llm_task(llm_task: dict):
    """Worker entry for processing a single LLM task.

    Args:
        llm_task: LLM 任务字典，包含 task_id, url, video_title, transcript 等
    """
    task_id = llm_task.get("task_id")

    usage_event_id = llm_task.get("usage_event_id")
    postprocess_owner = None
    postprocess_heartbeat = None
    postprocess_repository = None
    if usage_event_id:
        postprocess_repository = UsageEventRepository(
            get_transcription_control_database(cache_manager)
        )
        try:
            postprocess_event = postprocess_repository.get_event(usage_event_id)
        except Exception:
            llm_task_queue.task_done()
            return
        if (
            not llm_task.get("postprocess_key")
            or llm_task.get("postprocess_key")
            != postprocess_event.postprocess_key
        ):
            llm_task_queue.task_done()
            return
        postprocess_owner = uuid4().hex
        if not postprocess_repository.claim_postprocess(
            usage_event_id, postprocess_owner, now=datetime.now(UTC)
        ):
            llm_task_queue.task_done()
            return
        postprocess_heartbeat = _PostprocessHeartbeat(
            postprocess_repository, usage_event_id, postprocess_owner
        )
        postprocess_heartbeat.start()
        if _is_cloud_postprocess_terminal(task_id):
            postprocess_repository.complete_postprocess(
                usage_event_id,
                postprocess_owner,
                now=datetime.now(UTC),
            )
            postprocess_heartbeat.stop()
            llm_task_queue.task_done()
            return

    # 从 transcription 阶段传递过来的性能追踪器，若无则创建新实例
    tracker: PerfTracker = llm_task.pop("perf_tracker", None) or PerfTracker(task_id=task_id)

    try:
        if _is_task_canceled(task_id):
            logger.info(f"LLM任务已取消，跳过处理: {task_id}")
            return
        with task_lock(task_id):
            if (
                postprocess_repository is not None
                and _is_cloud_postprocess_terminal(task_id)
            ):
                postprocess_repository.complete_postprocess(
                    usage_event_id,
                    postprocess_owner,
                    now=datetime.now(UTC),
                )
                return
            if _is_task_canceled(task_id):
                logger.info(f"LLM任务已取消，跳过处理: {task_id}")
                return
            url = llm_task["url"]
            display_url = llm_task.get("display_url", url)
            platform = llm_task.get("platform")
            media_id = llm_task.get("media_id")
            video_title = llm_task["video_title"]
            transcript = llm_task["transcript"]
            use_speaker_recognition = llm_task.get("use_speaker_recognition", False)
            wechat_webhook = llm_task.get("wechat_webhook")
            notification_channel = llm_task.get("notification_channel")
            notification_webhooks = llm_task.get("notification_webhooks", {})
            calibrate_only = llm_task.get("calibrate_only", False)

            _router = get_notification_router()

            class _TaskNotifier:
                def send_text(self, content, skip_risk_control=False):
                    return _router.send_text(
                        content, channel_name=notification_channel,
                        webhooks=notification_webhooks,
                    )

            task_notifier = _TaskNotifier()
            logger.info(f"开始处理LLM任务: {task_id}, 标题: {video_title}")

            try:
                if llm_task.get("summary_only_retry"):
                    _handle_summary_only_retry(llm_task)
                    return

                # 通用下载器无标题时使用 LLM 生成
                video_title = _generate_title_if_needed(llm_task, video_title, transcript)
                llm_task["video_title"] = video_title

                if llm_task.get("comment_only"):
                    logger.info(f"开始处理缓存补评论任务: {task_id}, 标题: {video_title}")
                    _safe_update_progress(
                        task_id,
                        stage="comment_insight",
                        stage_label="正在生成评论洞察",
                        basis="llm_started",
                        confidence="low",
                    )
                    result_dict = _build_comment_only_result_dict(llm_task)
                    result_dict["models_used"] = llm_coordinator.config.get_models()
                    _append_comment_insight(
                        llm_task=llm_task,
                        result_dict=result_dict,
                        summary_model=llm_coordinator.config.summary_model,
                        summary_reasoning_effort=llm_coordinator.config.summary_reasoning_effort,
                    )
                    _save_llm_results(
                        task_id=task_id,
                        platform=platform,
                        media_id=media_id,
                        use_speaker_recognition=use_speaker_recognition,
                        result_dict=result_dict,
                        calibrate_only=False,
                    )
                    if not calibrate_only:
                        _send_notification(
                            task_id=task_id,
                            video_title=video_title,
                            display_url=display_url,
                            use_speaker_recognition=use_speaker_recognition,
                            result_dict=result_dict,
                            notification_channel=notification_channel,
                            notification_webhooks=notification_webhooks,
                        )
                    tracker.log_summary()
                    cache_manager.update_task_status(
                        task_id,
                        TaskStatus.SUCCESS,
                        platform=platform,
                        media_id=media_id,
                        title=video_title,
                        author=llm_task.get("author", ""),
                    )
                    logger.info(f"缓存补评论任务完成: {task_id}, 标题: {video_title}")
                    return

                # 使用新 LLM 协调器处理任务（用 PerfTracker 记录 LLM 处理耗时）
                logger.info(f"开始使用 LLM 协调器处理任务: {task_id}")
                _safe_update_progress(
                    task_id,
                    stage="calibrating",
                    stage_label=_fallback_stage_label(llm_task, "正在校对和总结"),
                    basis="llm_started",
                    confidence="low",
                    evidence=_progress_evidence(
                        llm_task, transcript_chars=len(transcript)
                    ),
                )

                # 准备内容参数
                content = _prepare_llm_content(llm_task, transcript, use_speaker_recognition)

                # 是否为仅校对模式（重新校对场景）
                # 仅校对模式下，若缓存里 llm_summary.txt 缺失/为空，顺手补跑一次 summary
                # 避免老任务卡在 view 页的 "总结处理中..." 状态
                force_summary_regeneration = bool(llm_task.get("regenerate_summary"))
                summary_backfill = force_summary_regeneration
                if force_summary_regeneration:
                    logger.info(f"recalibrate: forced summary regeneration enabled for {task_id}")
                if calibrate_only and platform and media_id:
                    cache_snapshot = cache_manager.get_cache(
                        platform, media_id,
                        use_speaker_recognition=use_speaker_recognition,
                    )
                    if (
                        not summary_backfill
                        and _should_backfill_summary(cache_snapshot or {}, calibrate_only=True)
                    ):
                        summary_backfill = True
                        logger.info(
                            f"recalibrate: llm_summary missing for {task_id}, "
                            f"auto-backfill enabled"
                        )

                # 协调器需要知道是否跳过 summary：backfill 时强制跑 summary
                skip_summary_for_coordinator = calibrate_only and not summary_backfill

                # 调用新架构（包含校对和总结）
                def _calibration_progress(completed: int, total: int) -> None:
                    _safe_update_progress(
                        task_id,
                        stage="calibrating",
                        stage_label=_fallback_stage_label(
                            llm_task, "正在校对和总结"
                        ),
                        fraction=(completed / total) if total else None,
                        basis="completed_segments",
                        confidence="high",
                        evidence=_progress_evidence(
                            llm_task,
                            completed_segments=completed,
                            total_segments=total,
                        ),
                    )

                with tracker.track("llm_processing"):
                    coordinator_result = llm_coordinator.process(
                        content=content,
                        title=video_title,
                        author=llm_task.get("author", ""),
                        description=llm_task.get("description", ""),
                        platform=platform or "",
                        media_id=media_id or "",
                        skip_summary=skip_summary_for_coordinator,
                        progress_callback=_calibration_progress,
                    )

                # 适配返回格式
                result_dict = _build_result_dict(coordinator_result)

                summary_error_message = None
                summary_expected = (not calibrate_only) or summary_backfill
                if summary_expected and result_dict.get("内容总结") is None:
                    calibrated_text = result_dict.get("校对文本") or ""
                    min_summary_threshold = getattr(
                        llm_coordinator.config, "min_summary_threshold", 500
                    )
                    try:
                        min_summary_threshold = int(min_summary_threshold)
                    except (TypeError, ValueError):
                        min_summary_threshold = 500
                    if len(calibrated_text) < min_summary_threshold:
                        result_dict["skip_summary"] = True
                        result_dict["summary_success"] = True
                        result_dict.setdefault("stats", {})["summary_length"] = len(
                            calibrated_text
                        )
                    else:
                        summary_error_message = (
                            "summary generation returned empty for required summary"
                        )

                # 可选评论洞察：失败不影响主转录/总结链路
                if not calibrate_only and not summary_error_message:
                    models_used = result_dict.get("models_used", {})
                    if llm_task.get("include_comments"):
                        _safe_update_progress(
                            task_id,
                            stage="comment_insight",
                            stage_label="正在生成评论洞察",
                            basis="llm_started",
                            confidence="low",
                        )
                    _append_comment_insight(
                        llm_task=llm_task,
                        result_dict=result_dict,
                        summary_model=(
                            models_used.get("summary_model")
                            or llm_coordinator.config.summary_model
                        ),
                        summary_reasoning_effort=(
                            models_used.get("summary_reasoning_effort")
                            or llm_coordinator.config.summary_reasoning_effort
                        ),
                    )

                logger.info(f"LLM处理完成，开始保存结果和发送微信通知: {task_id}")
                _safe_update_progress(
                    task_id,
                    stage="notifying",
                    stage_label="正在保存结果和发送通知",
                    basis="stage_transition",
                    confidence="medium",
                    evidence=_progress_evidence(llm_task),
                )

                # 保存结果到缓存
                _save_llm_results(
                    task_id=task_id,
                    platform=platform,
                    media_id=media_id,
                    use_speaker_recognition=use_speaker_recognition,
                    result_dict=result_dict,
                    calibrate_only=calibrate_only,
                    summary_backfill=summary_backfill,
                )
                # Summary failure must not block transcript delivery or collection progress.
                # Model problems are handled by immediate in-request fallback models;
                # if the whole chain fails, keep calibrated artifacts and mark pending.
                if summary_error_message:
                    summary_retry_delay = _schedule_summary_retry(llm_task, 1)
                    result_dict["summary_success"] = False
                    result_dict["summary_pending"] = True
                    result_dict["summary_error"] = summary_error_message
                    logger.warning(
                        "summary generation failed after in-request model fallbacks; "
                        "marking summary pending without failing the task: "
                        f"{task_id}, error={summary_error_message}"
                    )

                # 发送通知（多渠道）
                if not calibrate_only and not llm_task.get("skip_notification"):
                    _send_notification(
                        task_id=task_id,
                        video_title=video_title,
                        display_url=display_url,
                        use_speaker_recognition=use_speaker_recognition,
                        result_dict=result_dict,
                        notification_channel=notification_channel,
                        notification_webhooks=notification_webhooks,
                    )

                logger.info(f"LLM任务处理完成: {task_id}, 标题: {video_title}")

                # 任务成功完成，输出完整性能摘要
                tracker.log_summary()

                # LLM 阶段拥有终态：产物已通过 _save_llm_results 落盘，此时才置 success
                # （对所有任务生效，不再仅限 calibrate_only；终态由本阶段统一写回）
                done_message = "重新校对完成" if calibrate_only else "校对完成"
                if summary_error_message:
                    done_message = "校对完成（AI 解读失败，已尝试备用模型）"
                terminal_evidence = _terminal_evidence(llm_task) or {}
                if summary_error_message:
                    terminal_evidence = {
                        **terminal_evidence,
                        "summary_pending": True,
                        "summary_error": summary_error_message,
                        "summary_fallback_exhausted": True,
                        "summary_retry_scheduled": summary_retry_delay is not None,
                        "summary_retry_attempt": 1,
                    }
                    if summary_retry_delay is not None:
                        terminal_evidence["summary_retry_in_seconds"] = (
                            summary_retry_delay
                        )
                elif result_dict.get("内容总结"):
                    terminal_evidence = {
                        **terminal_evidence,
                        "summary_pending": False,
                        "summary_fallback_exhausted": False,
                    }
                success_stage_label = None
                if summary_error_message:
                    success_stage_label = "AI 解读失败（已切换备用模型）"
                cache_manager.update_task_status(
                    task_id,
                    TaskStatus.SUCCESS,
                    platform=platform,
                    media_id=media_id,
                    title=video_title,
                    author=llm_task.get("author", ""),
                    terminal_evidence=terminal_evidence or None,
                    stage_label=success_stage_label,
                )

                # Complete the durable outbox only after artifacts and the
                # LearnFlux terminal state are persisted. A crash before this
                # point is reconciled by the scanner using the same key.
                if postprocess_repository is not None:
                    if (
                        postprocess_heartbeat.lost.is_set()
                        or not postprocess_repository.complete_postprocess(
                            usage_event_id,
                            postprocess_owner,
                            now=datetime.now(UTC),
                        )
                    ):
                        raise RuntimeError("postprocess_lease_lost")
                logger.info(f"任务状态已更新为 success: {task_id} ({done_message})")

            except Exception as exc:
                logger.exception(f"LLM任务处理异常: {task_id}, 错误: {exc}")
                # LLM 处理失败时输出已记录的性能摘要
                tracker.log_summary()
                if not llm_task.get("skip_notification"):
                    task_notifier.send_text(f"【LLM API调用异常】{exc}")

                # 终态由 LLM 阶段统一写回（对所有任务生效，修复普通任务 LLM 失败被静默的问题）
                # Always write failed, including cloud postprocess paths; otherwise the
                # task can remain stuck in calibrating/"AI 处理中".
                fail_message = (
                    f"重新校对失败: {exc}" if llm_task.get("calibrate_only")
                    else f"LLM处理失败: {exc}"
                )
                try:
                    cache_manager.update_task_status(
                        task_id, TaskStatus.FAILED, error_message=fail_message,
                        terminal_evidence=_terminal_evidence(llm_task),
                    )
                    logger.info(f"任务状态已更新为 failed: {task_id} ({fail_message})")
                except Exception:
                    logger.exception(
                        f"failed to persist failed terminal state: {task_id}"
                    )
    finally:
        if postprocess_heartbeat is not None:
            postprocess_heartbeat.stop()
        llm_task_queue.task_done()


def _generate_title_if_needed(llm_task: dict, video_title: str, transcript: str) -> str:
    """通用下载器场景下使用 LLM 生成标题

    Args:
        llm_task: LLM 任务字典
        video_title: 当前标题
        transcript: 转录文本

    Returns:
        str: 标题（可能是生成的或原始的）
    """
    if video_title != "":
        return video_title

    is_generic = llm_task.get("is_generic", False)
    if not is_generic:
        return video_title

    logger.info("通用下载器文件没有标题，使用LLM生成")
    title_prompt = (
        "请根据以下音视频转录文本，生成一个简洁的标题（不超过20个字）。\n"
        "只返回标题文本，不要有任何其他说明或标点符号。\n"
        "如果无法从内容中提取有意义的标题，请返回'自定义文件总结'。\n\n"
        "转录文本：\n" + transcript[:1000]
    )

    try:
        config_llm = config.get("llm", {})
        generated_title = call_llm_api(
            config_llm.get("summary_model"),
            title_prompt,
            config_llm.get("api_key"),
            config_llm.get("base_url"),
            config_llm.get("max_retries", 2),
            config_llm.get("retry_delay", 5),
        )

        generated_title = (
            generated_title.strip()
            .strip('"')
            .strip("'")
            .strip("。")
            .strip("，")
        )

        if generated_title and len(generated_title) <= 30:
            logger.info(f"LLM生成的标题: {generated_title}")
            return generated_title
        else:
            logger.warning("LLM生成的标题不合规，使用默认标题")
            return "自定义文件总结"
    except Exception as exc:
        logger.error(f"LLM生成标题失败: {exc}")
        return "自定义文件总结"


def _prepare_llm_content(llm_task: dict, transcript: str, use_speaker_recognition: bool):
    """准备 LLM 协调器的输入内容

    Args:
        llm_task: LLM 任务字典
        transcript: 转录文本
        use_speaker_recognition: 是否使用说话人识别

    Returns:
        内容参数（字符串或列表）
    """
    if use_speaker_recognition and llm_task.get("transcription_data"):
        transcription_data = llm_task.get("transcription_data")
        if isinstance(transcription_data, dict):
            return transcription_data.get("segments", [])
        elif isinstance(transcription_data, list):
            return transcription_data
        else:
            logger.warning(
                f"Unexpected transcription_data type: {type(transcription_data)}, "
                f"falling back to formatted text"
            )
            return transcript
    return transcript


def _build_result_dict(coordinator_result: dict) -> dict:
    """将协调器结果适配为统一格式

    Args:
        coordinator_result: LLM 协调器返回的结果

    Returns:
        dict: 统一格式的结果字典
    """
    calibrated_text = coordinator_result.get("calibrated_text", "")
    summary_text = coordinator_result.get("summary_text")
    should_skip_summary = summary_text is None

    result_dict = {
        "校对文本": calibrated_text,
        "内容总结": summary_text,
        "skip_summary": should_skip_summary,
        "stats": coordinator_result.get("stats", {}),
        "models_used": coordinator_result.get("models_used", {}),
        "calibrate_success": True,
        "summary_success": summary_text is not None,
    }

    if "structured_data" in coordinator_result:
        result_dict["structured_data"] = coordinator_result["structured_data"]

    return result_dict


def _build_comment_only_result_dict(llm_task: dict) -> dict:
    """Build a result dict from cached LLM outputs for comment-only enrichment."""
    transcript = llm_task.get("transcript", "") or ""
    calibrated_text = llm_task.get("cached_calibrated") or transcript
    summary_text = llm_task.get("cached_summary")

    return {
        "校对文本": calibrated_text,
        "内容总结": summary_text,
        "skip_summary": summary_text is None,
        "stats": {
            "original_length": len(transcript),
            "calibrated_length": len(calibrated_text),
            "summary_length": len(summary_text) if summary_text else 0,
        },
        "models_used": {},
        "calibrate_success": True,
        "summary_success": summary_text is not None,
    }


def _append_comment_insight(
    *,
    llm_task: dict,
    result_dict: dict,
    summary_model: str,
    summary_reasoning_effort: str | None,
    analyzer=None,
    insight_runner=generate_comment_insight,
) -> None:
    """Append optional hot-comment insight to an LLM result dict."""
    if not llm_task.get("include_comments", False):
        return

    try:
        fetch_limit = int(llm_task.get("comment_limit", 100))
    except (TypeError, ValueError):
        fetch_limit = 100
    fetch_limit = max(1, min(fetch_limit, 200))
    analysis_limit = min(fetch_limit, 50)

    comment_analyzer = analyzer or CommentInsightAnalyzer(
        llm_client=llm_coordinator.llm_client,
        model=summary_model,
        reasoning_effort=summary_reasoning_effort,
    )

    try:
        insight_result = insight_runner(
            url=llm_task.get("url", ""),
            platform=llm_task.get("platform"),
            media_id=llm_task.get("media_id"),
            title=llm_task.get("video_title", ""),
            author=llm_task.get("author", ""),
            summary_text=result_dict.get("内容总结"),
            fetch_limit=fetch_limit,
            analysis_limit=analysis_limit,
            analyzer=comment_analyzer,
        )
    except Exception as exc:
        logger.warning(
            f"评论洞察生成失败，不影响主任务: task_id={llm_task.get('task_id')}, error={exc}"
        )
        result_dict["comment_error"] = str(exc)
        return

    if not insight_result:
        logger.info(f"未生成评论洞察: task_id={llm_task.get('task_id')}")
        return

    result_dict["评论洞察"] = insight_result["insight_text"]
    result_dict["comment_samples"] = insight_result["samples"]
    result_dict["comment_stats"] = {
        "fetched_count": insight_result["fetched_count"],
        "selected_count": insight_result["selected_count"],
    }
    logger.info(
        f"评论洞察生成完成: task_id={llm_task.get('task_id')}, "
        f"selected={insight_result['selected_count']}/{insight_result['fetched_count']}"
    )


def _should_backfill_summary(cache_data: dict, calibrate_only: bool) -> bool:
    """判断是否需要在 recalibrate 流程里顺手补跑一次 summary。

    触发条件：仅校对模式，且缓存目录里的 llm_summary.txt 缺失或为空字节。
    空文件视为历史遗留占位，同样需要补跑。

    Args:
        cache_data: cache_manager.get_cache(...) 返回的数据字典
        calibrate_only: 是否仅校对（recalibrate）流程

    Returns:
        True 表示应当补跑 summary，False 表示保留现状
    """
    if not calibrate_only:
        return False

    if cache_data and cache_data.get("storage_backend") == "postgres":
        summary = cache_data.get("llm_summary")
        return not isinstance(summary, str) or not summary.strip()

    file_path = cache_data.get("file_path") if cache_data else None
    if not file_path:
        return False

    summary_file = Path(file_path) / "llm_summary.txt"
    if not summary_file.exists():
        return True

    try:
        return summary_file.stat().st_size == 0
    except OSError:
        return True


def _save_llm_results(
    task_id: str,
    platform: str,
    media_id: str,
    use_speaker_recognition: bool,
    result_dict: dict,
    calibrate_only: bool,
    summary_backfill: bool = False,
):
    """保存 LLM 处理结果到缓存

    Args:
        task_id: 任务 ID
        platform: 平台标识
        media_id: 媒体 ID
        use_speaker_recognition: 是否使用说话人识别
        result_dict: LLM 处理结果字典
        calibrate_only: 是否仅校对模式
        summary_backfill: 仅校对模式下是否需要补写 summary 文件
            （原任务缺失 llm_summary.txt 时由 _handle_llm_task 置为 True）
    """
    calibrated_text = result_dict.get("校对文本", "")
    summary_text = result_dict.get("内容总结")
    skip_summary = result_dict.get("skip_summary", False)
    stats = result_dict.get("stats", {})
    models_used = result_dict.get("models_used", {})
    calibrate_success = result_dict.get("calibrate_success", True)
    summary_success = result_dict.get("summary_success", True)

    # 保存 LLM 模型配置到数据库
    if models_used:
        cache_manager.update_task_llm_config(task_id, models_used)
        logger.info(
            f"LLM模型配置已保存: {task_id}"
        )

    if not (platform and media_id):
        return

    # 保存校对文本
    if calibrate_success:
        cache_manager.save_llm_result(
            platform=platform,
            media_id=media_id,
            use_speaker_recognition=use_speaker_recognition,
            llm_type="calibrated",
            content=calibrated_text,
        )
        logger.info(f"校对文本已保存到缓存: {task_id}")
    else:
        logger.warning(f"校对失败，跳过保存校对文件: {task_id}")

    # 保存总结文本
    if calibrate_only and not summary_backfill:
        logger.info(f"仅校对模式，保留原有总结文件: {task_id}")
    elif summary_success:
        if skip_summary:
            if calibrate_success:
                logger.info(f"文本过短，保存校对文本作为总结: {task_id}")
                cache_manager.save_llm_result(
                    platform=platform,
                    media_id=media_id,
                    use_speaker_recognition=use_speaker_recognition,
                    llm_type="summary",
                    content=calibrated_text,
                )
        else:
            if summary_text is not None:
                logger.info(f"保存LLM总结到缓存: {task_id}")
                cache_manager.save_llm_result(
                    platform=platform,
                    media_id=media_id,
                    use_speaker_recognition=use_speaker_recognition,
                    llm_type="summary",
                    content=normalize_markdown_text(summary_text),
                )
            else:
                logger.warning(f"总结生成失败，跳过保存: {task_id}")
    else:
        logger.warning(f"总结失败，跳过保存总结文件: {task_id}")

    # 保存结构化数据
    if use_speaker_recognition and calibrate_success and "structured_data" in result_dict:
        structured_data = result_dict["structured_data"]
        cal_stats_for_save = stats.get("calibration_stats")
        if cal_stats_for_save:
            structured_data["calibration_stats"] = cal_stats_for_save
        save_ok = cache_manager.save_llm_result(
            platform=platform,
            media_id=media_id,
            use_speaker_recognition=use_speaker_recognition,
            llm_type="structured",
            content=structured_data,
        )
        if save_ok:
            logger.info(f"结构化数据已保存到缓存: {platform}/{media_id}/llm_processed.json")
        else:
            logger.warning(f"结构化数据保存失败: {task_id}")

    comment_insight = result_dict.get("评论洞察")
    if comment_insight:
        cache_manager.save_llm_result(
            platform=platform,
            media_id=media_id,
            use_speaker_recognition=use_speaker_recognition,
            llm_type="comment_insight",
            content=comment_insight,
        )
        logger.info(f"评论洞察已保存到缓存: {task_id}")

    comment_samples = result_dict.get("comment_samples")
    if comment_samples:
        cache_manager.save_llm_result(
            platform=platform,
            media_id=media_id,
            use_speaker_recognition=use_speaker_recognition,
            llm_type="comment_samples",
            content=comment_samples,
        )
        logger.info(f"评论样本已保存到缓存: {task_id}")

    if calibrate_success or summary_success:
        logger.info(f"LLM结果已保存到缓存: {platform}/{media_id}")
    else:
        logger.warning(f"LLM处理全部失败，未保存任何结果文件: {task_id}")


def _send_notification(
    task_id: str,
    video_title: str,
    display_url: str,
    use_speaker_recognition: bool,
    result_dict: dict,
    notification_channel: str = None,
    notification_webhooks: dict = None,
):
    """Send LLM results notification via router (multi-channel).

    Args:
        task_id: task ID
        video_title: video title
        display_url: display URL
        use_speaker_recognition: speaker recognition flag
        result_dict: LLM result dict
        notification_channel: target channel (wechat/feishu/None=all)
        notification_webhooks: per-channel webhook dict
    """
    if notification_webhooks is None:
        notification_webhooks = {}
    router = get_notification_router()

    calibrated_text = result_dict.get("校对文本", "")
    summary_text = result_dict.get("内容总结")
    skip_summary = result_dict.get("skip_summary", False)
    stats = result_dict.get("stats", {})
    models_used = result_dict.get("models_used", {})

    task_info = cache_manager.get_task_by_id(task_id)
    view_url = ""
    if task_info and task_info.get("view_token"):
        base_url = get_base_url()
        view_url = f"{base_url}/view/{task_info['view_token']}"

    original_length = stats.get("original_length", 0)
    calibrated_length = stats.get("calibrated_length", 0)
    summary_length = stats.get("summary_length", 0)

    calibration_warning = _build_calibration_warning(stats)

    speaker_info = "（含说话人识别）" if use_speaker_recognition else ""
    model_config_text = format_llm_config_markdown(models_used)

    # 校对文本超过此阈值时，不发送全文到通知渠道（避免刷屏）
    NOTIFICATION_TEXT_THRESHOLD = 5000

    if skip_summary:
        if len(calibrated_text) <= NOTIFICATION_TEXT_THRESHOLD:
            full_message = f"""## 总结和校对
🌐 网页查看：{view_url}
📄 直接获取：{view_url}?raw=calibrated

## 转录统计
原始 {original_length:,} 字 | 校对 {calibrated_length:,} 字 | 总结 未生成{calibration_warning}

{model_config_text}

## 校对文本{speaker_info}
{calibrated_text}"""
            logger.info(f"发送校对文本（总结未生成，文本较短直接发送）: {task_id}")
        else:
            full_message = f"""## 总结和校对
🌐 网页查看：{view_url}
📄 直接获取：{view_url}?raw=calibrated

## 转录统计
原始 {original_length:,} 字 | 校对 {calibrated_length:,} 字 | 总结 未生成{calibration_warning}

{model_config_text}

⚠️ 校对文本过长（{calibrated_length:,} 字），请点击上方链接在网页中查看完整内容。"""
            logger.info(
                f"校对文本过长（{calibrated_length} 字 > {NOTIFICATION_TEXT_THRESHOLD}），"
                f"仅发送链接: {task_id}"
            )
    else:
        full_message = f"""## 总结和校对
🌐 网页查看：{view_url}
📄 直接获取：{view_url}?raw=calibrated

## 转录统计
原始 {original_length:,} 字 | 校对 {calibrated_length:,} 字 | 总结 {summary_length:,} 字{calibration_warning}

{model_config_text}

## 总结{speaker_info}
{summary_text}"""
        logger.info(f"发送总结文本: {task_id}")

    router.send_long_text(
        title=video_title,
        url=display_url,
        text=full_message,
        is_summary=not skip_summary,
        has_speaker_recognition=use_speaker_recognition,
        channel_name=notification_channel,
        webhooks=notification_webhooks,
        skip_content_type_header=True,
    )

    time.sleep(0.1)

    task_info = cache_manager.get_task_by_id(task_id)
    if task_info and task_info.get("view_token"):
        base_url = get_base_url()
        view_url = f"{base_url}/view/{task_info['view_token']}"
        clean = _clean_url(display_url)
        sanitized_title = _sanitize_title(video_title)

        completion_message = f"# {sanitized_title}\n\n{clean}\n\n🔗 总结和校对：\n{view_url}\n\n✅ **【任务完成】**"
        router.send_text(
            completion_message,
            channel_name=notification_channel,
            webhooks=notification_webhooks,
        )
        logger.info(f"任务完成通知已加入限流队列: {task_id}")


def _build_calibration_warning(stats: dict) -> str:
    """构建校准质量警告文本

    Args:
        stats: 统计信息字典

    Returns:
        str: 警告文本（空字符串表示无警告）
    """
    cal_stats = stats.get("calibration_stats")
    if not cal_stats:
        return ""

    failed = cal_stats.get("failed_count", 0)
    fallback = cal_stats.get("fallback_count", 0)
    total = cal_stats.get("total_chunks", 0)
    success = cal_stats.get("success_count", 0)

    if failed == total and total > 0:
        return (
            "\n⚠️ **校准完全失败**：LLM API 超时，"
            "当前显示为未校准的原始语音识别文本，质量较低。"
            "建议稍后重新提交。"
        )
    elif failed > 0 or fallback > 0:
        return (
            f"\n⚠️ **校准部分异常**：{success}/{total} 段校准成功，"
            f"{fallback} 段降级，{failed} 段失败。"
            "部分内容为未校准文本。"
        )
    return ""


def _sanitize_title(video_title: str) -> str:
    """对标题进行风控处理

    Args:
        video_title: 原始标题

    Returns:
        str: 处理后的标题
    """
    try:
        from ...risk_control import is_enabled, sanitize_text

        if is_enabled():
            title_result = sanitize_text(video_title, text_type="title")
            if title_result["has_sensitive"]:
                logger.info(
                    f"[风控] 完成通知标题包含 {len(title_result['sensitive_words'])} 个敏感词，已处理"
                )
                return title_result["sanitized_text"]
    except Exception as risk_exc:
        logger.exception(f"完成通知标题风控处理失败: {risk_exc}")

    return video_title
