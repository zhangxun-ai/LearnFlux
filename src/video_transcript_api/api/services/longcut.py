"""Lightweight integration with a local LongCut development server."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import quote, urlparse, urlunparse

import requests


DEFAULT_BASE_URL = "http://localhost:3000"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class LongCutSettings:
    enabled: bool
    base_url: str
    project_dir: Optional[Path]
    script_name: str
    startup_timeout_seconds: int
    auto_start: bool


@dataclass(frozen=True)
class LongCutStartResult:
    ready: bool
    started: bool
    message: str = ""


def get_longcut_settings(config: Mapping[str, Any] | None) -> LongCutSettings:
    """Build LongCut settings from app config and environment fallbacks."""
    raw = {}
    if isinstance(config, Mapping):
        raw = config.get("longcut") or {}
        if not isinstance(raw, Mapping):
            raw = {}

    base_url = str(
        raw.get("base_url")
        or os.getenv("LONGCUT_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    project_dir_raw = raw.get("project_dir") or os.getenv("LONGCUT_PROJECT_DIR")
    project_dir = Path(str(project_dir_raw)).expanduser() if project_dir_raw else None

    return LongCutSettings(
        enabled=bool(raw.get("enabled", False)),
        base_url=_normalize_base_url(base_url),
        project_dir=project_dir,
        script_name=str(raw.get("script_name") or "server.sh"),
        startup_timeout_seconds=int(
            raw.get("startup_timeout_seconds", DEFAULT_STARTUP_TIMEOUT_SECONDS)
        ),
        auto_start=bool(raw.get("auto_start", True)),
    )


def build_analysis_url(base_url: str, video_id: str) -> str:
    """Return the LongCut analysis URL for a YouTube video id."""
    return f"{base_url.rstrip('/')}/analyze/{quote(video_id, safe='')}"


def build_longcut_action(
    view_data: Mapping[str, Any] | None,
    settings: LongCutSettings,
) -> Optional[dict[str, str]]:
    """Return template action data when the current view can open in LongCut."""
    if not settings.enabled or not view_data:
        return None

    platform = str(view_data.get("platform") or "").lower()
    video_id = str(view_data.get("media_id") or "").strip()
    view_token = str(view_data.get("view_token") or "").strip()

    if platform != "youtube" or not video_id or not view_token:
        return None

    return {
        "url": f"/view/{quote(view_token, safe='')}/longcut",
        "label": "用 LongCut 深度学习",
        "description": "自动检查并启动 LongCut",
        "target_url": build_analysis_url(settings.base_url, video_id),
    }


def ensure_longcut_ready(settings: LongCutSettings) -> LongCutStartResult:
    """Ensure LongCut is reachable, starting the local dev server if needed."""
    if not settings.enabled:
        return LongCutStartResult(False, False, "LongCut integration is disabled")

    if _is_url_ready(settings.base_url):
        return LongCutStartResult(True, False, "LongCut is already running")

    if not settings.auto_start:
        return LongCutStartResult(False, False, "LongCut is not running")

    if not settings.project_dir:
        return LongCutStartResult(False, False, "LongCut project_dir is not configured")

    script_path = settings.project_dir / settings.script_name
    if not script_path.exists():
        return LongCutStartResult(
            False,
            False,
            f"LongCut startup script not found: {script_path}",
        )

    try:
        subprocess.Popen(
            ["bash", str(script_path), "start"],
            cwd=str(settings.project_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return LongCutStartResult(False, False, f"Failed to start LongCut: {exc}")

    deadline = time.monotonic() + max(1, settings.startup_timeout_seconds)
    while time.monotonic() < deadline:
        if _is_url_ready(settings.base_url):
            return LongCutStartResult(True, True, "LongCut started")
        time.sleep(1)

    return LongCutStartResult(
        False,
        True,
        f"LongCut did not become ready within {settings.startup_timeout_seconds}s",
    )


def _normalize_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_BASE_URL
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def _is_url_ready(base_url: str) -> bool:
    try:
        response = requests.get(base_url, timeout=2, allow_redirects=False)
        return response.status_code < 500
    except requests.RequestException:
        return False
