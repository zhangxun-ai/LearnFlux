import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "src/web/static"


class _ReadingElementParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.elements[element_id] = (tag, attributes)


def _reading_elements(html):
    parser = _ReadingElementParser()
    parser.feed(html)
    return parser.elements


def _css_rule_declarations(css, selector):
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]+)\}}", css)
    assert match, f"missing CSS rule for {selector}"
    return match.group("body")


def test_reading_page_has_real_library_and_reader_layers():
    html = (STATIC_ROOT / "reading.html").read_text(encoding="utf-8")
    elements = _reading_elements(html)

    assert 'id="reading-library"' in html
    assert 'id="reading-import"' in html
    assert 'id="reading-reader"' in html
    assert 'id="reading-import-button"' in html
    assert 'id="reading-empty-state"' in html
    reader_tag, reader_attributes = elements["reading-reader"]
    assert reader_tag == "section"
    assert "hidden" in reader_attributes
    assert "css/editorial.css" in html
    assert "css/app-shell.css" in html
    assert "css/product-linear.css" in html
    assert "css/product-linear-core.css" in html
    assert "css/reading.css" in html
    assert "js/reading.js" in html
    assert "reading.css?v=__ASSET_VERSION__" in html
    assert "reading.js?v=__ASSET_VERSION__" in html
    assert "<iframe" not in html
    assert "52042" not in html


def test_reading_library_preserves_the_approved_prototype_structure():
    html = (STATIC_ROOT / "reading.html").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "css/reading.css").read_text(encoding="utf-8")

    assert "FLOW SPACE · READING" in html
    assert 'id="reading-search"' in html
    assert 'id="reading-continue-card"' in html
    assert 'id="reading-continue-title"' in html
    assert 'id="reading-continue-progress"' in html
    assert 'id="reading-sort"' in html
    assert "reading-library-actions" in html
    assert "reading-section-head" in html
    assert "grid-template-columns: repeat(5" in css
    assert ".reading-empty-state[hidden]" in css


def test_reading_library_main_area_owns_viewport_scrolling():
    css = (STATIC_ROOT / "css/reading.css").read_text(encoding="utf-8")
    declarations = _css_rule_declarations(
        css,
        ".page-reading.product-linear .main-area",
    )

    assert "height: 100vh;" in declarations
    assert "height: 100dvh;" in declarations
    assert "min-height: 0;" in declarations
    assert "overflow-y: auto;" in declarations


def test_reader_preserves_the_approved_two_page_prototype_structure():
    html = (STATIC_ROOT / "reading.html").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "css/reading.css").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")
    elements = _reading_elements(html)

    sound_tag, sound_attributes = elements["reading-sound-shortcut"]
    assert sound_tag == "button"
    assert sound_attributes["data-reading-panel"] == "sound"
    assert sound_attributes["aria-pressed"] == "false"
    assert 'id="reading-reprocess"' not in html
    assert 'id="reading-mode-toggle"' not in html
    assert 'data-reading-bookmark' not in html
    assert '点击两侧或使用 ← → 翻页' not in html
    assert 'aria-label="关闭目录"' in html
    assert 'aria-label="关闭搜索"' in html
    assert 'aria-label="关闭阅读设置"' in html
    assert 'aria-label="关闭背景音"' in html
    assert 'id="reading-reader-pages"' in html
    assert 'id="reading-flow-content"' in html
    assert 'id="reading-panel-search"' in html
    assert 'data-reading-size="smaller"' in html
    assert 'data-reading-size="larger"' in html
    for theme in ["original", "quiet", "focus", "dark", "paper", "gray"]:
        assert f'data-reading-theme="{theme}"' in html
    assert 'data-reading-layout="double"' in html
    assert 'data-reading-layout="single"' in html
    assert "column-fill: auto" in css
    assert "column-width: var(--reader-page-width)" in css
    assert "overflow: hidden" in css
    assert "margin-left: var(--reader-page-gutter)" in css
    assert "margin-right: var(--reader-page-gutter)" in css
    assert "column-gap: calc(var(--reader-page-gutter) + var(--reader-page-gutter))" in css
    assert "splitChapterAcrossPages" not in js
    assert "renderDocumentFlow" in js
    assert "goToSpread" in js
    assert "elements.pages.scrollLeft = targetLeft" in js
    assert "pageWidth - (2 * pageGutter)" in js
    assert "getComputedStyle(elements.flow).marginLeft" in js
    assert "scroll-behavior: smooth" not in css
    assert "elements.soundShortcut" in js
    assert "elements.soundShortcut.setAttribute('aria-pressed', String(isPlaying))" in js
    assert "toggleBookmark" not in js
    assert "applyMode" not in js
    assert "/reprocess" not in js


def test_reader_toolbar_styles_match_the_simplified_controls():
    css = (STATIC_ROOT / "css/reading.css").read_text(encoding="utf-8")
    page_indicator = _css_rule_declarations(css, ".reading-spread-number")

    assert ".reading-mode-toggle" not in css
    assert '[data-reading-mode="original"]' not in css
    assert '#reading-sound-shortcut[aria-pressed="true"]' in css
    assert "opacity: 1;" in page_indicator
    assert ".reading-page-spread:hover .reading-spread-number" not in css


def test_reader_toolbar_uses_an_explicit_aa_settings_control():
    html = (STATIC_ROOT / "reading.html").read_text(encoding="utf-8")
    elements = _reading_elements(html)

    settings_tag, settings_attributes = elements["reading-settings-shortcut"]
    assert settings_tag == "button"
    assert settings_attributes["data-reading-panel"] == "settings"
    assert 'class="reading-settings-symbol"' in html
    assert ">Aa</span>" in html


def test_reader_toolbar_panels_open_on_hover_and_close_after_mouse_leaves():
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")

    assert "const PANEL_CLOSE_DELAY_MS = 300;" in js
    assert "function schedulePanelClose()" in js
    assert "button.addEventListener('pointerenter', (event) => {" in js
    assert "button.addEventListener('pointerleave', (event) => {" in js
    assert "panel.addEventListener('pointerenter', (event) => {" in js
    assert "panel.addEventListener('pointerleave', (event) => {" in js
    assert "if (event.pointerType === 'mouse') return;" in js


def test_pdf_reflow_helper_merges_visual_lines_for_existing_documents():
    helper = STATIC_ROOT / "js/reading-flow.js"
    node_test = r"""
const assert = require('node:assert/strict');
const flow = require(process.argv[1]);
const blocks = flow.pdfTextToBlocks([
    '第一段尚未结束，',
    '这一行只是视觉换行，',
    '这里才真正结束。',
    '8',
    '•',
    '1. 第一项跨行',
    '继续完成。',
    '2. 第二项。',
].join('\n'));
assert.deepEqual(blocks, [
    {type: 'p', text: '第一段尚未结束，这一行只是视觉换行，这里才真正结束。'},
    {type: 'ol', items: ['第一项跨行继续完成。', '第二项。']},
]);
assert.deepEqual(
    flow.pdfTextToBlocks('报告标题\n执行摘要\n正文结束。', {promoteLeadingHeadings: true}),
    [
        {type: 'h1', text: '报告标题'},
        {type: 'h2', text: '执行摘要'},
        {type: 'p', text: '正文结束。'},
    ],
);
"""
    result = subprocess.run(
        ["node", "-e", node_test, str(helper)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_pdf_reader_renders_the_sanitized_html_contract():
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")

    assert "chapter.sanitized_html" in js
    assert "pdfTextToBlocks" not in js


def test_pdf_reader_keeps_reprocess_out_of_the_reader_toolbar():
    html = (STATIC_ROOT / "reading.html").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")

    assert 'id="reading-reprocess"' not in html
    assert "/reprocess" not in js


def test_reading_import_uses_native_modal_markup_and_focus_contract():
    html = (STATIC_ROOT / "reading.html").read_text(encoding="utf-8")
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")
    elements = _reading_elements(html)

    import_tag, import_attributes = elements["reading-import"]
    assert import_tag == "dialog"
    assert "hidden" not in import_attributes
    assert "aria-modal" not in import_attributes
    assert "reading-import-backdrop" not in html
    assert "showModal()" in js
    assert ".close()" in js
    assert "event.currentTarget" in js
    assert "addEventListener('cancel'" in js
    assert "addEventListener('close'" in js


def test_reading_script_keeps_the_optional_deep_link_document_id():
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")

    assert "window.location.pathname" in js
    assert "documentId" in js
    assert "decodeURIComponent" in js


def test_reading_decrypts_the_shared_workbench_token():
    js = (STATIC_ROOT / "js/reading.js").read_text(encoding="utf-8")

    assert "vta_encrypt_key_2024" in js
    assert "decryptToken(localStorage.getItem(TOKEN_KEY))" in js


def test_app_shell_reconciles_the_canonical_navigation():
    js = (STATIC_ROOT / "js/app-shell.js").read_text(encoding="utf-8")
    navigation_source = (
        PROJECT_ROOT / "src/web/product-navigation.json"
    ).read_text(encoding="utf-8")
    navigation = json.loads(navigation_source)

    assert "const NAV_GROUPS =" not in js
    assert "replaceChildren" not in js
    expected_labels = [
        "核心工具",
        "单篇深度学习",
        "系列深度学习",
        "图解生成",
        "边播边学",
        "复盘",
        "心流空间",
        "心流阅读",
        "心流写作",
    ]
    labels = []
    for group in navigation["groups"]:
        labels.append(group["label"])
        labels.extend(navigation["items"][item_id]["label"] for item_id in group["items"])
    assert labels[:len(expected_labels)] == expected_labels
    assert navigation["items"]["reading"]["href"] == "/reading"
    assert navigation["items"]["focus_studio"]["href"] == "/static/focus-studio.html"
    assert "reconcileNavigation" in js


def test_app_shell_reconcile_activates_canonical_routes():
    node_test = r"""
const assert = require('node:assert/strict');
global.document = { body: null };
const shell = require(process.argv[1]);

function link(href, aliases = '') {
    const classes = new Set(['nav-item']);
    return {
        href,
        dataset: {aliases},
        attributes: {},
        classList: {
            toggle: (name, active) => active ? classes.add(name) : classes.delete(name),
            contains: (name) => classes.has(name),
        },
        getAttribute: (name) => name === 'href' ? href : null,
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
    };
}

function activeItem(pathname) {
    const links = [
        link('/add_task_by_web', '/,/view'),
        link('/collections'),
        link('/visual-learning'),
        link('/study'),
        link('/reading'),
        link('/static/focus-studio.html'),
    ];
    const sidebar = {querySelectorAll: () => links};
    shell.reconcileNavigation(sidebar, pathname);
    return links.find((item) => item.classList.contains('is-active'));
}

for (const [pathname, expectedHref] of [
    ['/', '/add_task_by_web'],
    ['/add_task_by_web', '/add_task_by_web'],
    ['/view/token-123', '/add_task_by_web'],
    ['/reading', '/reading'],
    ['/reading/document-123', '/reading'],
]) {
    const active = activeItem(pathname);
    assert.ok(active, `missing active item for ${pathname}`);
    assert.equal(active.href, expectedHref);
    assert.equal(active.attributes['aria-current'], 'page');
}
"""
    result = subprocess.run(
        ["node", "-e", node_test, str(STATIC_ROOT / "js/app-shell.js")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
