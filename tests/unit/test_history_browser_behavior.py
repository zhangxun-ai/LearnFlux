"""Behavioral regression checks for history loading and safe previews."""

import shutil
import subprocess
from pathlib import Path


def test_history_browser_behaviors():
    node = shutil.which("node")
    assert node, "Node.js is required for history browser behavior checks"
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "tests/frontend/history_browser_behavior.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
