import asyncio
import contextlib
import os
import threading
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

from ..utils.notifications import init_all_notifiers, shutdown_all_notifiers
from ..utils.source_file_cleanup import cleanup_old_source_files
from ..utils.ytdlp import YtdlpConfigBuilder
from ..llm import set_default_config, log_llm_stats
from ..llm.llm import log_llm_config_summary
from .context import get_cache_manager, get_config, get_logger, get_static_dir, get_temp_manager
from .services.progress_notifications import process_progress_reminders
from .routes import audit, collections, flywheel, health, journal, marks, obsidian, post_insight, settings, study, tasks, trend_radar, users, views, visual_learning
from .services.transcription import process_llm_queue, process_task_queue


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


def create_app() -> FastAPI:
    config = get_config()
    logger = get_logger()

    app = FastAPI(
        title="VideoTranscriptAPI",
        description="视频转录API服务",
        version="1.0.0",
    )

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
        if "/view/" in path or "/export/" in path:
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
    app.include_router(settings.router)

    @app.on_event("startup")
    async def startup_event():
        temp_manager = get_temp_manager()
        old_files_count = temp_manager.clean_up_old_files(hours=24)
        if old_files_count > 0:
            logger.info(f"启动时清理了 {old_files_count} 个旧临时文件")

        init_all_notifiers()

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
            try:
                recovered = cache_manager.recover_orphaned_tasks()
                if recovered:
                    logger.warning(
                        f"启动恢复：已将 {recovered} 个中断任务标记为 failed"
                    )
            except Exception as exc:
                logger.exception("启动恢复扫描失败: %s", exc)

            try:
                _run_source_file_cleanup(
                    cache_manager,
                    config.get("storage", {}) or {},
                    logger,
                )
            except Exception as exc:
                logger.exception("源文件清理失败: %s", exc)

        # 设置 LLM 模块默认配置（用于 JSON 结构化输出）
        set_default_config(config)
        logger.info("LLM default config set")

        # 打印每任务 provider+model+thinking 摘要（set_default_config 已注入 custom_patterns）
        log_llm_config_summary(config)

        # 初始化 yt-dlp 配置并验证 YouTube cookie
        logger.info("Initializing yt-dlp configuration...")
        ytdlp_builder = YtdlpConfigBuilder(config)
        ytdlp_builder.validate_cookie_on_startup()
        app.state.ytdlp_builder = ytdlp_builder

        logger.info("启动任务队列处理器")
        asyncio.create_task(process_task_queue())

        logger.info("启动任务进度提醒处理器")
        app.state.progress_reminder_task = asyncio.create_task(
            process_progress_reminders()
        )

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
        _release_runtime_lock(getattr(app.state, "runtime_lock_file", None))
        app.state.runtime_lock_file = None
        logger.info("API服务已关闭")

    return app
