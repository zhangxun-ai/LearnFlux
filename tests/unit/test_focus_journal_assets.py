from pathlib import Path
import re
import subprocess


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
    page_version = re.search(
        r'/static/css/focus-studio\.css\?v=([0-9a-f]{12})',
        html,
    )
    assert page_version is not None
    assert f'/static/js/focus-journal.js?v={page_version.group(1)}' in html

    assert "/api/journal/entries" in js
    assert "/api/journal/reviews" in js
    assert "journalSidecar" in js
    assert "togglePanel" in js
    assert "mouseleave" in js
    assert "journal-sidecar-close" in js
    assert "window.LearnFluxAuth.getTokenPlaceholder()" in js
    assert "vta_bearer_token" not in js
    assert "NO_TOKEN" in js

    assert "/static/js/auth-session.js" in html
    assert "/static/js/auth-session.js" in sw
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


def test_workbench_theme_preserves_focus_scenes_and_only_recolors_the_writing_surface():
    css = (PROJECT_ROOT / "src/web/static/css/workbench-wildwood.css").read_text(encoding="utf-8")
    focus_rules = css[css.index("/* Focus writing:"):css.index("/* Study result detail:")]

    assert ".focus-canvas" not in focus_rules
    assert ".focus-vignette" not in focus_rules
    assert "filter: brightness" not in focus_rules
    assert "opacity: 0.22" not in focus_rules
    assert "background: rgba(255, 255, 255, 0.88);" in focus_rules


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


def test_focus_writing_removes_draft_actions_but_keeps_automatic_saving():
    html = (PROJECT_ROOT / "src/web/static/focus-studio.html").read_text(encoding="utf-8")
    assert 'id="focus-clear"' not in html
    assert 'id="focus-export"' not in html
    assert 'class="sr-only" id="save-status" aria-live="polite"' in html
    behavior = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('    function persistDraft() {');
const end = source.indexOf('    // Edge proximity', start);
const saved = new Map();
const context = {
    editor: {value: 'Demo draft'},
    STORAGE: {text: 'draft', savedAt: 'savedAt'},
    localStorage: {setItem(key, value) {saved.set(key, value);}},
    updateSaveStatus() {context.updated = true;},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
context.persistDraft();
assert.equal(saved.get('draft'), 'Demo draft');
assert.ok(Number.isFinite(Date.parse(saved.get('savedAt'))));
assert.equal(context.updated, true);
"""
    result = subprocess.run(
        ["node", "-e", behavior, str(PROJECT_ROOT / "src/web/static/js/focus-studio.js")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_focus_snow_animation_has_no_pointer_input():
    js = (PROJECT_ROOT / "src/web/static/js/focus-studio.js").read_text(encoding="utf-8")
    snow_shader = re.search(r"const SNOW_FRAGMENT = `(.+?)`;", js, re.DOTALL)
    assert snow_shader is not None
    assert "uniform float uTime;" in snow_shader.group(1)
    assert "SPEED * uTime" in snow_shader.group(1)
    assert "uMouse" not in js
    assert "state.mouseX" not in js
    assert "state.mouseY" not in js
    # Pointer proximity must still reveal the writing controls.
    assert "stage.addEventListener('pointermove', revealControls" in js


def test_focus_font_scale_migrates_once_and_keeps_the_selected_size():
    behavior = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('    const SIZE_SCALE =');
const end = source.indexOf('    const state =', start);
const saved = new Map();
const context = {
    STORAGE: {size: 'size', sizeScale: 'scale'},
    localStorage: {getItem(key) {return saved.get(key) || null;}},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
assert.equal(context.initialSize(), 'medium');
saved.set('size', 'large');
assert.equal(context.initialSize(), 'medium');
saved.set('scale', '14-16-18-v1');
for (const size of ['small', 'medium', 'large']) {
    saved.set('size', size);
    assert.equal(context.initialSize(), size);
}
saved.set('size', 'invalid');
assert.equal(context.initialSize(), 'medium');
"""
    result = subprocess.run(
        ["node", "-e", behavior, str(PROJECT_ROOT / "src/web/static/js/focus-studio.js")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_focus_writing_alignment_is_shared_across_backgrounds():
    css = (PROJECT_ROOT / "src/web/static/css/workbench-wildwood.css").read_text(encoding="utf-8")
    # Writing gutters follow the available scene width, shared by both modes.
    assert "container: focus-writing / inline-size;" in css
    assert "inset: 68px clamp(24px, 6cqw, 80px) 24px;" in css
    # Scene-specific background treatments must not move the date or editor.
    assert not re.search(
        r"[^{}]*\[data-mode=[^{}]*\.(?:deck-wrap|journal-meta|focus-editor)"
        r"[^{}]*\{[^}]*\b(?:inset|left|right|top|bottom|margin|padding|width|height|transform)\s*:",
        css,
    )


def test_focus_canvas_resizes_with_its_scene_without_a_window_resize():
    behavior = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const resizeStart = source.indexOf('        function resize() {');
const resizeEnd = source.indexOf('        function render(now)', resizeStart);
const observerStart = source.indexOf("        window.addEventListener('resize', resize);");
const observerEnd = source.indexOf("        document.addEventListener('visibilitychange'", observerStart);
const stage = {clientWidth: 1120, clientHeight: 900};
const viewport = [];
let observed, observerCallback;
const context = {
    gl: {viewport(...values) {viewport.push(values);}},
    stage, canvas: {style: {}}, dpr: 1,
    window: {innerWidth: 1440, innerHeight: 1000, devicePixelRatio: 1, addEventListener() {}},
    ResizeObserver: class {
        constructor(callback) {observerCallback = callback;}
        observe(element) {observed = element;}
    },
};
vm.createContext(context);
vm.runInContext(source.slice(resizeStart, resizeEnd), context);
vm.runInContext(source.slice(observerStart, observerEnd), context);
assert.equal(observed, stage);
context.resize();
assert.deepEqual(viewport.at(-1), [0, 0, 1120, 900]);
stage.clientWidth = 820;
observerCallback();
assert.deepEqual(viewport.at(-1), [0, 0, 820, 900]);
assert.equal(context.canvas.width, 820);
assert.equal(context.canvas.height, 900);
assert.equal(context.canvas.style.width, undefined);
assert.equal(context.canvas.style.height, undefined);
"""
    result = subprocess.run(
        ["node", "-e", behavior, str(PROJECT_ROOT / "src/web/static/js/focus-studio.js")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
