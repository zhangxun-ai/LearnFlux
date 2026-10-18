"""Accessibility contracts for priority workspaces and tab systems."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "src/web"
STATIC_ROOT = WEB_ROOT / "static"
TEMPLATE_ROOT = WEB_ROOT / "templates"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _soup(path: Path) -> BeautifulSoup:
    return BeautifulSoup(_source(path), "html.parser")


def _has_programmatic_label(soup: BeautifulSoup, control_id: str) -> bool:
    control = soup.find(id=control_id)
    assert control is not None, f"missing control #{control_id}"
    if str(control.get("aria-label") or "").strip():
        return True
    if str(control.get("aria-labelledby") or "").strip():
        return True
    if soup.find("label", attrs={"for": control_id}) is not None:
        return True
    return control.find_parent("label") is not None


def test_priority_workspace_form_controls_have_programmatic_labels():
    contracts = {
        TEMPLATE_ROOT / "post_insight.html": ("post-url",),
        TEMPLATE_ROOT / "flywheel.html": (
            "url",
            "f-subscribe",
            "f-blogger",
            "f-status",
            "f-type",
            "f-date",
            "f-sort",
            "o-date",
            "o-type",
            "o-subscribe",
            "sub-url",
            "prompt-media-type",
            "prompt-body",
        ),
        STATIC_ROOT / "history.html": (
            "filterRecordType",
            "filterStartDate",
            "filterEndDate",
            "filterPlatform",
            "authorMultiSelect",
            "filterStatus",
            "filterRead",
            "filterMarked",
            "filterQ",
            "selectAllChk",
        ),
        STATIC_ROOT / "focus-studio.html": ("focus-editor",),
    }

    for path, control_ids in contracts.items():
        soup = _soup(path)
        missing = [control_id for control_id in control_ids if not _has_programmatic_label(soup, control_id)]
        assert missing == [], f"{path.relative_to(PROJECT_ROOT)} missing labels: {missing}"


def _assert_tab_contract(
    soup: BeautifulSoup,
    tab_id: str,
    panel_id: str,
    *,
    selected: bool,
) -> None:
    tab = soup.find(id=tab_id)
    panel = soup.find(id=panel_id)
    assert tab is not None, f"missing tab #{tab_id}"
    assert panel is not None, f"missing panel #{panel_id}"
    assert tab.get("role") == "tab"
    assert tab.get("aria-controls") == panel_id
    assert tab.get("aria-selected") == ("true" if selected else "false")
    assert tab.get("tabindex") == ("0" if selected else "-1")
    assert panel.get("role") == "tabpanel"
    assert panel.get("aria-labelledby") == tab_id
    assert panel.has_attr("hidden") is (not selected)


def test_study_tabs_have_complete_aria_relationships():
    soup = _soup(STATIC_ROOT / "study.html")
    _assert_tab_contract(soup, "study-library-tab-single", "study-single-import", selected=True)
    _assert_tab_contract(soup, "study-library-tab-collection", "study-collection-import", selected=False)

    for name in ("transcript", "notes", "ai", "visual", "chat"):
        _assert_tab_contract(
            soup,
            f"study-tab-{name}",
            f"tab-{name}",
            selected=name == "transcript",
        )


def test_visual_learning_tabs_have_complete_aria_relationships():
    soup = _soup(STATIC_ROOT / "visual-learning.html")
    _assert_tab_contract(soup, "visual-source-text", "visual-text-panel", selected=True)
    _assert_tab_contract(soup, "visual-source-file", "visual-file-panel", selected=False)


def test_flywheel_tabs_have_complete_aria_relationships():
    soup = _soup(TEMPLATE_ROOT / "flywheel.html")
    for name in ("analyze", "opportunities", "history", "bloggers", "settings"):
        _assert_tab_contract(
            soup,
            f"flywheel-tab-{name}",
            f"v-{name}",
            selected=name == "analyze",
        )


def test_priority_tab_systems_support_roving_keyboard_navigation():
    scripts = (
        _source(STATIC_ROOT / "js/study.js"),
        _source(STATIC_ROOT / "js/visual-learning-workbench.js"),
        _source(TEMPLATE_ROOT / "flywheel.html"),
    )
    for source in scripts:
        for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
            assert key in source
        assert "tabIndex" in source
        assert ".focus()" in source


def test_visual_learning_skip_link_remains_same_document_without_a_base_url():
    html = _source(STATIC_ROOT / "visual-learning.html")
    route = _source(PROJECT_ROOT / "src/video_transcript_api/api/routes/visual_learning.py")

    assert '<a class="skip-link" href="#main-content">' in html
    assert '<main class="main-area" id="main-content" tabindex="-1">' in html
    assert "<base " not in html
    assert 'href="/static/css/visual-learning.css' in html
    assert 'src="/static/js/visual-learning-workbench.js' in html
    assert "<base " not in route
    assert "base href" not in route


def test_history_dynamic_checkboxes_and_alias_inputs_receive_accessible_names():
    source = _source(STATIC_ROOT / "history.html")

    assert "author-checkbox-" in source
    assert "label.htmlFor = checkbox.id" in source
    assert "checkbox.setAttribute('aria-label'" in source
    assert 'aria-label="全选当前页记录"' in source
    assert 'aria-label="Webhook 别名"' in source


def test_focus_journal_tabs_and_editor_are_semantically_connected():
    soup = _soup(STATIC_ROOT / "focus-studio.html")
    _assert_tab_contract(soup, "journal-tab-history", "journal-panel-history", selected=True)
    _assert_tab_contract(soup, "journal-tab-review", "journal-panel-review", selected=False)


def test_app_shell_key_touch_targets_are_at_least_44_css_pixels():
    source = _source(STATIC_ROOT / "css/app-shell.css")

    assert "width: 44px;\n    min-width: 44px;\n    height: 44px;\n    min-height: 44px;" in source
    assert "@media (max-width: 900px)" in source
    assert ".nav-group-toggle,\n    .nav-item,\n    .nav-subitem" in source
