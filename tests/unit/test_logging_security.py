"""Security regression tests for application logging."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_exception_logging_does_not_expose_local_secrets(tmp_path):
    """Exception diagnostics must keep tracebacks without dumping local secrets."""
    sentinel = "SENTINEL_SECRET_DO_NOT_USE"
    log_path = tmp_path / "app.log"
    script_path = tmp_path / "reproduce_secret_leak.py"
    script_path.write_text(
        """
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

logmod = importlib.import_module("video_transcript_api.utils.logging.logger")


class FailingClient:
    def __init__(self, config):
        self.config = config

    def get(self):
        raise RuntimeError("synthetic request failure")


def call_with_config(config):
    return FailingClient(config).get()


logmod.logger.remove()
logmod._logger_configured = False
log = logmod.setup_logger(
    "security_regression",
    config={
        "log": {
            "level": "INFO",
            "file": sys.argv[1],
            "max_size": 1024 * 1024,
            "backup_count": 1,
        }
    },
)

try:
    secret_config = {"tikhub": {"api_key": "SENTINEL_SECRET_DO_NOT_USE"}}
    call_with_config(secret_config)
except RuntimeError:
    log.exception("Synthetic request failed")

log.complete()
""".strip(),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script_path), str(log_path)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    console_output = completed.stdout + completed.stderr
    file_output = log_path.read_text(encoding="utf-8")

    assert "RuntimeError" in console_output
    assert "synthetic request failure" in console_output
    assert "RuntimeError: synthetic request failure" in file_output
    assert sentinel not in console_output
    assert sentinel not in file_output
