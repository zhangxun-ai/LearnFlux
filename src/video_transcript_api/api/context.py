import asyncio
import concurrent.futures
import os
import queue
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from fastapi.templating import Jinja2Templates

from ..utils.accounts import get_user_manager as _get_user_manager_impl
from ..cache import CacheManager
from ..llm import LLMCoordinator
from ..utils.logging import get_audit_logger as _get_audit_logger_impl
from ..utils.logging import load_config as _load_config_impl
from ..utils.logging import setup_logger
from ..utils.tempfile_manager import TempFileManager
from ..transcriber.concurrency import (
    LOCAL_ASR_HARD_LIMIT,
    TranscriptionConcurrencyController,
    resolve_transcription_limits,
)
from ..transcriber.control_store import (
    PostgresTranscriptionControlStore,
    SQLiteTranscriptionControlStore,
)
from ..transcriber.online_runtime import OnlineRuntimeSettings
from ..transcriber.object_store import LocalObjectStore, S3ObjectStore
from ..transcriber.submission_guard import CloudSubmissionGuard
from ..persistence import get_persistence_database

# Lazy initialized runtime resources
_task_queue: asyncio.Queue | None = None
_executor: concurrent.futures.ThreadPoolExecutor | None = None
_local_asr_executor: concurrent.futures.ThreadPoolExecutor | None = None
_cloud_asr_executor: concurrent.futures.ThreadPoolExecutor | None = None
_transcription_concurrency_controller: TranscriptionConcurrencyController | None = None
_cloud_asr_dispatcher: Any | None = None
_cloud_asr_dispatcher_guard = threading.Lock()
_cloud_submission_guard: CloudSubmissionGuard | None = None
_llm_task_queue: queue.Queue | None = None
_llm_executor: concurrent.futures.ThreadPoolExecutor | None = None
_templates: Jinja2Templates | None = None
_task_locks: Dict[str, threading.Lock] = {}
_task_locks_guard = threading.Lock()


@lru_cache
def get_logger():
    """Return the API logger singleton."""
    return setup_logger("api_server")


@lru_cache
def get_config():
    """Load configuration once."""
    return _load_config_impl()


@lru_cache
def get_user_manager():
    """User manager shared across routes."""
    return _get_user_manager_impl(fallback_config=get_config())


@lru_cache
def get_audit_logger():
    """Audit logger singleton."""
    return _get_audit_logger_impl(get_persistence_database())


@lru_cache
def get_online_runtime_settings() -> OnlineRuntimeSettings:
    """Return validated infrastructure selection without logging its values."""
    return OnlineRuntimeSettings.from_environ(os.environ)


@lru_cache
def get_transcription_control_store():
    """Return the single task/quote/usage authority for this process."""
    settings = get_online_runtime_settings()
    if settings.persistence_backend == "postgres":
        return PostgresTranscriptionControlStore(
            database=get_persistence_database()
        )
    cache_dir = get_config().get("storage", {}).get("cache_dir", "./data/cache")
    return SQLiteTranscriptionControlStore(Path(cache_dir) / "cache.db")


def get_cloud_quote_repository():
    return get_transcription_control_store().quote_repository


def get_usage_repository():
    return get_transcription_control_store().usage_repository


def get_transcription_control_database(cache_manager=None):
    """Resolve the selected control DB while preserving legacy local callers."""
    return get_repository_database(cache_manager)


def get_repository_database(cache_manager=None):
    """Return a real database adapter or a concrete legacy SQLite path."""

    manager = cache_manager or get_cache_manager()
    database = getattr(manager, "database", None)
    if getattr(database, "dialect", None) in {"sqlite", "postgres"}:
        return database
    repository = getattr(manager, "_task_status_repository", None)
    repository_database = getattr(repository, "database", None)
    if getattr(repository_database, "dialect", None) in {"sqlite", "postgres"}:
        return repository_database
    db_path = getattr(manager, "db_path", None)
    if isinstance(db_path, (str, Path)):
        return db_path
    raise RuntimeError("persistence_database_unavailable")


@lru_cache
def get_transcription_object_store():
    """Return private temporary media storage for the selected runtime."""
    settings = get_online_runtime_settings()
    if settings.object_backend == "s3":
        return S3ObjectStore.from_settings(settings)
    temp_dir = get_config().get("storage", {}).get("temp_dir", "./data/temp")
    return LocalObjectStore(Path(temp_dir) / "online_objects")


@lru_cache
def get_cache_manager():
    cache_dir = get_config().get("storage", {}).get("cache_dir", "./data/cache")
    database = get_persistence_database()
    manager = CacheManager(cache_dir, database=database)
    if database is not None:
        manager.set_task_status_repository(get_transcription_control_store())
    return manager


@lru_cache
def get_temp_manager():
    temp_dir = get_config().get("storage", {}).get("temp_dir", "./data/temp")
    return TempFileManager(temp_dir)


@lru_cache
def get_workspace_dir() -> str:
    workspace_dir = (
        get_config().get("storage", {}).get("workspace_dir", "./data/workspace")
    )
    return workspace_dir


@lru_cache
def get_llm_coordinator():
    """获取 LLM 协调器（新架构）"""
    config = get_config()
    cache_dir = config.get("storage", {}).get("cache_dir", "./data/cache")
    return LLMCoordinator(
        config_dict=config,
        cache_dir=cache_dir,
        artifact_cache_manager=get_cache_manager(),
    )


def get_task_queue() -> asyncio.Queue:
    """Create (if needed) and return the transcription task queue."""
    global _task_queue
    if _task_queue is None:
        queue_size = get_config().get("concurrent", {}).get("queue_size", 10)
        _task_queue = asyncio.Queue(queue_size)
    return _task_queue


def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the shared transcription thread pool."""
    global _executor
    if _executor is None:
        max_workers = get_config().get("concurrent", {}).get("max_workers", 3)
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    return _executor


def get_transcription_concurrency_controller() -> TranscriptionConcurrencyController:
    """Return the process-wide ASR concurrency controller."""
    global _transcription_concurrency_controller
    if _transcription_concurrency_controller is None:
        limits = resolve_transcription_limits(
            get_config(), warn=get_logger().warning
        )
        _transcription_concurrency_controller = TranscriptionConcurrencyController(
            local=limits.local_soft,
            cloud=limits.cloud_soft,
            local_hard=limits.local_hard,
            cloud_hard=limits.cloud_hard,
        )
    return _transcription_concurrency_controller


def get_local_asr_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the provider-only local ASR executor."""
    global _local_asr_executor
    if _local_asr_executor is None:
        _local_asr_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=LOCAL_ASR_HARD_LIMIT,
            thread_name_prefix="local-asr",
        )
    return _local_asr_executor


def get_cloud_asr_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the provider-only cloud ASR executor."""
    global _cloud_asr_executor
    if _cloud_asr_executor is None:
        hard_limit = get_transcription_concurrency_controller().snapshot()[
            "cloud_asr_hard_limit"
        ]
        _cloud_asr_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=hard_limit,
            thread_name_prefix="cloud-asr",
        )
    return _cloud_asr_executor


def get_cloud_submission_guard() -> CloudSubmissionGuard:
    """Return the process-wide serialized cloud upload guard."""
    global _cloud_submission_guard
    if _cloud_submission_guard is None:
        _cloud_submission_guard = CloudSubmissionGuard()
    return _cloud_submission_guard


def set_cloud_asr_dispatcher(dispatcher: Any | None) -> None:
    """Publish or clear the active cloud dispatcher without exposing config."""
    global _cloud_asr_dispatcher
    with _cloud_asr_dispatcher_guard:
        _cloud_asr_dispatcher = dispatcher


def get_cloud_asr_dispatcher() -> Any:
    """Return the active cloud dispatcher or fail closed during startup/shutdown."""
    with _cloud_asr_dispatcher_guard:
        if _cloud_asr_dispatcher is None:
            raise RuntimeError("cloud_asr_dispatcher_unavailable")
        return _cloud_asr_dispatcher


def get_llm_queue() -> queue.Queue:
    """Queue used for serialized LLM post-processing tasks."""
    global _llm_task_queue
    if _llm_task_queue is None:
        _llm_task_queue = queue.Queue(maxsize=100)
    return _llm_task_queue


def get_llm_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Thread pool dedicated to LLM post-processing."""
    global _llm_executor
    if _llm_executor is None:
        max_workers = get_config().get("concurrent", {}).get("llm_max_workers", 10)
        _llm_executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    return _llm_executor


@contextmanager
def task_lock(task_id: str | None):
    """Context manager guarding operations for the same task_id."""
    key = task_id or "default"
    with _task_locks_guard:
        lock = _task_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _task_locks[key] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _task_locks_guard:
            if not lock.locked():
                _task_locks.pop(key, None)


def get_template_dir() -> Path:
    """Return src/web/templates directory path."""
    return Path(__file__).resolve().parents[2] / "web" / "templates"


def get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=str(get_template_dir()))
        # 模板页资源版本号：用共享静态资源的 mtime 破坏 CSS/JS 浏览器缓存，
        # 部署/改样式后回访用户即可拿到新版（模板里用 ?v={{ asset_ver }}）。
        try:
            static_dir = get_static_dir()
            version_files = [
                static_dir / "css" / "editorial.css",
                static_dir / "css" / "visual-learning.css",
                static_dir / "css" / "obsidian-knowledge.css",
                static_dir / "css" / "product-linear.css",
                static_dir / "css" / "product-linear-core.css",
                static_dir / "css" / "product-linear-insights.css",
                static_dir / "css" / "product-linear-system.css",
                static_dir / "js" / "pwa-register.js",
                static_dir / "js" / "ui-features.js",
                static_dir / "js" / "app-shell.js",
                static_dir / "js" / "floating-toc.js",
                static_dir / "js" / "visual-learning.js",
                static_dir / "js" / "transcript-visual-reader.js",
                static_dir / "js" / "obsidian-knowledge.js",
            ]
            version = max((f.stat().st_mtime for f in version_files if f.exists()), default=0)
            _templates.env.globals["asset_ver"] = str(int(version))
        except OSError:
            _templates.env.globals["asset_ver"] = "1"
    return _templates


def get_static_dir() -> Path:
    """Return src/web/static directory path."""
    return Path(__file__).resolve().parents[2] / "web" / "static"
