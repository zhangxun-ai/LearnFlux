import asyncio
import contextlib
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows only
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX only
    msvcrt = None

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..collections.summary_worker import CollectionSummaryWorker
from ..utils.notifications import init_all_notifiers, shutdown_all_notifiers
from ..utils.source_file_cleanup import cleanup_old_source_files
from ..utils.ytdlp import YtdlpConfigBuilder
from ..llm import set_default_config, log_llm_stats
from ..llm.llm import log_llm_config_summary
from .context import (
    get_cache_manager,
    get_cloud_asr_executor,
    get_config,
    get_logger,
    get_llm_queue,
    get_static_dir,
    get_temp_manager,
    get_transcription_control_store,
    get_workspace_dir,
    get_executor,
    get_transcription_concurrency_controller,
    set_cloud_asr_dispatcher,
)
from ..transcriber.cloud_dispatcher import CloudASRDispatcher
from ..transcriber.cloud_runtime import (
    build_aliyun_recovery,
    build_aliyun_reserved_provider,
    identify_quote_backed_reserved,
    reconcile_stale_local_queued,
    resume_quote_backed_reserved_attempt,
)
from ..reading.service import ReadingService
from .services.post_asr import dispatch_pending_post_asr, dispatch_post_asr
from .services.progress_notifications import process_progress_reminders
from .routes import (
    audit,
    collections,
    flywheel,
    health,
    journal,
    marks,
    obsidian,
    post_insight,
    reading,
    settings,
    study,
    tasks,
    trend_radar,
    users,
    views,
    visual_learning,
)
from .services.transcription import (
    process_llm_queue,
    process_task_queue,
    resume_confirmed_cloud_quote,
)


_CLOUD_RECOVERY_SHUTDOWN_JOIN_SECONDS = 1.0


def external_access_debug_enabled(config: dict) -> bool:
    """Return whether detailed external-access diagnostics are explicitly enabled."""
    return config.get("log", {}).get("external_access_debug") is True


def _acquire_runtime_lock(cache_dir: Path) -> TextIO | None:
    """Hold task recovery ownership for the lifetime of one API instance."""
    lock_path = Path(cache_dir) / ".runtime.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            lock_file.seek(0)
            if not lock_file.read(1):
                lock_file.write("\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - unsupported Python platform
            raise OSError("no supported file-lock implementation")
    except (BlockingIOError, OSError):
        lock_file.close()
        return None

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


def _release_runtime_lock(lock_file: TextIO | None) -> None:
    if lock_file is None:
        return
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - Windows only
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    lock_file.close()


def _release_app_runtime_lock(app: FastAPI) -> None:
    """Release one app's recovery lock at most once across two threads."""
    guard = getattr(app.state, "runtime_lock_release_guard", None)
    if guard is None:
        return
    with guard:
        lock_file = getattr(app.state, "runtime_lock_file", None)
        if lock_file is None:
            return
        _release_runtime_lock(lock_file)
        app.state.runtime_lock_file = None


def _source_cleanup_paths(storage_config: dict) -> tuple[Path, Path]:
    configured_source_dir = storage_config.get("source_files_dir")
    if configured_source_dir:
        source_root = Path(configured_source_dir)
        return source_root, source_root

    source_root = Path("./data/source_files")
    return source_root, source_root / "collection_uploads"


def _run_source_file_cleanup(cache_manager, storage_config: dict, logger) -> None:
    if not storage_config.get("source_file_cleanup_enabled", True):
        return

    retention_days = storage_config.get("source_file_retention_days", 30)
    source_root, collection_source_dir = _source_cleanup_paths(storage_config)
    result = cleanup_old_source_files(
        cache_manager=cache_manager,
        source_root=source_root,
        collection_source_dir=collection_source_dir,
        max_age_days=retention_days,
    )
    if result.deleted_count or result.error_count:
        logger.info(
            f"源文件清理完成: scanned={result.scanned_count} "
            f"deleted={result.deleted_count} "
            f"skipped_referenced={result.skipped_referenced_count} "
            f"errors={result.error_count}"
        )


def _recover_reading_deletions(
    cache_manager, storage_config: dict, logger
) -> None:
    source_root, _ = _source_cleanup_paths(storage_config)
    service = ReadingService(
        db_path=cache_manager.db_path,
        source_root=source_root,
    )
    try:
        recovered = service.recover_deletion_jobs()
        if recovered:
            logger.info(f"Reading deletion cleanup completed: count={recovered}")
        recovered_ocr = service.recover_interrupted_ocr(
            older_than=datetime.now(UTC) - timedelta(minutes=15)
        )
        if recovered_ocr:
            logger.warning(
                f"Reading OCR recovery made retryable: count={recovered_ocr}"
            )
    finally:
        service.close()


def create_app() -> FastAPI:
    config = get_config()
    logger = get_logger()
    external_access_debug = external_access_debug_enabled(config)

    app = FastAPI(
        title="LearnFlux",
        description="AI 驱动的内容学习工作台",
        version="1.0.0",
    )
    app.state.runtime_lock_release_guard = threading.Lock()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = get_static_dir()
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 调试中间件：记录 /view/ 请求的详细信息，用于排查外部 AI 工具的访问问题
    @app.middleware("http")
    async def log_external_access(request: Request, call_next):
        path = request.url.path
        if external_access_debug and ("/view/" in path or "/export/" in path):
            query = str(request.url.query)
            ua = request.headers.get("user-agent", "N/A")[:200]
            cf_ip = request.headers.get("cf-connecting-ip", "N/A")
            cf_ray = request.headers.get("cf-ray", "N/A")
            accept = request.headers.get("accept", "N/A")[:100]
            logger.info(
                f"[ExternalAccess] {request.method} {path}?{query} | "
                f"UA: {ua} | CF-IP: {cf_ip} | CF-Ray: {cf_ray} | Accept: {accept}"
            )
            response = await call_next(request)
            ct = response.headers.get("content-type", "N/A")
            cl = response.headers.get("content-length", "unknown")
            logger.info(
                f"[ExternalAccess] Response: {request.method} {path} | "
                f"status={response.status_code} | content-type={ct} | content-length={cl}"
            )
            return response
        return await call_next(request)

    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(audit.router)
    app.include_router(users.router)
    app.include_router(views.router)
    app.include_router(obsidian.router)
    app.include_router(study.router)
    app.include_router(visual_learning.router)
    app.include_router(journal.router)
    app.include_router(marks.router)
    app.include_router(collections.router)
    app.include_router(post_insight.router)
    app.include_router(flywheel.router)
    app.include_router(trend_radar.router)
    app.include_router(reading.router)
    app.include_router(settings.router)

    @app.on_event("startup")
    async def startup_event():
        temp_manager = get_temp_manager()
        # 只有持有运行锁的主实例可以执行恢复。测试进程或重复启动的短生命周期实例
        # 不得把仍由在线服务处理的任务误判为孤儿任务。
        cache_manager = get_cache_manager()
        runtime_lock_file = _acquire_runtime_lock(cache_manager.cache_dir)
        app.state.runtime_lock_file = runtime_lock_file
        if runtime_lock_file is None:
            logger.warning(
                "Skipping orphan task recovery: another API instance owns the runtime lock"
            )
        else:
            Path(cache_manager.db_path).parent.mkdir(parents=True, exist_ok=True)
            control_store = get_transcription_control_store()
            usage_repository = control_store.usage_repository
            quote_repository = control_store.quote_repository
            startup_at = datetime.now(UTC)
            quote_repository.reconcile_usage_attempts()
            reconcile_stale_local_queued(
                quote_repository,
                temp_manager.get_temp_dir(),
                startup_at,
            )
            protected_reserved = identify_quote_backed_reserved(
                control_store,
                temp_manager.get_temp_dir(),
                startup_at,
            )
            for orphan in usage_repository.fail_orphan_reserved(
                created_before=startup_at,
                excluded_event_ids={
                    record.event_id for record in protected_reserved.records
                },
            ):
                cache_manager.update_task_status(
                    orphan.task_id,
                    "failed",
                    error_message="云端转录在提交前中断，请重新提交",
                    force=True,
                )
            for expired_task_id in quote_repository.expire_stale_unconfirmed():
                cache_manager.update_task_status(
                    expired_task_id,
                    "failed",
                    error_message="云端转录报价已过期，请重新提交",
                    force=True,
                )
            protected_task_ids = usage_repository.list_protected_task_ids()
            protected_snapshot_roots = (
                usage_repository.list_protected_snapshot_roots(
                    temp_manager.get_temp_dir()
                )
            )
            protected_snapshot_roots.update(protected_reserved.media_roots)
            old_files_count = temp_manager.clean_up_old_files(
                hours=24, protected_roots=protected_snapshot_roots
            )
            if old_files_count > 0:
                logger.info(f"启动时清理了 {old_files_count} 个旧临时文件")
            try:
                recovered = cache_manager.recover_orphaned_tasks(
                    protected_task_ids=protected_task_ids
                )
                if recovered:
                    logger.warning(
                        f"启动恢复：已将 {recovered} 个中断任务标记为 failed"
                    )
            except Exception as exc:
                logger.exception("启动恢复扫描失败: %s", exc)

            try:
                _recover_reading_deletions(
                    cache_manager,
                    config.get("storage", {}) or {},
                    logger,
                )
            except Exception as exc:
                logger.exception("Reading deletion recovery failed: %s", exc)

            try:
                _run_source_file_cleanup(
                    cache_manager,
                    config.get("storage", {}) or {},
                    logger,
                )
            except Exception as exc:
                logger.exception("源文件清理失败: %s", exc)

            cloud_recovery_stop_event = threading.Event()
            cloud_recovery_lock_handoff = threading.Event()
            app.state.cloud_recovery_stop_event = cloud_recovery_stop_event
            app.state.cloud_recovery_lock_handoff = (
                cloud_recovery_lock_handoff
            )
            app.state.cloud_recovery = None
            controller = get_transcription_concurrency_controller()
            finalize_uploads = getattr(
                usage_repository, "finalize_known_upload_failures", None
            )
            if callable(finalize_uploads):
                finalized_uploads = finalize_uploads(now=datetime.now(UTC))
                if finalized_uploads:
                    logger.warning(
                        "Recovered {} expired cloud upload failures",
                        len(finalized_uploads),
                    )
            for event_id in usage_repository.list_remote_capacity_attempt_ids():
                controller.reserve_recovered_cloud(f"usage:{event_id}")

            def _sync_cloud_capacity(event_id):
                if usage_repository.remote_attempt_occupies_capacity(event_id):
                    return
                try:
                    controller.release("cloud", f"usage:{event_id}")
                except Exception:
                    pass

            def _dispatch_recovered(result, event):
                if cloud_recovery_stop_event.is_set():
                    return
                get_executor().submit(
                    dispatch_post_asr,
                    result,
                    event.continuation_json,
                    cache_manager=cache_manager,
                    llm_queue=get_llm_queue(),
                    repository=usage_repository,
                    stop_event=cloud_recovery_stop_event,
                )

            def _resume_reserved(record, slot_owner):
                usage_owner = f"usage:{record.event_id}"
                transferred = False
                if not controller.acquire(
                    "cloud",
                    slot_owner,
                    cancelled=cloud_recovery_stop_event.is_set,
                ):
                    return
                try:
                    controller.transfer_cloud_owner(slot_owner, usage_owner)
                    transferred = True
                    provider = build_aliyun_reserved_provider(
                        config=config,
                        output_dir=get_workspace_dir(),
                        repository=usage_repository,
                        attempt_state_callback=_sync_cloud_capacity,
                    )
                    resume_quote_backed_reserved_attempt(
                        record,
                        store=control_store,
                        temp_root=temp_manager.get_temp_dir(),
                        provider=provider,
                    )
                except Exception:
                    logger.warning(
                        "Quote-backed cloud ASR recovery remains pending"
                    )
                finally:
                    if transferred:
                        _sync_cloud_capacity(record.event_id)
                    else:
                        try:
                            controller.release("cloud", slot_owner)
                        except Exception:
                            pass

            def _run_cloud_recovery():
                try:
                    try:
                        if cloud_recovery_stop_event.is_set():
                            return
                        dispatch_pending_post_asr(
                            repository=usage_repository,
                            output_dir=get_workspace_dir(),
                            cache_manager=cache_manager,
                            llm_queue=get_llm_queue(),
                            stop_event=cloud_recovery_stop_event,
                        )
                    except Exception:
                        logger.warning("Cloud ASR postprocess remains pending")
                    try:
                        recovery = build_aliyun_recovery(
                            config=config,
                            output_dir=get_workspace_dir(),
                            repository=usage_repository,
                            result_callback=_dispatch_recovered,
                            attempt_state_callback=_sync_cloud_capacity,
                            stop_event=cloud_recovery_stop_event,
                        )
                        app.state.cloud_recovery = recovery
                        recovery.recover_pending()
                    except Exception:
                        logger.warning("Cloud ASR recovery remains pending")
                    if not cloud_recovery_stop_event.is_set():
                        for record in protected_reserved.records:
                            slot_owner = f"reserved-recovery:{record.event_id}"
                            try:
                                get_cloud_asr_executor().submit(
                                    _resume_reserved, record, slot_owner
                                )
                            except Exception:
                                logger.warning(
                                    "Quote-backed cloud ASR recovery remains pending"
                                )
                    if not cloud_recovery_stop_event.is_set():
                        try:
                            dispatch_pending_post_asr(
                                repository=usage_repository,
                                output_dir=get_workspace_dir(),
                                cache_manager=cache_manager,
                                llm_queue=get_llm_queue(),
                                stop_event=cloud_recovery_stop_event,
                            )
                        except Exception:
                            logger.warning(
                                "Cloud ASR postprocess remains pending"
                            )
                    if not cloud_recovery_stop_event.is_set():
                        dispatcher = CloudASRDispatcher(
                            quote_repository,
                            usage_repository,
                            controller,
                            get_cloud_asr_executor(),
                            resume_confirmed_cloud_quote,
                        )
                        dispatcher.start()
                        app.state.cloud_asr_dispatcher = dispatcher
                        set_cloud_asr_dispatcher(dispatcher)
                finally:
                    if cloud_recovery_lock_handoff.is_set():
                        _release_app_runtime_lock(app)

            cloud_recovery_thread = threading.Thread(
                target=_run_cloud_recovery,
                name="cloud-asr-startup-recovery",
                daemon=True,
            )
            cloud_recovery_thread.start()
            app.state.cloud_recovery_thread = cloud_recovery_thread

        init_all_notifiers()

        # 设置 LLM 模块默认配置（用于 JSON 结构化输出）
        set_default_config(config)
        logger.info("LLM default config set")

        # 打印每任务 provider+model+thinking 摘要（set_default_config 已注入 custom_patterns）
        log_llm_config_summary(config)

        if runtime_lock_file is not None:
            llm_config = config.get("llm") or {}
            summary_worker = CollectionSummaryWorker(
                collections.get_collection_service(),
                poll_interval_seconds=float(
                    llm_config.get("collection_summary_poll_interval_seconds", 1.0)
                ),
                heartbeat_interval_seconds=float(
                    llm_config.get("collection_summary_heartbeat_seconds", 10.0)
                ),
                lease_seconds=int(
                    llm_config.get("collection_summary_lease_seconds", 60)
                ),
            )
            summary_recovery = summary_worker.start()
            app.state.collection_summary_worker = summary_worker
            if any(summary_recovery.values()):
                logger.warning(
                    "Collection summary recovery completed: {}",
                    summary_recovery,
                )
        else:
            app.state.collection_summary_worker = None

        # 初始化 yt-dlp 配置并验证 YouTube cookie
        logger.info("Initializing yt-dlp configuration...")
        ytdlp_builder = YtdlpConfigBuilder(config)
        ytdlp_builder.validate_cookie_on_startup()
        app.state.ytdlp_builder = ytdlp_builder

        logger.info("启动任务队列处理器")
        asyncio.create_task(process_task_queue())

        if runtime_lock_file is not None:
            logger.info("启动任务进度提醒处理器")
            app.state.progress_reminder_task = asyncio.create_task(
                process_progress_reminders()
            )
        else:
            app.state.progress_reminder_task = None

        logger.info("启动LLM队列处理器线程")
        llm_thread = threading.Thread(target=process_llm_queue, daemon=True)
        llm_thread.start()
        app.state.llm_thread = llm_thread

        risk_config = config.get("risk_control", {})
        if risk_config.get("enabled", False):
            logger.info("正在初始化风控模块...")
            try:
                from ..risk_control import init_risk_control

                init_risk_control(config)
                logger.info("风控模块初始化完成")
            except Exception as exc:
                logger.exception("风控模块初始化失败: %s", exc)
                logger.warning("风控模块将被禁用")

        # 启动 ASR 服务监控
        try:
            from ..utils.asr_monitor import start_asr_monitor
            asr_monitor = start_asr_monitor(config)
            if asr_monitor:
                app.state.asr_monitor = asr_monitor
                logger.info("ASR 服务监控已启动")
        except Exception as exc:
            logger.warning(f"ASR 监控启动失败: {exc}")

        logger.info("API服务已启动")

    @app.on_event("shutdown")
    async def shutdown_event():
        summary_worker = getattr(app.state, "collection_summary_worker", None)
        if summary_worker is not None:
            summary_worker.stop(timeout=2.0)
        dispatcher = getattr(app.state, "cloud_asr_dispatcher", None)
        set_cloud_asr_dispatcher(None)
        if dispatcher is not None:
            dispatcher.stop(timeout=_CLOUD_RECOVERY_SHUTDOWN_JOIN_SECONDS)
        stop_event = getattr(app.state, "cloud_recovery_stop_event", None)
        if stop_event is not None:
            stop_event.set()
            get_transcription_concurrency_controller().wake_waiters()
        recovery = getattr(app.state, "cloud_recovery", None)
        if recovery is not None:
            recovery.stop()
        lock_handoff = getattr(
            app.state, "cloud_recovery_lock_handoff", None
        )
        if lock_handoff is not None:
            lock_handoff.set()
        recovery_thread = getattr(app.state, "cloud_recovery_thread", None)
        if recovery_thread is not None:
            recovery_thread.join(
                timeout=_CLOUD_RECOVERY_SHUTDOWN_JOIN_SECONDS
            )
        if recovery_thread is None or not recovery_thread.is_alive():
            _release_app_runtime_lock(app)

        progress_task = getattr(app.state, "progress_reminder_task", None)
        if progress_task:
            progress_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await progress_task

        temp_manager = get_temp_manager()
        temp_manager.clean_up()

        log_llm_stats()

        # 停止 ASR 监控
        if hasattr(app.state, "asr_monitor") and app.state.asr_monitor:
            app.state.asr_monitor.stop()

        shutdown_all_notifiers()
        logger.info("API服务已关闭")

    return app
