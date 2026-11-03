"""Exercise paid-generation boundaries and image-reader behavior in a browser harness."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_image_diagram_browser_behavior():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the browser behavior harness')
    result = subprocess.run(
        [node, 'tests/frontend/image_diagrams_behavior.cjs'],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
