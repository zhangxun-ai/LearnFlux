"""Regression tests for task recovery across concurrent API instances."""

import importlib

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_secondary_app_instance_does_not_recover_active_tasks(
    monkeypatch, tmp_path
):
    """A short-lived second app must not fail tasks owned by the live server."""
    app_module = importlib.import_module("video_transcript_api.api.app")

    cache_manager = MagicMock()
    cache_manager.cache_dir = tmp_path / "cache"
    cache_manager.recover_orphaned_tasks.return_value = 0

    temp_manager = MagicMock()
    temp_manager.clean_up_old_files.return_value = 0

    async def no_op_async():
        return None

    class FakeYtdlpConfigBuilder:
        def __init__(self, config):
            self.config = config

        def validate_cookie_on_startup(self):
            return None

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
    monkeypatch.setattr(app_module, "process_task_queue", no_op_async)
    monkeypatch.setattr(app_module, "process_progress_reminders", no_op_async)
    monkeypatch.setattr(app_module, "process_llm_queue", lambda: None)
    monkeypatch.setattr(
        "video_transcript_api.utils.asr_monitor.start_asr_monitor",
        lambda config: None,
    )

    primary_app = app_module.create_app()
    secondary_app = app_module.create_app()

    with TestClient(primary_app):
        with TestClient(secondary_app):
            pass

    assert cache_manager.recover_orphaned_tasks.call_count == 1
