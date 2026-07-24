"""Regression tests for the local API service management script."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        env["STOP_TIMEOUT_SECONDS"] = "1"

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
    finally:
        if worker.poll() is None:
            os.killpg(worker.pid, signal.SIGKILL)
            worker.wait(timeout=2)
