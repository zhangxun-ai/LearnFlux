"""Regression tests for optional external-access diagnostics."""

import asyncio
import importlib
from unittest.mock import MagicMock

import httpx
import pytest

from video_transcript_api.api.app import external_access_debug_enabled


@pytest.mark.unit
def test_external_access_logging_is_disabled_without_explicit_opt_in():
    """Normal requests must not emit detailed diagnostic logs by default."""
    assert external_access_debug_enabled({}) is False
    assert external_access_debug_enabled({"log": {}}) is False
    assert external_access_debug_enabled(
        {"log": {"external_access_debug": True}}
    ) is True
    assert external_access_debug_enabled(
        {"log": {"external_access_debug": "true"}}
    ) is False


@pytest.mark.unit
def test_disabled_external_access_diagnostics_do_not_log_requests(monkeypatch):
    """A disabled diagnostic flag must suppress /view request logging."""
    app_module = importlib.import_module("video_transcript_api.api.app")
    logger = MagicMock()
    monkeypatch.setattr(app_module, "get_config", lambda: {})
    monkeypatch.setattr(app_module, "get_logger", lambda: logger)
    app = app_module.create_app()

    async def request_view():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.get("/view/noise-reduction-probe")

    response = asyncio.run(request_view())

    assert response.status_code == 200
    logger.info.assert_not_called()
