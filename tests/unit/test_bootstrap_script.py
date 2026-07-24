"""Regression coverage for the new-user bootstrap command."""

import os
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _fake_command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_bootstrap_syncs_dependencies_without_overwriting_existing_config(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    config_path = tmp_path / "config.jsonc"
    config_path.write_text('{"api": {"auth_token": "keep-this"}}\n', encoding="utf-8")
    _fake_command(
        fake_bin,
        "uv",
        'printf "uv %s\\n" "$*" >> "$LEARNFLUX_TEST_LOG"',
    )
    _fake_command(fake_bin, "ffmpeg", "exit 0")

    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "LEARNFLUX_CONFIG_PATH": str(config_path),
        "LEARNFLUX_TEST_LOG": str(command_log),
    }
    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "bootstrap.sh")],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert config_path.read_text(encoding="utf-8") == '{"api": {"auth_token": "keep-this"}}\n'
    assert command_log.read_text(encoding="utf-8") == "uv sync --extra dev\n"
