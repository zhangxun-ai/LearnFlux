"""Unit tests for the LongCut local integration helpers."""

from pathlib import Path
from unittest.mock import patch

from video_transcript_api.api.services.longcut import (
    LongCutSettings,
    build_analysis_url,
    build_longcut_action,
    ensure_longcut_ready,
    get_longcut_settings,
)


def _settings(project_dir: Path | None = None) -> LongCutSettings:
    return LongCutSettings(
        enabled=True,
        base_url="http://localhost:3000",
        project_dir=project_dir,
        script_name="server.sh",
        startup_timeout_seconds=3,
        auto_start=True,
    )


def test_get_longcut_settings_uses_config_values(tmp_path):
    settings = get_longcut_settings(
        {
            "longcut": {
                "enabled": True,
                "base_url": "http://localhost:3000/some/path",
                "project_dir": str(tmp_path),
                "script_name": "dev.sh",
                "startup_timeout_seconds": 12,
                "auto_start": False,
            }
        }
    )

    assert settings.enabled is True
    assert settings.base_url == "http://localhost:3000"
    assert settings.project_dir == tmp_path
    assert settings.script_name == "dev.sh"
    assert settings.startup_timeout_seconds == 12
    assert settings.auto_start is False


def test_build_analysis_url_escapes_video_id():
    assert (
        build_analysis_url("http://localhost:3000/", "abc 123")
        == "http://localhost:3000/analyze/abc%20123"
    )


def test_build_longcut_action_for_youtube_view():
    action = build_longcut_action(
        {
            "platform": "youtube",
            "media_id": "abc123",
            "view_token": "vt-1",
        },
        _settings(),
    )

    assert action is not None
    assert action["url"] == "/view/vt-1/longcut"
    assert action["target_url"] == "http://localhost:3000/analyze/abc123"


def test_build_longcut_action_skips_non_youtube():
    action = build_longcut_action(
        {
            "platform": "bilibili",
            "media_id": "BV123",
            "view_token": "vt-1",
        },
        _settings(),
    )

    assert action is None


def test_ensure_longcut_ready_returns_when_already_running():
    with patch(
        "video_transcript_api.api.services.longcut._is_url_ready",
        return_value=True,
    ), patch("video_transcript_api.api.services.longcut.subprocess.Popen") as popen:
        result = ensure_longcut_ready(_settings())

    assert result.ready is True
    assert result.started is False
    popen.assert_not_called()


def test_ensure_longcut_ready_starts_with_script(tmp_path):
    script = tmp_path / "server.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    with patch(
        "video_transcript_api.api.services.longcut._is_url_ready",
        side_effect=[False, True],
    ), patch("video_transcript_api.api.services.longcut.subprocess.Popen") as popen:
        result = ensure_longcut_ready(_settings(tmp_path))

    assert result.ready is True
    assert result.started is True
    popen.assert_called_once()
    assert popen.call_args.args[0][-1] == "start"


def test_ensure_longcut_ready_reports_missing_script(tmp_path):
    with patch(
        "video_transcript_api.api.services.longcut._is_url_ready",
        return_value=False,
    ):
        result = ensure_longcut_ready(_settings(tmp_path))

    assert result.ready is False
    assert result.started is False
    assert "startup script not found" in result.message
