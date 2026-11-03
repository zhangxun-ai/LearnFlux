"""Offline regression coverage for the new-user bootstrap command."""

import os
from pathlib import Path
import subprocess
import sys

import commentjson


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _fake_command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _bootstrap(tmp_path, *, existing=False, options=()):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    config_path = tmp_path / "config.jsonc"
    if existing:
        config_path.write_text('{"api": {"auth_token": "keep-this"}}\n', encoding="utf-8")
    _fake_command(fake_bin, "uv", r'''printf "uv %s\n" "$*" >> "$LEARNFLUX_TEST_LOG"
if [ "$1" = run ]; then
    shift
    [ "$1" = --no-sync ] && shift
    [ "$1" = python ] && shift
    exec "$LEARNFLUX_TEST_PYTHON" "$@"
fi''')
    # Exclude Homebrew's FFmpeg/uv so a text-only bootstrap cannot rely on them.
    env = os.environ | {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "LEARNFLUX_CONFIG_PATH": str(config_path),
        "LEARNFLUX_TEST_LOG": str(command_log),
        "LEARNFLUX_TEST_PYTHON": sys.executable,
    }
    result = subprocess.run(
        ["/bin/bash", str(PROJECT_ROOT / "scripts/bootstrap.sh"), *options],
        cwd=PROJECT_ROOT, env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return config_path, command_log.read_text(), result


def test_text_bootstrap_needs_no_ffmpeg_and_initializes_private_config(tmp_path):
    path, commands, result = _bootstrap(tmp_path)
    config = commentjson.loads(path.read_text())
    assert commands.splitlines()[0] == "uv sync --frozen --python 3.11"
    assert "uv run --no-sync python scripts/init_config.py" in commands
    assert config["api"]["host"] == "127.0.0.1"
    assert len(config["api"]["auth_token"]) >= 48
    assert config["api"]["auth_token"] not in result.stdout + result.stderr


def test_bootstrap_keeps_existing_configuration(tmp_path):
    path, _, result = _bootstrap(tmp_path, existing=True)
    assert path.read_text() == '{"api": {"auth_token": "keep-this"}}\n'
    assert "Keeping existing configuration unchanged" in result.stdout
    assert "keep-this" not in result.stdout + result.stderr


def test_bootstrap_installs_dev_dependencies_only_when_requested(tmp_path):
    _, commands, _ = _bootstrap(tmp_path, options=("--dev",))
    assert commands.splitlines()[0] == "uv sync --frozen --python 3.11 --extra dev"
