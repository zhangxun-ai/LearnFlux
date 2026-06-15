"""
Health check endpoint unit tests.

Covers:
- SQLite health check
- Disk space check
- TCP port check (fallback)
- Overall health status aggregation

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest


from video_transcript_api.api.routes.health import (
    health_check,
    _check_local_whisper,
    _check_sqlite,
    _check_disk_space,
    _check_tcp_port,
)


class TestSQLiteHealthCheck:
    """Verify SQLite health check."""

    @patch("video_transcript_api.api.routes.health.get_cache_manager")
    def test_sqlite_healthy(self, mock_cm):
        """SQLite check should return healthy when DB is accessible."""
        mock_instance = MagicMock()
        mock_instance.db_path = ":memory:"
        mock_cm.return_value = mock_instance

        result = _check_sqlite()
        assert result["healthy"] is True

    @patch("video_transcript_api.api.routes.health.get_cache_manager")
    def test_sqlite_unhealthy(self, mock_cm):
        """SQLite check should return unhealthy on error."""
        mock_cm.side_effect = Exception("db locked")

        result = _check_sqlite()
        assert result["healthy"] is False
        assert "error" in result


class TestDiskSpaceCheck:
    """Verify disk space check."""

    def test_disk_space_returns_result(self):
        """Disk space check should return a valid result."""
        result = _check_disk_space()
        assert "healthy" in result
        assert "free_gb" in result
        assert isinstance(result["free_gb"], float)

    @patch("video_transcript_api.api.routes.health.os.statvfs")
    def test_disk_space_low(self, mock_statvfs):
        """Low disk space should return unhealthy."""
        mock_stat = MagicMock()
        mock_stat.f_bavail = 100  # Very low
        mock_stat.f_frsize = 4096
        mock_statvfs.return_value = mock_stat

        result = _check_disk_space()
        assert result["healthy"] is False
        assert "low disk space" in result.get("error", "")


class TestLocalWhisperHealthCheck:
    """Verify local whisper health check."""

    def test_local_whisper_binary_present(self, tmp_path):
        """Existing binary should be healthy."""
        binary = tmp_path / "mlx_whisper"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")

        result = _check_local_whisper({"enabled": True, "binary": str(binary)})

        assert result["healthy"] is True

    def test_local_whisper_binary_missing(self, tmp_path):
        """Missing binary should be unhealthy."""
        result = _check_local_whisper({
            "enabled": True,
            "binary": str(tmp_path / "missing"),
        })

        assert result["healthy"] is False
        assert "missing" in result.get("error", "")


class TestOverallHealthCheck:
    """Verify overall health aggregation follows active ASR engine."""

    @pytest.mark.asyncio
    async def test_local_whisper_skips_capswriter_probe(self, monkeypatch, tmp_path):
        """When local whisper is enabled, CapsWriter should not affect health."""
        binary = tmp_path / "mlx_whisper"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        calls = []

        async def fake_ws_check(url, name):
            calls.append((url, name))
            return {"healthy": True}

        monkeypatch.setattr(
            "video_transcript_api.api.routes.health.config",
            {
                "local_whisper": {"enabled": True, "binary": str(binary)},
                "capswriter": {"server_url": "ws://localhost:6016"},
                "funasr_spk_server": {"server_url": "ws://localhost:8767"},
            },
        )
        monkeypatch.setattr(
            "video_transcript_api.api.routes.health._check_sqlite",
            lambda: {"healthy": True},
        )
        monkeypatch.setattr(
            "video_transcript_api.api.routes.health._check_disk_space",
            lambda: {"healthy": True, "free_gb": 10.0},
        )
        monkeypatch.setattr(
            "video_transcript_api.api.routes.health._check_websocket_service",
            fake_ws_check,
        )

        result = await health_check()

        assert result["checks"]["local_whisper"]["healthy"] is True
        assert result["checks"]["capswriter"]["skipped"] is True
        assert calls == [("ws://localhost:8767", "FunASR")]

    @pytest.mark.asyncio
    async def test_funasr_is_optional_when_local_whisper_handles_default_transcription(
        self, monkeypatch, tmp_path
    ):
        """Unavailable FunASR should not fail default transcription readiness."""
        binary = tmp_path / "mlx_whisper"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")

        async def fake_ws_check(url, name):
            return {"healthy": False, "error": "connection refused"}

        monkeypatch.setattr(
            "video_transcript_api.api.routes.health.config",
            {
                "local_whisper": {"enabled": True, "binary": str(binary)},
                "funasr_spk_server": {"server_url": "ws://localhost:8767"},
            },
        )
        monkeypatch.setattr(
            "video_transcript_api.api.routes.health._check_sqlite",
            lambda: {"healthy": True},
        )
        monkeypatch.setattr(
            "video_transcript_api.api.routes.health._check_disk_space",
            lambda: {"healthy": True, "free_gb": 10.0},
        )
        monkeypatch.setattr(
            "video_transcript_api.api.routes.health._check_websocket_service",
            fake_ws_check,
        )

        result = await health_check()

        assert result["status"] == "healthy"
        assert result["checks"]["funasr"]["healthy"] is False
        assert result["checks"]["funasr"]["required"] is False
        assert result["checks"]["funasr"]["feature"] == "speaker_recognition"


class TestTCPPortCheck:
    """Verify TCP port fallback check."""

    @patch("socket.socket")
    def test_port_reachable(self, mock_socket_cls):
        """Reachable port should return healthy."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_socket_cls.return_value = mock_sock

        result = _check_tcp_port("ws://localhost:6016", "CapsWriter")
        assert result["healthy"] is True

    @patch("socket.socket")
    def test_port_unreachable(self, mock_socket_cls):
        """Unreachable port should return unhealthy."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 111  # Connection refused
        mock_socket_cls.return_value = mock_sock

        result = _check_tcp_port("ws://localhost:9999", "FunASR")
        assert result["healthy"] is False
        assert "unreachable" in result.get("error", "")
