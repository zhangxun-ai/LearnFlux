"""Offline behavior checks for staged uploads and recoverable text imports."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_single_study_import_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for import behavior checks")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(root / "tests/frontend/single_study_behavior.cjs")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
