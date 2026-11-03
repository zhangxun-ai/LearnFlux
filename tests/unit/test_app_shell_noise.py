"""Regression tests for the content-first application shell."""

import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from video_transcript_api.api.routes.views import _HOME_HTML


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SHELL_SOURCES = (
    PROJECT_ROOT / "src/web/static/index.html",
    PROJECT_ROOT / "src/web/static/collections.html",
    PROJECT_ROOT / "src/web/static/study.html",
    PROJECT_ROOT / "src/web/static/focus-studio.html",
    PROJECT_ROOT / "src/web/static/visual-learning.html",
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

    for html in sources:
        topbar = _topbar(html)
        assert "topbar-page-title" in topbar
        assert "workspace-status" not in topbar
        assert "topbar-button" not in topbar
        assert "工作区就绪" not in topbar


class _VisibleHeadingParser(HTMLParser):
    """Count document headings outside hidden panels, including ancestors."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.visible_h1 = 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        hidden = (self.stack and self.stack[-1][1]) or "hidden" in attrs
        if tag == "h1" and not hidden:
            self.visible_h1 += 1
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, bool(hidden)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def test_production_shells_have_one_visible_content_heading():
    sources = [path.read_text(encoding="utf-8") for path in SHELL_SOURCES]
    sources.append(_HOME_HTML)
    for html in sources:
        parser = _VisibleHeadingParser()
        parser.feed(html)
        assert parser.visible_h1 == 1


def test_collection_views_have_mutually_exclusive_page_headings():
    html = (PROJECT_ROOT / "src/web/static/collections.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "src/web/static/js/collections.js").read_text(encoding="utf-8")
    for mode, section_id in (("catalog", "collection-catalog-page"), ("create", "collection-import-panel"), ("topic", "collection-workspace")):
        panel = re.search(rf'<section[^>]*id="{section_id}"[^>]*>.*?</section>', html, re.DOTALL)
        assert panel, section_id
        assert len(re.findall(r"<h1(?:\s|>)", panel.group(0))) == 1
    assert "els.catalogPage.hidden = pageMode !== 'catalog'" in script
    assert "els.createPage.hidden = pageMode !== 'create'" in script
    assert "els.collectionWorkspace.hidden = pageMode !== 'topic'" in script

    behavior = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('    function applyCollectionPageMode() {');
const end = source.indexOf('    function setCollectionPageMode(', start);
const panels = {catalogPage: {}, createPage: {}, collectionWorkspace: {}};
const context = {els: panels, document: {body: {classList: {toggle() {}}}}};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
for (const mode of ['catalog', 'create', 'topic']) {
    context.pageMode = mode;
    context.applyCollectionPageMode();
    assert.equal(Object.values(panels).filter(panel => !panel.hidden).length, 1);
    assert.equal(panels.catalogPage.hidden, mode !== 'catalog');
    assert.equal(panels.createPage.hidden, mode !== 'create');
    assert.equal(panels.collectionWorkspace.hidden, mode !== 'topic');
}
"""
    result = subprocess.run(
        ["node", "-e", behavior, str(PROJECT_ROOT / "src/web/static/js/collections.js")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_shell_uses_consistent_desktop_and_compact_mobile_bars():
    css = (
        PROJECT_ROOT / "src/web/static/css/app-shell.css"
    ).read_text(encoding="utf-8")

    desktop, mobile = css.split("@media (max-width: 900px)", maxsplit=1)
    # Desktop hides the topbar page-title echo (sidebar already shows location).
    assert "--shell-topbar: 0px" in desktop
    assert re.search(r"\.topbar\s*\{[^}]*display:\s*none", desktop, re.DOTALL)
    # Mobile keeps a compact topbar as the navigation/location anchor.
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
