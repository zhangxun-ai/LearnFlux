"""Contracts for the unified LearnFlux product shell."""

import json
import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "src" / "web" / "static"
FEATURE_CONFIG = STATIC_ROOT / "js" / "ui-features.js"
APP_SHELL = STATIC_ROOT / "js" / "app-shell.js"
APP_SHELL_CSS = STATIC_ROOT / "css" / "app-shell.css"
PRODUCT_CSS = STATIC_ROOT / "css" / "product-linear.css"
TEMPLATE_ROOT = PROJECT_ROOT / "src" / "web" / "templates"
NAVIGATION_DATA = PROJECT_ROOT / "src" / "web" / "product-navigation.json"
SYNC_NAVIGATION = PROJECT_ROOT / "scripts" / "sync_product_navigation.py"

STATIC_SHELL_CANDIDATES = (
    "index.html",
    "collections.html",
    "study.html",
    "visual-learning.html",
    "focus-studio.html",
    "reading.html",
    "review.html",
    "trend-radar.html",
    "history.html",
    "settings.html",
)
STATIC_SHELLS = tuple(
    filename for filename in STATIC_SHELL_CANDIDATES
    if (STATIC_ROOT / filename).exists()
)


class TestFeatureConfig:
    def test_feature_config_is_the_complete_boolean_ui_source(self):
        node_test = r"""
const assert = require('node:assert/strict');
const features = require(process.argv[1]);
assert.deepEqual(Object.keys(features), [
  'collections',
  'visual_learning',
  'study_player',
  'reading',
  'focus_studio',
  'post_insight',
  'trend_radar',
  'flywheel',
  'history',
]);
assert.ok(Object.isFrozen(features));
for (const value of Object.values(features)) assert.equal(typeof value, 'boolean');
assert.equal(features.trend_radar, false);
const optionallyDisabled = new Set(['reading', 'trend_radar']);
for (const [key, value] of Object.entries(features)) {
  if (!optionallyDisabled.has(key)) assert.equal(value, true, key);
}
"""
        result = subprocess.run(
            ["node", "-e", node_test, str(FEATURE_CONFIG)],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr

    def test_feature_config_has_no_backend_or_storage_coupling(self):
        source = FEATURE_CONFIG.read_text(encoding="utf-8")

        for forbidden in (
            "fetch(",
            "XMLHttpRequest",
            "localStorage",
            "sessionStorage",
            "/api/",
        ):
            assert forbidden not in source

    def test_feature_ids_are_safe_data_attribute_values(self):
        node_script = (
            "const f=require(process.argv[1]);"
            "process.stdout.write(JSON.stringify(Object.keys(f)));"
        )
        result = subprocess.run(
            ["node", "-e", node_script, str(FEATURE_CONFIG)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        for feature_id in json.loads(result.stdout):
            assert feature_id.replace("_", "").isalnum()
            assert feature_id == feature_id.lower()


class TestShellBehaviorSource:
    def test_shell_exports_strict_feature_and_state_helpers(self):
        node_test = r"""
const assert = require('node:assert/strict');
global.document = { body: null };
const shell = require(process.argv[1]);

assert.equal(shell.isFeatureEnabled({reading: true}, 'reading'), true);
assert.equal(shell.isFeatureEnabled({reading: 1}, 'reading'), false);
assert.equal(shell.isFeatureEnabled({}, 'reading'), false);
assert.equal(shell.isFeatureEnabled(null, 'reading'), false);

assert.deepEqual(shell.normalizeShellState('expanded'), {mode: 'expanded', groups: {}});
assert.deepEqual(shell.normalizeShellState('collapsed'), {mode: 'rail', groups: {}});
assert.deepEqual(
  shell.normalizeShellState({mode: 'rail', groups: {core: false, flow: true}}),
  {mode: 'rail', groups: {core: false, flow: true}},
);
assert.deepEqual(shell.normalizeShellState({mode: 'broken', groups: []}), {
  mode: 'expanded', groups: {},
});

assert.equal(shell.isNavItemActive('/reading/book-1', {
  href: '/reading', aliases: [],
}), true);
assert.equal(shell.isNavItemActive('/view/token-1', {
  href: '/add_task_by_web', aliases: ['/', '/view'],
}), true);
assert.equal(shell.isNavItemActive('/flywheel', {
  href: '/trend-radar', aliases: [],
}), false);
assert.equal(shell.isNavItemActive('/review/weekly', {
  href: '/review/daily', aliases: ['/review'], exact: true,
}), false);
assert.equal(shell.isNavItemActive('/review/', {
  href: '/review/daily', aliases: ['/review'], exact: true,
}), true);

const activeLink = {
  querySelector: (selector) => selector === '.nav-label'
    ? {textContent: '单篇深度学习'}
    : null,
};
const sidebar = {
  querySelector: (selector) => selector === '.nav-subitem.is-active, .nav-item.is-active'
    ? activeLink
    : null,
};
const documentStub = {title: 'localhost:8000/view/token-1'};
assert.equal(
  shell.syncProductPageTitle(sidebar, documentStub),
  '单篇深度学习 · LearnFlux',
);
assert.equal(documentStub.title, '单篇深度学习 · LearnFlux');

const branchClasses = new Set();
const branchToggle = {
  attributes: {},
  setAttribute(name, value) { this.attributes[name] = value; },
};
const branchSubitems = {hidden: false};
const branch = {
  classList: {
    toggle: (name, active) => active ? branchClasses.add(name) : branchClasses.delete(name),
  },
  querySelector: (selector) => ({
    '.nav-branch-toggle': branchToggle,
    '.nav-subitems': branchSubitems,
    '[data-nav-parent="true"] .nav-label': {textContent: '复盘'},
  })[selector] || null,
};
assert.equal(shell.setNavigationBranchExpanded(branch, false), false);
assert.equal(branchClasses.has('is-expanded'), false);
assert.equal(branchToggle.attributes['aria-expanded'], 'false');
assert.equal(branchToggle.attributes['aria-label'], '展开复盘二级导航');
assert.equal(branchSubitems.hidden, true);
assert.equal(shell.setNavigationBranchExpanded(branch, true), true);
assert.equal(branchClasses.has('is-expanded'), true);
assert.equal(branchToggle.attributes['aria-expanded'], 'true');
assert.equal(branchToggle.attributes['aria-label'], '收起复盘二级导航');
assert.equal(branchSubitems.hidden, false);
"""
        result = subprocess.run(
            ["node", "-e", node_test, str(APP_SHELL)],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr

    def test_visibility_handler_uses_one_strict_rule_for_existing_entries(self):
        node_test = r"""
const assert = require('node:assert/strict');
global.document = { body: null };
const shell = require(process.argv[1]);

const elements = [
  {dataset: {feature: 'reading'}, hidden: true},
  {dataset: {feature: 'trend_radar'}, hidden: true},
  {dataset: {feature: 'missing'}, hidden: false},
];
const root = {querySelectorAll: () => elements};
shell.applyFeatureVisibility(root, {reading: true, trend_radar: false});
assert.equal(elements[0].hidden, false);
assert.equal(elements[1].hidden, true);
assert.equal(elements[2].hidden, true);
"""
        result = subprocess.run(
            ["node", "-e", node_test, str(APP_SHELL)],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr

    def test_review_parent_is_contextual_and_one_child_owns_current_page(self):
        node_test = r"""
const assert = require('node:assert/strict');
global.document = { body: null };
const shell = require(process.argv[1]);

function link(href, dataset = {}) {
  const classes = new Set();
  return {
    dataset: {aliases: '', ...dataset},
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

const parent = link('/review', {navParent: 'true'});
const daily = link('/review/daily', {aliases: '/review', navMatch: 'exact'});
const weekly = link('/review/weekly', {navMatch: 'exact'});
const links = [parent, daily, weekly];
const sidebar = {
  querySelectorAll: (selector) => {
    assert.equal(selector, '.nav-item, .nav-subitem');
    return links;
  },
};

shell.reconcileNavigation(sidebar, '/review/weekly');
assert.equal(parent.classList.contains('is-active'), true);
assert.equal(parent.attributes['aria-current'], undefined);
assert.equal(daily.classList.contains('is-active'), false);
assert.equal(daily.attributes['aria-current'], undefined);
assert.equal(weekly.classList.contains('is-active'), true);
assert.equal(weekly.attributes['aria-current'], 'page');
"""
        result = subprocess.run(
            ["node", "-e", node_test, str(APP_SHELL)],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr

    def test_shell_source_observes_dynamic_feature_entries_without_backend_calls(self):
        source = APP_SHELL.read_text(encoding="utf-8")

        assert "MutationObserver" in source
        assert "addedNodes" in source
        assert "LEARNFLUX_UI_FEATURES" in source
        assert "replaceChildren" not in source
        assert "const NAV_GROUPS" not in source
        assert "fetch(" not in source

    def test_mobile_drawer_has_focus_trap_and_progressive_enhancement(self):
        script = APP_SHELL.read_text(encoding="utf-8")
        styles = APP_SHELL_CSS.read_text(encoding="utf-8")

        assert "focusableDrawerItems" in script
        assert "event.key === 'Tab'" in script
        assert "sidebar-drawer-open" in script
        assert ".shell-enhanced .sidebar" in styles
        assert "body.sidebar-drawer-open" in styles


class TestNavigationMarkup:
    def test_navigation_has_one_canonical_data_source_and_generated_partial(self):
        navigation = json.loads(NAVIGATION_DATA.read_text(encoding="utf-8"))
        partial = (
            TEMPLATE_ROOT / "partials" / "product_navigation.html"
        ).read_text(encoding="utf-8")

        assert [group["id"] for group in navigation["groups"]] == [
            "core", "flow", "insight", "system",
        ]
        assert navigation["items"]["trend_radar"]["feature"] == "trend_radar"
        assert navigation["items"]["trend_radar"]["href"] == "/trend-radar"
        review_children = navigation["items"]["review"]["children"]
        assert [child["label"] for child in review_children] == [
            "今日复盘", "周度复盘", "月度复盘", "年度复盘", "内在洞察",
        ]
        assert "PRODUCT_NAV_START" in partial
        assert "PRODUCT_NAV_END" in partial
        assert 'class="nav-branch-toggle"' in partial
        assert 'aria-controls="nav-review-children"' in partial
        assert (
            '<nav class="nav-subitems" id="nav-review-children" '
            'aria-label="复盘二级导航">'
        ) in partial
        assert partial.count("data-review-section=") == 5
        assert 'data-feature="trend_radar"' in partial
        assert re.search(r'<a[^>]*data-feature="trend_radar"[^>]*\shidden(?:\s|>)', partial)

        for template_name in ("base.html", "flywheel.html"):
            template = (TEMPLATE_ROOT / template_name).read_text(encoding="utf-8")
            assert '{% include "partials/product_navigation.html" %}' in template
            assert template.count("PRODUCT_NAV_START") == 0

    def test_static_shells_use_generated_navigation_and_feature_config_first(self):
        for filename in STATIC_SHELLS:
            html = (STATIC_ROOT / filename).read_text(encoding="utf-8")
            assert html.count("PRODUCT_NAV_START") == 1, filename
            assert html.count("PRODUCT_NAV_END") == 1, filename
            assert html.index("ui-features.js") < html.index("app-shell.js"), filename
            assert 'data-feature="trend_radar"' in html, filename
            assert re.search(
                r'<a[^>]*data-feature="trend_radar"[^>]*\shidden(?:\s|>)',
                html,
            ), filename
            for group_id in ("core", "flow", "insight", "system"):
                assert f'data-group="{group_id}"' in html, filename
                assert f'aria-controls="nav-{group_id}-items"' in html, filename
                assert f'id="nav-{group_id}-items"' in html, filename
            assert html.count('class="nav-branch-toggle"') == 1, filename
            assert 'aria-controls="nav-review-children"' in html, filename
            assert 'id="nav-review-children"' in html, filename

    def test_root_home_is_marketing_landing_without_product_shell(self):
        from video_transcript_api.api.routes.views import _HOME_HTML

        # Marketing home stays outside the product shell navigation contract.
        assert "PRODUCT_NAV_START" not in _HOME_HTML
        assert "sidebar-nav" not in _HOME_HTML
        assert "marketing-home" in _HOME_HTML
        assert 'href="#features"' in _HOME_HTML
        assert 'href="/add_task_by_web"' in _HOME_HTML

    def test_navigation_generator_reports_no_drift(self):
        result = subprocess.run(
            ["python", str(SYNC_NAVIGATION), "--check"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stdout + result.stderr


class TestAssetVersions:
    def test_every_shell_route_versions_the_ui_feature_config(self):
        route_files = (
            PROJECT_ROOT / "src/video_transcript_api/api/routes/views.py",
            PROJECT_ROOT / "src/video_transcript_api/api/routes/collections.py",
            PROJECT_ROOT / "src/video_transcript_api/api/routes/settings.py",
            PROJECT_ROOT / "src/video_transcript_api/api/routes/trend_radar.py",
            PROJECT_ROOT / "src/video_transcript_api/api/routes/visual_learning.py",
        )
        reading_route = PROJECT_ROOT / "src/video_transcript_api/api/routes/reading.py"
        if reading_route.exists():
            route_files = (*route_files, reading_route)

        for path in route_files:
            source = path.read_text(encoding="utf-8")
            assert '"ui-features.js"' in source, path.name

        if reading_route.exists():
            reading = reading_route.read_text(encoding="utf-8")
            assert 'replace("__ASSET_VERSION__", version)' in reading

    def test_direct_static_shells_stamp_the_current_feature_digest(self):
        digest = __import__("hashlib").sha256(FEATURE_CONFIG.read_bytes()).hexdigest()[:12]

        for filename in ("focus-studio.html", "history.html"):
            html = (STATIC_ROOT / filename).read_text(encoding="utf-8")
            assert f"/static/js/ui-features.js?v={digest}" in html, filename

    def test_shared_shell_assets_do_not_use_stale_handwritten_versions(self):
        stale = re.compile(r"20260712|20260722-blue")
        sources = [
            *(STATIC_ROOT / filename for filename in STATIC_SHELLS),
            TEMPLATE_ROOT / "base.html",
            TEMPLATE_ROOT / "flywheel.html",
        ]

        for path in sources:
            assert not stale.search(path.read_text(encoding="utf-8")), path.name

    def test_service_worker_precaches_the_versioned_feature_config(self):
        source = (STATIC_ROOT / "service-worker.js").read_text(encoding="utf-8")

        assert "/static/js/ui-features.js" in source
        assert "learnflux-pwa-20260722-shell" in source


class TestProductDesignSystem:
    def test_brand_cool_tokens_have_one_light_and_dark_source(self):
        source = PRODUCT_CSS.read_text(encoding="utf-8")

        light_tokens = (
            "--product-bg: #F6F8FB",
            "--product-sidebar: #EEF2F7",
            "--product-surface: #FFFFFF",
            "--product-ink: #172033",
            "--product-muted: #596579",
            "--product-subtle: #68758A",
            "--product-line: #DCE2EA",
            "--product-accent: #2868D8",
            "--product-accent-hover: #1F57B6",
            "--product-accent-soft: #E9F1FF",
            "--product-info: #0F7890",
            "--product-success: #18794E",
            "--product-warning: #8A5B00",
            "--product-danger: #B42318",
            "--product-attention: #C94B42",
        )
        dark_tokens = (
            "--product-bg: #0F141D",
            "--product-sidebar: #151C27",
            "--product-surface: #1B2431",
            "--product-ink: #F3F6FA",
            "--product-muted: #B5C0CF",
            "--product-subtle: #94A3B8",
            "--product-line: #2D3948",
            "--product-accent: #78A7FF",
            "--product-accent-hover: #91B7FF",
            "--product-info: #5DD5E8",
            "--product-success: #55D69E",
            "--product-warning: #F0C66C",
            "--product-danger: #FF8A80",
            "--product-attention: #FF948C",
        )

        for token in (*light_tokens, *dark_tokens):
            assert token in source

    def test_app_shell_is_the_only_owner_of_sidebar_layout(self):
        shell = APP_SHELL_CSS.read_text(encoding="utf-8")
        product = PRODUCT_CSS.read_text(encoding="utf-8")

        for selector in (
            ".sidebar {",
            ".sidebar-brand {",
            ".sidebar-nav {",
            ".nav-group-toggle {",
            ".nav-item {",
            ".topbar {",
            ".page-stage {",
        ):
            assert selector in shell
            assert f"body.product-linear {selector}" not in product

    def test_shell_targets_and_modes_are_accessible_and_responsive(self):
        source = APP_SHELL_CSS.read_text(encoding="utf-8")

        assert "--shell-sidebar: 280px" in source
        assert "--shell-sidebar-collapsed: 72px" in source
        assert "min-height: 44px" in source
        assert ".nav-group-toggle" in source
        assert "[aria-expanded=\"false\"] .nav-group-chevron" in source
        assert "body.sidebar-rail" in source
        assert "@media (max-width: 900px)" in source
        assert "outline: 2px solid var(--shell-focus)" in source

    def test_hidden_features_cannot_be_revealed_by_layout_css(self):
        shell = APP_SHELL_CSS.read_text(encoding="utf-8")
        assert re.search(
            r"\[data-feature\]\[hidden\][^{]*\{[^}]*display:\s*none\s*!important",
            shell,
            re.S,
        )

        for path in (
            PRODUCT_CSS,
            *(STATIC_ROOT / "css" / name for name in (
                "product-linear-core.css",
                "product-linear-insights.css",
                "product-linear-system.css",
            )),
        ):
            source = path.read_text(encoding="utf-8")
            assert "[hidden]" not in source

    def test_real_shells_use_the_product_class_and_visible_mobile_topbar(self):
        for filename in STATIC_SHELLS:
            html = (STATIC_ROOT / filename).read_text(encoding="utf-8")
            body_tag = re.search(r"<body\b[^>]*>", html).group(0)
            assert "product-linear" in body_tag, filename
            topbar_tag = re.search(r'<header class="topbar"[^>]*>', html).group(0)
            assert " hidden" not in topbar_tag, filename

    def test_page_adapters_do_not_restyle_the_shared_shell(self):
        forbidden = re.compile(
            r"(?:home-linear|product-linear\.page-focus)\s+"
            r"(?:\.sidebar|\.sidebar-brand|\.sidebar-nav|\.nav-item|\.topbar|\.brand-|\.shell-)"
        )
        for name in ("home-linear.css", "product-linear-core.css"):
            source = (STATIC_ROOT / "css" / name).read_text(encoding="utf-8")
            assert not forbidden.search(source), name

        for name in (
            "home-linear.css",
            "product-linear-core.css",
            "product-linear-insights.css",
            "product-linear-system.css",
        ):
            source = (STATIC_ROOT / "css" / name).read_text(encoding="utf-8")
            assert ".page-stage" not in source, name


class TestFeatureEntryCoverage:
    def test_home_marketing_cards_link_core_product_surfaces(self):
        from video_transcript_api.api.routes.views import _HOME_HTML

        # Marketing cards are public discovery links, not fail-closed shell nav.
        for href in (
            "/add_task_by_web",
            "/add_task_by_web#local-video-study",
            "/collections",
            "/visual-learning",
            "/reading",
            "/flywheel",
            "/study",
        ):
            assert f'href="{href}"' in _HOME_HTML, href

    def test_root_home_is_self_contained_marketing_page(self):
        from video_transcript_api.api.routes.views import _HOME_HTML

        assert 'class="page-home marketing-home"' in _HOME_HTML
        assert "/static/images/landing/01-single-study.png" in _HOME_HTML
        assert "/static/icon/learnflux-icon-256.png" in _HOME_HTML
        assert "app-shell.js" not in _HOME_HTML
        assert "product-linear.css" not in _HOME_HTML

    def test_secondary_feature_links_are_fail_closed_too(self):
        coverage = (
            (STATIC_ROOT / "collections.html", "/study", "study_player"),
            (TEMPLATE_ROOT / "cleaned.html", "/static/focus-studio.html", "focus_studio"),
            (TEMPLATE_ROOT / "error.html", "/static/history.html", "history"),
        )
        for path, href, feature_id in coverage:
            source = path.read_text(encoding="utf-8")
            tags = re.findall(rf'<a\b[^>]*href="{re.escape(href)}"[^>]*>', source)
            assert tags, path.name
            assert all(f'data-feature="{feature_id}"' in tag for tag in tags)
            assert all(" hidden" in tag for tag in tags)
