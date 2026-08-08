from pathlib import Path
import hashlib
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _css_rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert match is not None, f"Missing CSS rule for {selector}"
    return match.group(1)


def test_focus_studio_contains_lightweight_journal_ui():
    html = (PROJECT_ROOT / "src/web/static/focus-studio.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/focus-studio.css").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "src/web/static/js/focus-journal.js").read_text(encoding="utf-8")
    sw = (PROJECT_ROOT / "src/web/static/service-worker.js").read_text(encoding="utf-8")

    assert 'id="journal-type-select"' in html
    assert 'value="weekly_plan"' in html
    assert 'value="monthly_review"' in html
    assert 'class="journal-shell"' in html
    assert 'id="journal-sidecar"' in html
    assert 'data-journal-open="history"' in html
    assert 'id="journal-sidecar-close"' in html
    assert 'id="journal-history-list"' in html
    assert 'id="journal-review-question"' in html
    assert "/static/js/focus-journal.js" in html

    assert ".journal-dock" in css
    assert ".journal-sidecar" in css
    assert "[data-journal-sidecar] .journal-dock" in css
    assert "[data-journal-sidecar] .focus-deck" in css
    assert ".journal-review-question" in css
    css_version = hashlib.sha256(css.encode("utf-8")).hexdigest()[:12]
    assert f'/static/css/focus-studio.css?v={css_version}' in html

    assert "/api/journal/entries" in js
    assert "/api/journal/reviews" in js
    assert "journalSidecar" in js
    assert "togglePanel" in js
    assert "mouseleave" in js
    assert "journal-sidecar-close" in js
    assert "vta_bearer_token" in js
    assert "NO_TOKEN" in js

    assert "/static/js/focus-journal.js" in sw


def test_focus_editor_has_a_subtle_scrollbar_and_reserved_ui_space():
    css = (PROJECT_ROOT / "src/web/static/css/focus-studio.css").read_text(encoding="utf-8")

    editor_rule = _css_rule(css, ".focus-editor")
    assert "inset: 5.5rem 0 4.75rem;" in editor_rule
    assert "height: auto;" in editor_rule
    assert "overflow-y: auto;" in editor_rule
    assert "scrollbar-width: thin;" in editor_rule
    assert "scrollbar-gutter: stable;" in editor_rule
    assert re.search(
        r"body\.product-linear\.page-focus \.focus-editor:focus,\s*"
        r"body\.product-linear\.page-focus \.focus-editor:focus-visible\s*"
        r"\{[^}]*outline: 0;[^}]*border-color: transparent;[^}]*box-shadow: none;",
        css,
    )

    webkit_scrollbar_rule = _css_rule(css, ".focus-editor::-webkit-scrollbar")
    assert "width: 0.3125rem;" in webkit_scrollbar_rule
    webkit_thumb_rule = _css_rule(css, ".focus-editor::-webkit-scrollbar-thumb")
    assert "background: rgba(255, 255, 255, 0.20);" in webkit_thumb_rule


def test_focus_mixer_is_compact_and_does_not_block_editor_clicks():
    css = (PROJECT_ROOT / "src/web/static/css/focus-studio.css").read_text(encoding="utf-8")

    mixer_zone_rule = _css_rule(css, ".mixer-zone")
    assert "width: min(28rem, calc(100vw - 2rem));" in mixer_zone_rule
    assert "pointer-events: none;" in mixer_zone_rule

    mixer_panel_rule = _css_rule(css, ".mixer-panel")
    assert "min-width: min(28rem, calc(100vw - 2rem));" in mixer_panel_rule
    assert "padding: 0.75rem 1rem;" in mixer_panel_rule

    assert re.search(r"\.mixer-orb\s*\{[^}]*pointer-events: auto;", css)
    assert re.search(
        r"body\.product-linear\.page-focus \.mixer-orb,\s*"
        r"body\.product-linear\.page-focus \.sound-current\s*\{[^}]*min-height: 0;",
        css,
    )
    mixer_range_rule = _css_rule(css, '.mixer-panel input[type="range"]')
    assert "min-height: 0;" in mixer_range_rule
    assert "height: 0.75rem;" in mixer_range_rule
    assert ".mixer-panel input[type=\"range\"]::-webkit-slider-thumb" in css


def test_focus_studio_hides_secondary_draft_actions():
    css = (PROJECT_ROOT / "src/web/static/css/focus-studio.css").read_text(encoding="utf-8")

    assert re.search(
        r"body\.product-linear\.page-focus \.deck-actions\s*\{[^}]*display: none;",
        css,
    )
