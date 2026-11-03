"""Content versions shared by HTML renderers and the navigation generator.

Keep this module independent of application startup and private configuration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def get_static_asset_version(static_dir: Path | None = None) -> str:
    """Return a deterministic version for every shipped CSS and JavaScript file.

    Compute from content rather than a hand-maintained dependency list or the
    process start time, so a shared theme edit reaches every product page.
    """
    root = static_dir or Path(__file__).resolve().parents[2] / "web" / "static"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".css", ".js", ".mjs"}:
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:12]
