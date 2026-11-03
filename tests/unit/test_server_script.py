"""Regression tests for the local API service management script."""

import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_start_installs_keepalive_launch_agent_on_macos(tmp_path):
    """macOS start must survive the shell or Codex session that invoked it."""
    script = tmp_path / "server.sh"
    shutil.copy2(PROJECT_ROOT / "server.sh", script)
    package = tmp_path / "src/video_transcript_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    shutil.copy2(PROJECT_ROOT / "src/video_transcript_api/config_env.py", package / "config_env.py")
    (tmp_path / ".env").write_text("LEARNFLUX_API_PORT=65431\n")
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
            "LEARNFLUX_LLM_API_KEY": "test-secret-must-stay-out-of-plist",
            "LEARNFLUX_API_PORT": "",
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
    assert "LEARNFLUX_LLM_API_KEY" not in service["EnvironmentVariables"]
    assert service["EnvironmentVariables"]["LEARNFLUX_API_PORT"] == ""
    assert "http://localhost:65432" in result.stdout
    assert "test-secret-must-stay-out-of-plist" not in plist_path.read_text()
    assert "bootstrap" in launchctl_log.read_text(encoding="utf-8")


@pytest.mark.parametrize("uv_directory", [".local/bin", ".cargo/bin"])
def test_start_finds_bootstrap_tools_outside_shell_path(tmp_path, uv_directory):
    """A fresh install can start before reopening the shell or installing Python globally."""
    script = tmp_path / "server.sh"
    shutil.copy2(PROJECT_ROOT / "server.sh", script)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.jsonc").write_text('{"api": {"port": 8000}}\n')
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    project_python = tmp_path / ".venv/bin/python"
    project_python.parent.mkdir(parents=True)
    _write_executable(
        project_python,
        '#!/usr/bin/env bash\nexec "$TEST_PYTHON" "$@"\n',
    )
    # A system Python must not be required after bootstrap prepared .venv.
    _write_executable(fake_bin / "python3", "#!/usr/bin/env bash\nexit 89\n")
    private_home = tmp_path / "home"
    uv = private_home / uv_directory / "uv"
    uv.parent.mkdir(parents=True)
    _write_executable(uv, "#!/usr/bin/env bash\nexit 0\n")
    marker = tmp_path / "started"
    _write_executable(
        fake_bin / "launchctl",
        '''#!/usr/bin/env bash
if [ "$1" = print ]; then exit 1; fi
if [ "$1" = bootstrap ]; then : > "$TEST_MARKER"; fi
''',
    )
    _write_executable(
        fake_bin / "lsof",
        '#!/usr/bin/env bash\nif [ -f "$TEST_MARKER" ]; then printf "4321\\n"; fi\n',
    )
    _write_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    launch_agent_dir = tmp_path / "LaunchAgents"
    env = os.environ | {
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin",
        "HOME": str(private_home),
        "LEARNFLUX_FORCE_LAUNCHD": "1",
        "LEARNFLUX_LAUNCH_AGENT_DIR": str(launch_agent_dir),
        "TEST_PYTHON": sys.executable,
        "TEST_MARKER": str(marker),
    }
    env.pop("LEARNFLUX_PYTHON_BIN", None)
    env.pop("LEARNFLUX_UV_BIN", None)
    result = subprocess.run(
        ["/bin/bash", str(script), "start"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with (launch_agent_dir / "com.learnflux.local.plist").open("rb") as handle:
        service = plistlib.load(handle)
    assert service["ProgramArguments"] == [str(uv), "run", "python", "main.py", "--start"]
    assert "http://localhost:8000" in result.stdout


@pytest.mark.parametrize("exported_port,expected_port", [(None, "65431"), ("65432", "65432"), ("", "8000")])
def test_status_uses_application_dotenv_port_without_executing_it(tmp_path, exported_port, expected_port):
    shutil.copy2(PROJECT_ROOT / "server.sh", tmp_path / "server.sh")
    package = tmp_path / "src/video_transcript_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    shutil.copy2(PROJECT_ROOT / "src/video_transcript_api/config_env.py", package / "config_env.py")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.jsonc").write_text('{"api": {"port": 8000}}')
    marker = tmp_path / "must-not-be-created"
    (tmp_path / ".env").write_text(
        f'LEARNFLUX_API_PORT=65431\nUNUSED=$(touch "{marker}")\n'
        'LEARNFLUX_LLM_API_KEY=test-private-value\n'
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "lsof", '#!/usr/bin/env bash\nprintf "4321\\n"\n')
    env = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LEARNFLUX_PYTHON_BIN": sys.executable,
    }
    env.pop("LEARNFLUX_API_PORT", None)
    if exported_port is not None:
        env["LEARNFLUX_API_PORT"] = exported_port
    result = subprocess.run(
        ["/bin/bash", str(tmp_path / "server.sh"), "status"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert f"http://localhost:{expected_port}" in result.stdout
    assert "test-private-value" not in result.stdout + result.stderr
    assert not marker.exists()


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
