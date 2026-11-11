"""Contracts for the production-only Linear visual system."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"
TEMPLATE_DIR = PROJECT_ROOT / "src" / "web" / "templates"
CSS_DIR = STATIC_DIR / "css"


STATIC_PAGES = {
    "index.html": ("page-home", "home-linear.css"),
    "collections.html": ("page-collections", "product-linear-core.css"),
    "study.html": ("page-study", "product-linear-core.css"),
    "visual-learning.html": ("page-visual-learning", "product-linear-core.css"),
    "focus-studio.html": ("page-focus", "product-linear-core.css"),
    "history.html": ("page-history", "product-linear-system.css"),
    "settings.html": ("page-settings", "product-linear-system.css"),
}


PAGE_ANCHORS = {
    "collections.html": ("drop-action", "collection-history-list", "workspace-title", "/static/js/collections.js"),
    "study.html": ("study-library", "study-player", "tab-transcript", "/static/js/study.js"),
    "visual-learning.html": ("visual-text-panel", "visual-output", "visual-evidence-drawer", "js/visual-learning-workbench.js"),
    "focus-studio.html": ("focus-editor", "mixer-zone", "journal-sidecar", "/static/js/focus-studio.js"),
    "history.html": ("filterBar", "listArea", "paginationBar", "/static/js/app-shell.js"),
    "settings.html": ("groups", "save-btn", "toast", "/static/js/app-shell.js"),
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_static_production_pages_load_one_shared_layer_and_one_adapter():
    for filename, (page_class, adapter) in STATIC_PAGES.items():
        html = _source(STATIC_DIR / filename)
        assert "product-linear" in html, filename
        assert page_class in html, filename
        assert html.count("product-linear.css") == 1, filename
        assert html.count(adapter) == 1, filename
        assert html.index("app-shell.css") < html.index("product-linear.css"), filename
        if adapter != "home-linear.css":
            assert html.index("product-linear.css") < html.index(adapter), filename


def test_template_pages_load_only_their_assigned_adapter():
    base = _source(TEMPLATE_DIR / "base.html")
    post = _source(TEMPLATE_DIR / "post_insight.html")
    flywheel = _source(TEMPLATE_DIR / "flywheel.html")

    assert base.count("product-linear.css") == 1
    assert "{% block body_class %}page-result{% endblock %}" in base
    assert "{% block product_linear_adapter %}" in base
    assert base.count("product-linear-system.css") == 1

    assert "{% block body_class %}page-post{% endblock %}" in post
    assert post.count("product-linear-insights.css") == 1
    assert "product-linear-system.css" not in post

    assert "page-flywheel" in flywheel
    assert flywheel.count("product-linear.css") == 1
    assert flywheel.count("product-linear-insights.css") == 1
    assert "product-linear-system.css" not in flywheel


def test_production_visual_layer_preserves_primary_dom_and_script_contracts():
    for filename, anchors in PAGE_ANCHORS.items():
        html = _source(STATIC_DIR / filename)
        for anchor in anchors:
            assert anchor in html, f"{filename}: missing {anchor}"

    post = _source(TEMPLATE_DIR / "post_insight.html")
    for anchor in ("post-url", "analyze-btn", "result-section", "sections-container"):
        assert f'id="{anchor}"' in post

    flywheel = _source(TEMPLATE_DIR / "flywheel.html")
    for anchor in ("v-analyze", "result", "v-history", "v-opportunities", "v-settings"):
        assert f'id="{anchor}"' in flywheel

    environment = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    transcript = environment.get_template("transcript.html").render(view_token="test-result")
    processing = _source(TEMPLATE_DIR / "processing.html")
    error = _source(TEMPLATE_DIR / "error.html")
    cleaned = _source(TEMPLATE_DIR / "cleaned.html")
    assert 'id="exportMainBtn"' in transcript
    assert 'aria-haspopup="dialog"' in transcript
    assert 'role="progressbar"' in processing
    assert 'role="alert"' in error
    assert "/static/focus-studio.html" in cleaned


def test_visual_css_is_scoped_and_includes_accessibility_states():
    shared = _source(CSS_DIR / "product-linear.css")
    assert "body.product-linear" in shared
    assert '[data-theme="dark"] body.product-linear' in shared
    assert ":focus-visible" in shared
    assert "prefers-reduced-motion: reduce" in shared

    for filename in (
        "product-linear.css",
        "product-linear-core.css",
        "product-linear-system.css",
    ):
        css = _source(CSS_DIR / filename)
        assert "!important" not in css, filename
        assert not re.search(r"(^|[},]\s*)(:root|html|body(?!\.product-linear))\s*[{,]", css, re.MULTILINE), filename

    allowed_prefixes = {
        "product-linear-core.css": "body.product-linear.page-",
        "product-linear-insights.css": "body.product-linear.page-",
        "product-linear-system.css": "body.product-linear.page-",
    }
    for filename, prefix in allowed_prefixes.items():
        css = re.sub(r"/\*.*?\*/", "", _source(CSS_DIR / filename), flags=re.DOTALL)
        selectors = re.findall(r"([^{}]+)\{", css)
        for selector_group in selectors:
            for selector in selector_group.split(","):
                selector = selector.strip()
                if selector and not selector.startswith("@"):
                    assert selector.startswith(prefix), f"{filename}: unscoped selector {selector}"


def test_versioned_routes_include_the_new_visual_assets(tmp_path):
    from video_transcript_api.api.assets import get_static_asset_version

    css = tmp_path / "css"
    css.mkdir()
    version = get_static_asset_version(tmp_path)
    for filename in (
        "product-linear.css", "product-linear-core.css",
        "product-linear-insights.css", "product-linear-system.css",
        "workbench-wildwood.css",
    ):
        (css / filename).write_text("body { color: green; }", encoding="utf-8")
        changed = get_static_asset_version(tmp_path)
        assert changed != version, filename
        version = changed


def test_service_worker_refreshes_and_precaches_the_visual_system():
    service_worker = _source(STATIC_DIR / "service-worker.js")

    cache_name = re.search(r"const CACHE_NAME = '(learnflux-pwa-(\d{8})[^']*)';", service_worker)
    assert cache_name, "Service worker must declare a versioned cache"
    assert cache_name.group(2) >= "20261030", "New image bundles require a fresh cache version"
    assert "/static/js/image-diagrams.js" in service_worker
    assert "/static/css/image-diagrams.css" in service_worker
    assert "/static/js/auth-session.js" in service_worker
    assert "/static/js/time.js" in service_worker
    assert "/static/js/ui-features.js" in service_worker
    for filename in (
        "product-linear.css",
        "product-linear-core.css",
        "product-linear-system.css",
    ):
        assert f"/static/css/{filename}" in service_worker


def test_visual_learning_skips_removed_optional_toolbar_actions():
    html = _source(STATIC_DIR / "visual-learning.html")
    javascript = _source(STATIC_DIR / "js" / "visual-learning-workbench.js")

    assert 'id="visual-export"' not in html
    assert 'id="visual-print-page"' not in html
    assert 'js/visual-learning-workbench.js?v=__ASSET_VERSION__' in html
    assert "els.exportButton?.addEventListener" in javascript
    assert "els.printButton?.addEventListener" in javascript


def test_result_toc_declares_container_before_pin_state_branches(tmp_path):
    javascript = _source(STATIC_DIR / "js" / "floating-toc.js")
    template = _source(TEMPLATE_DIR / "transcript.html")
    context = _source(PROJECT_ROOT / "src/video_transcript_api/api/context.py")
    init_source = javascript[javascript.index("function init()") :]

    declaration = "const container = document.getElementById('floating-toc');"
    assert init_source.count(declaration) == 1
    assert init_source.index(declaration) < init_source.index("if (isPinned && !isMobile)")
    assert '/static/js/floating-toc.js?v={{ asset_ver }}' in template
    assert "get_static_asset_version(get_static_dir())" in context
    from video_transcript_api.api.assets import get_static_asset_version
    script = tmp_path / "js" / "floating-toc.js"
    script.parent.mkdir()
    script.write_text("const pinned = false;", encoding="utf-8")
    before = get_static_asset_version(tmp_path)
    script.write_text("const pinned = true;", encoding="utf-8")
    assert get_static_asset_version(tmp_path) != before
