"""Run offline task-status DOM behavior regression checks."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_submitted_task_status_behavior():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for task status behavior checks')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(root / 'tests/frontend/task_status_behavior.cjs')],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
