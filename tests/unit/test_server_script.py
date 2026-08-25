"""Regression tests for the local API service management script."""

import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_start_installs_keepalive_launch_agent_on_macos(tmp_path):
    """macOS start must survive the shell or Codex session that invoked it."""
    script = tmp_path / "server.sh"
    shutil.copy2(PROJECT_ROOT / "server.sh", script)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.jsonc").write_text(
        '{"api": {"port": 65432}}\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "launchd-started"
    launchctl_log = tmp_path / "launchctl.log"
    _write_executable(
        fake_bin / "launchctl",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_LAUNCHCTL_LOG"
if [ "$1" = "print" ]; then
    exit 1
fi
if [ "$1" = "bootstrap" ]; then
    : > "$TEST_LAUNCHD_MARKER"
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "lsof",
        """#!/usr/bin/env bash
if [ -f "$TEST_LAUNCHD_MARKER" ]; then
    printf '4321\\n'
fi
""",
    )
    _write_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "uv", "#!/usr/bin/env bash\nexit 0\n")

    launch_agent_dir = tmp_path / "LaunchAgents"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "LEARNFLUX_FORCE_LAUNCHD": "1",
            "LEARNFLUX_LAUNCH_AGENT_DIR": str(launch_agent_dir),
            "LEARNFLUX_PYTHON_BIN": sys.executable,
            "TEST_LAUNCHCTL_LOG": str(launchctl_log),
            "TEST_LAUNCHD_MARKER": str(marker),
        }
    )

    result = subprocess.run(
        ["bash", str(script), "start"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    plist_path = launch_agent_dir / "com.learnflux.local.plist"
    assert result.returncode == 0, result.stderr
    assert plist_path.exists()
    with plist_path.open("rb") as handle:
        service = plistlib.load(handle)
    assert service["Label"] == "com.learnflux.local"
    assert service["RunAtLoad"] is True
    assert service["KeepAlive"] is True
    assert service["WorkingDirectory"] == str(tmp_path)
    assert "bootstrap" in launchctl_log.read_text(encoding="utf-8")


def test_stop_unloads_and_removes_launch_agent(tmp_path):
    """Stopping the service must disable launchd auto-restart cleanly."""
    script = tmp_path / "server.sh"
    shutil.copy2(PROJECT_ROOT / "server.sh", script)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.jsonc").write_text(
        '{"api": {"port": 65432}}\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    launchctl_log = tmp_path / "launchctl.log"
    _write_executable(
        fake_bin / "launchctl",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_LAUNCHCTL_LOG"
exit 0
""",
    )
    _write_executable(fake_bin / "lsof", "#!/usr/bin/env bash\nexit 0\n")

    launch_agent_dir = tmp_path / "LaunchAgents"
    launch_agent_dir.mkdir()
    plist_path = launch_agent_dir / "com.learnflux.local.plist"
    plist_path.write_text("placeholder", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "LEARNFLUX_FORCE_LAUNCHD": "1",
            "LEARNFLUX_LAUNCH_AGENT_DIR": str(launch_agent_dir),
            "TEST_LAUNCHCTL_LOG": str(launchctl_log),
        }
    )

    result = subprocess.run(
        ["bash", str(script), "stop"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not plist_path.exists()
    assert "bootout" in launchctl_log.read_text(encoding="utf-8")


def test_stop_waits_for_tracked_process_after_listener_closes(tmp_path):
    """Restart must not launch a replacement while the old worker still lives."""
    script = tmp_path / "server.sh"
    shutil.copy2(PROJECT_ROOT / "server.sh", script)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.jsonc").write_text(
        '{"api": {"port": 65432}}\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()

    # Never let this test inspect or unload the user's real LaunchAgent. The
    # copied script still runs on macOS and would otherwise target the default
    # com.learnflux.local label even though its PID file lives in tmp_path.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    launchctl_log = tmp_path / "launchctl.log"
    _write_executable(
        fake_bin / "launchctl",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_LAUNCHCTL_LOG"
if [ "$1" = "print" ]; then
    exit 1
fi
exit 0
""",
    )

    worker = subprocess.Popen(
        ["bash", "-c", 'trap "" TERM; while :; do sleep 1; done'],
        start_new_session=True,
    )
    try:
        (tmp_path / "data" / "server.pid").write_text(
            str(worker.pid),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}:{env['PATH']}",
                "LEARNFLUX_LAUNCHD_LABEL": "com.learnflux.test.stop-wait",
                "LEARNFLUX_LAUNCH_AGENT_DIR": str(tmp_path / "LaunchAgents"),
                "STOP_TIMEOUT_SECONDS": "1",
                "TEST_LAUNCHCTL_LOG": str(launchctl_log),
            }
        )

        result = subprocess.run(
            ["bash", str(script), "stop"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        deadline = time.monotonic() + 2
        while worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)

        assert result.returncode == 0, result.stderr
        assert worker.poll() is not None
        assert "强制结束" in result.stdout
        assert launchctl_log.exists()
    finally:
        if worker.poll() is None:
            os.killpg(worker.pid, signal.SIGKILL)
            worker.wait(timeout=2)
