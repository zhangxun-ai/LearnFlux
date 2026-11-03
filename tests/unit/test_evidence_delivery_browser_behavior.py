"""Offline browser checks for source isolation and delivery interaction states."""

from pathlib import Path
import shutil
import subprocess


def test_evidence_and_delivery_browser_behavior():
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    assert node, "Node.js is required for browser behavior checks"
    result = subprocess.run(
        [node, "tests/frontend/evidence_delivery_behavior.cjs"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
