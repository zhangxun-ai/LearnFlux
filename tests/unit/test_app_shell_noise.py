"""Regression tests for the content-first application shell."""

import re
from pathlib import Path

from video_transcript_api.api.routes.views import _HOME_HTML


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SHELL_SOURCES = (
    PROJECT_ROOT / "src/web/static/index.html",
    PROJECT_ROOT / "src/web/static/collections.html",
    PROJECT_ROOT / "src/web/static/study.html",
    PROJECT_ROOT / "src/web/static/focus-studio.html",
    PROJECT_ROOT / "src/web/static/visual-learning.html",
    PROJECT_ROOT / "src/web/static/trend-radar.html",
    PROJECT_ROOT / "src/web/static/history.html",
    PROJECT_ROOT / "src/web/static/settings.html",
    PROJECT_ROOT / "src/web/templates/base.html",
    PROJECT_ROOT / "src/web/templates/flywheel.html",
)


def _topbar(html: str) -> str:
    match = re.search(
        r'<header class="topbar"[^>]*>.*?</header>',
        html,
        flags=re.DOTALL,
    )
    assert match, "production shell must keep a mobile navigation anchor"
    return match.group(0)


def test_production_shells_remove_static_status_and_duplicate_actions():
    sources = [path.read_text(encoding="utf-8") for path in SHELL_SOURCES]
    sources.append(_HOME_HTML)

    for html in sources:
        topbar = _topbar(html)
        assert "topbar-page-title" in topbar
        assert "workspace-status" not in topbar
        assert "topbar-button" not in topbar
        assert "工作区就绪" not in topbar


def test_production_shells_have_one_content_heading():
    sources = [path.read_text(encoding="utf-8") for path in SHELL_SOURCES]
    sources.append(_HOME_HTML)

    for html in sources:
        assert len(re.findall(r"<h1(?:\s|>)", html)) == 1


def test_shared_shell_uses_consistent_desktop_and_compact_mobile_bars():
    css = (
        PROJECT_ROOT / "src/web/static/css/app-shell.css"
    ).read_text(encoding="utf-8")

    desktop, mobile = css.split("@media (max-width: 900px)", maxsplit=1)
    assert "--shell-topbar: 64px" in desktop
    assert re.search(r"\.topbar\s*\{[^}]*display:\s*flex", desktop, re.DOTALL)
    assert "--shell-topbar: 56px" in mobile
    assert re.search(r"\.topbar\s*\{[^}]*display:\s*flex", mobile, re.DOTALL)
    assert re.search(r"\.sr-only\s*\{", css)


def test_focus_stage_can_shrink_to_the_remaining_viewport():
    css = (
        PROJECT_ROOT / "src/web/static/css/focus-studio.css"
    ).read_text(encoding="utf-8")
    rule = re.search(
        r"\.focus-body\.has-app-shell \.focus-stage\s*\{([^}]*)\}",
        css,
        flags=re.DOTALL,
    )

    assert rule
    assert "height: calc(100vh - var(--shell-topbar))" in rule.group(1)
    assert "min-height: 0" in rule.group(1)
