"""Regression tests for task recovery across concurrent API instances."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from video_transcript_api.transcriber.concurrency import (
    TranscriptionConcurrencyController,
)


def test_secondary_app_instance_does_not_recover_active_tasks(
    monkeypatch, tmp_path
):
    """Only the primary app performs ordered, capacity-limited recovery."""
    app_module = importlib.import_module("video_transcript_api.api.app")

    trace = []
    dispatcher_started = Event()
    reserved_resumed = Event()
    released_locks = []
    cache_manager = MagicMock()
    cache_manager.cache_dir = tmp_path / "cache"
    cache_manager.db_path = tmp_path / "cache" / "cache.db"
    cache_manager.recover_orphaned_tasks.return_value = 0
    cache_manager.recover_orphaned_tasks.side_effect = (
        lambda **kwargs: trace.append("orphan") or 0
    )
    source_cleanup = MagicMock()
    reading_cleanup = MagicMock(
        side_effect=lambda *args, **kwargs: trace.append("reading_cleanup")
    )

    temp_manager = MagicMock()
    temp_manager.get_temp_dir.return_value = tmp_path / "temp"
    temp_manager.clean_up_old_files.return_value = 0
    temp_manager.clean_up_old_files.side_effect = (
        lambda **kwargs: trace.append("temp_cleanup") or 0
    )

    class FakeUsageRepository:
        def list_protected_task_ids(self):
            trace.append("protected_tasks")
            return set()

        def list_protected_snapshot_roots(self, temp_root):
            trace.append("protected_roots")
            return set()

        def list_recoverable_events(self):
            return []

        def list_pending_postprocess(self):
            return []

        def fail_orphan_reserved(self, *, created_before, excluded_event_ids=()):
            trace.append("reserved_recovery")
            assert set(excluded_event_ids) == {"reserved-event"}
            return []

        def list_remote_capacity_attempt_ids(self):
            trace.append("capacity_recovery")
            return ["existing-event"]

        def remote_attempt_occupies_capacity(self, event_id):
            return False

    class FakeCloudQuoteRepository:
        def reconcile_usage_attempts(self):
            trace.append("quote_reconcile")
            return []

        def expire_stale_unconfirmed(self):
            return []

    class FakeRecovery:
        def stop(self):
            return None

        def recover_pending(self):
            trace.append("cloud_recovery")
            return []

    class FakeDispatcher:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            trace.append("dispatcher")
            dispatcher_started.set()

        def stop(self, timeout):
            return True

    usage_repository = FakeUsageRepository()
    quote_repository = FakeCloudQuoteRepository()
    control_store = SimpleNamespace(
        usage_repository=usage_repository,
        quote_repository=quote_repository,
    )
    quote_root = tmp_path / "temp" / "cloud_quotes" / ("a" * 64) / "quote-1"
    record = SimpleNamespace(event_id="reserved-event")
    controller = TranscriptionConcurrencyController(
        local=1, cloud=1, local_hard=2, cloud_hard=1
    )
    cloud_executor = ThreadPoolExecutor(max_workers=1)

    class RecordingExecutor:
        def submit(self, callback, *args):
            trace.append("reserved_enqueue")
            return cloud_executor.submit(callback, *args)

    async def no_op_async():
        return None

    class FakeYtdlpConfigBuilder:
        def __init__(self, config):
            self.config = config

        def validate_cookie_on_startup(self):
            return None

    class FakeSummaryWorker:
        def __init__(self, service, **kwargs):
            trace.append("summary_worker_init")

        def start(self):
            trace.append("summary_worker_start")
            return {"requeued_jobs": 0, "legacy_failed": 0}

        def stop(self, timeout):
            trace.append("summary_worker_stop")

    monkeypatch.setattr(app_module, "get_cache_manager", lambda: cache_manager)
    monkeypatch.setattr(app_module, "get_temp_manager", lambda: temp_manager)
    monkeypatch.setattr(
        app_module,
        "get_config",
        lambda: {"storage": {"cache_dir": str(cache_manager.cache_dir)}},
    )
    monkeypatch.setattr(app_module, "get_logger", MagicMock)
    monkeypatch.setattr(app_module, "init_all_notifiers", lambda: None)
    monkeypatch.setattr(app_module, "shutdown_all_notifiers", lambda: None)
    monkeypatch.setattr(app_module, "set_default_config", lambda config: None)
    monkeypatch.setattr(app_module, "log_llm_config_summary", lambda config: None)
    monkeypatch.setattr(app_module, "log_llm_stats", lambda: None)
    monkeypatch.setattr(app_module, "YtdlpConfigBuilder", FakeYtdlpConfigBuilder)
    monkeypatch.setattr(app_module, "CollectionSummaryWorker", FakeSummaryWorker)
    monkeypatch.setattr(
        app_module.collections, "get_collection_service", lambda: object()
    )
    monkeypatch.setattr(app_module, "cleanup_old_source_files", source_cleanup)
    monkeypatch.setattr(
        app_module, "_recover_reading_deletions", reading_cleanup
    )
    monkeypatch.setattr(app_module, "process_task_queue", no_op_async)
    monkeypatch.setattr(app_module, "process_progress_reminders", no_op_async)
    monkeypatch.setattr(app_module, "process_llm_queue", lambda: None)
    monkeypatch.setattr(
        app_module,
        "get_transcription_concurrency_controller", lambda: controller,
    )
    monkeypatch.setattr(
        app_module, "get_cloud_asr_executor", lambda: RecordingExecutor()
    )
    monkeypatch.setattr(app_module, "set_cloud_asr_dispatcher", lambda value: None)
    monkeypatch.setattr(
        app_module, "get_transcription_control_store", lambda: control_store
    )
    monkeypatch.setattr(
        app_module,
        "build_aliyun_recovery",
        lambda **kwargs: FakeRecovery(),
    )
    monkeypatch.setattr(
        app_module,
        "identify_quote_backed_reserved",
        lambda store, temp_root, cutoff: (
            trace.append("identify_reserved")
            or SimpleNamespace(records=(record,), media_roots=frozenset({quote_root}))
        ),
    )
    monkeypatch.setattr(
        app_module,
        "reconcile_stale_local_queued",
        lambda repository, temp_root, cutoff: trace.append("local_reconcile") or [],
    )
    monkeypatch.setattr(
        app_module, "build_aliyun_reserved_provider", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        app_module,
        "resume_quote_backed_reserved_attempt",
        lambda item, **kwargs: (
            trace.append("reserved_resume"), reserved_resumed.set()
        ),
    )
    monkeypatch.setattr(app_module, "CloudASRDispatcher", FakeDispatcher)
    monkeypatch.setattr(
        app_module,
        "dispatch_pending_post_asr",
        lambda **kwargs: trace.append("postprocess_scan") or 0,
    )
    primary_lock = object()
    lock_results = iter([primary_lock, None])
    monkeypatch.setattr(
        app_module,
        "_acquire_runtime_lock",
        lambda cache_dir: trace.append("lock") or next(lock_results),
    )
    def record_runtime_lock_release(lock):
        released_locks.append(lock)

    monkeypatch.setattr(
        app_module, "_release_runtime_lock", record_runtime_lock_release
    )
    monkeypatch.setattr(
        "video_transcript_api.utils.asr_monitor.start_asr_monitor",
        lambda config: None,
    )

    primary_app = app_module.create_app()
    secondary_app = app_module.create_app()

    with TestClient(primary_app):
        assert dispatcher_started.wait(timeout=1)
        assert not reserved_resumed.wait(timeout=0.05)
        controller.release("cloud", "usage:existing-event")
        assert reserved_resumed.wait(timeout=1)
        with TestClient(secondary_app):
            pass

    cloud_executor.shutdown(wait=True)
    assert released_locks == [primary_lock]

    assert cache_manager.recover_orphaned_tasks.call_count == 1
    assert trace.count("summary_worker_start") == 1
    assert trace.count("summary_worker_stop") == 1
    cache_manager.recover_orphaned_tasks.assert_called_once_with(
        protected_task_ids=set()
    )
    assert temp_manager.clean_up_old_files.call_count == 1
    assert source_cleanup.call_count == 1
    assert reading_cleanup.call_count == 1
    assert trace.index("quote_reconcile") < trace.index("identify_reserved")
    assert trace.index("identify_reserved") < trace.index("reserved_recovery")
    assert trace.index("protected_roots") < trace.index("temp_cleanup")
    assert quote_root in temp_manager.clean_up_old_files.call_args.kwargs[
        "protected_roots"
    ]
    assert trace.index("reserved_recovery") < trace.index("temp_cleanup")
    assert trace.index("temp_cleanup") < trace.index("orphan")
    assert trace.index("orphan") < trace.index("reading_cleanup")
    assert trace.index("orphan") < trace.index("cloud_recovery")
    assert trace.index("cloud_recovery") < trace.index("reserved_enqueue")
    assert trace.index("reserved_enqueue") < trace.index("dispatcher")
    assert trace.count("reserved_resume") == 1


def test_source_file_cleanup_respects_disabled_config(monkeypatch):
    app_module = importlib.import_module("video_transcript_api.api.app")
    source_cleanup = MagicMock()
    monkeypatch.setattr(app_module, "cleanup_old_source_files", source_cleanup)

    app_module._run_source_file_cleanup(
        MagicMock(),
        {"source_file_cleanup_enabled": False},
        MagicMock(),
    )

    source_cleanup.assert_not_called()
