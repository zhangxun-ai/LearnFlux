#!/usr/bin/env python3
"""Capture the current UI with authored fixtures; never start the real backend.

Requires Node/npx, Chromium for playwright-cli, FFmpeg and cwebp.
Run from the repository with ``uv run --no-sync python scripts/capture_readme.py``.
"""

from __future__ import annotations

import argparse
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading

from readme_demo import CASE_SOURCES, DemoHandler, ROOT, STATIC, TITLE, get_static_asset_version


NAMES = ["01-import", "02-result", "03-collections", "04-reading-library",
         "05-reading", "06-writing", "07-history", "08-briefings", "09-player"]
ROUTES = ["/add_task_by_web", "/view/demo-note-0", "/collections?collection_id=demo-course",
          "/reading", "/reading/demo-book-0", "/static/focus-studio.html",
          "/static/history.html", "/briefings", "/study/demo-note-1"]
WORK = ROOT / "output/playwright/readme-20261103-cases"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/images/readme-20261103-cases")
    args = parser.parse_args()
    for executable in ("npx", "ffmpeg", "cwebp"):
        if not shutil.which(executable):
            parser.error(f"Required executable missing: {executable}")
    WORK.mkdir(parents=True, exist_ok=True)
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
                    "-i", str(STATIC / "images/landing/learnflux-reading-nook-cover.webp"),
                    "-t", "45", "-vf", "scale=960:-2", "-r", "24", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(WORK / "demo-video.mp4")], check=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    session = f"readme-{server.server_port}"
    cli = ["npx", "--yes", "--package", "@playwright/cli@0.1.23", "playwright-cli", "--session", session]
    code = (ROOT / "scripts/readme_capture.cjs").read_text().replace(
        "__DEMO_BASE__", json.dumps(base)).replace("__CAPTURE_OUTPUT__", json.dumps(str(WORK))).replace(
        "__MAIN_TITLE__", json.dumps(TITLE, ensure_ascii=False))
    try:
        # The dedicated browser session and ephemeral origin contain demo data only.
        subprocess.run([*cli, "open", base], check=True, capture_output=True, text=True)
        result = subprocess.run([*cli, "run-code", code], check=True, capture_output=True, text=True)
        (WORK / "capture.log").write_text(result.stdout + result.stderr)
    finally:
        subprocess.run([*cli, "close"], capture_output=True, timeout=30)
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    shots = []
    for name, route in zip(NAMES, ROUTES, strict=True):
        target = destination / (name + ".webp")
        subprocess.run(["cwebp", "-quiet", "-q", "88", "-m", "6", "-metadata", "none",
                        str(WORK / (name + ".png")), "-o", str(target)], check=True)
        shots.append({"file": target.name, "route": route,
                      "bytes": target.stat().st_size, "sha256": sha256(target)})
    manifest = {
        "fixture_date": "2026-11-03", "viewport": {"width": 1440, "height": 1000},
        "theme": "light", "sidebar_width": 280, "toc_pinned": True,
        "playwright_cli": "0.1.23", "webp_quality": 88,
        "asset_version": get_static_asset_version(STATIC),
        "fixture_sha256": sha256(ROOT / "scripts/readme_demo.py"),
        "cases_sha256": sha256(ROOT / "scripts/readme_cases.py"),
        "capture_sha256": sha256(ROOT / "scripts/readme_capture.cjs"),
        "data_source": "public-source reading notes, public-domain books and authored scenarios; no application config, database or provider calls",
        "sources": CASE_SOURCES,
        "javascript_errors": 0, "failed_local_requests": 0, "screenshots": shots,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Captured {len(shots)} screenshots ({sum(s['bytes'] for s in shots)} bytes) to {destination}")


if __name__ == "__main__":
    main()
