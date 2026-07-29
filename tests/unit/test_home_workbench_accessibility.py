"""Regression checks for the accessible home workbench controls."""

import re
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src/web/static"


def test_workbench_app_js_parses_without_syntax_errors():
    """Merge leftovers once broke tab switching and history rendering entirely."""
    node = shutil.which("node")
    assert node, "Node.js is required to syntax-check the workbench script"

    app_js = STATIC_DIR / "js/app.js"
    result = subprocess.run(
        [node, "--check", str(app_js)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    source = app_js.read_text(encoding="utf-8")
    # Guard against duplicated top-level return after syncMarkedHistoryFromServer.
    assert source.count("function syncMarkedHistoryFromServer") == 1
    assert "\n}\n\nreturn markedHistorySyncPromise;\n}" not in source


def test_home_input_tabs_have_complete_aria_wiring_and_keyboard_support():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "js/app.js").read_text(encoding="utf-8")

    assert 'aria-controls="panel-link"' in html
    assert 'aria-controls="panel-file"' in html
    assert 'aria-controls="panel-text"' in html
    assert 'aria-labelledby="tab-link"' in html
    assert 'aria-labelledby="tab-file"' in html
    assert 'aria-labelledby="tab-text"' in html
    assert "ArrowRight" in js
    assert "ArrowLeft" in js
    assert "tabIndex" in js


def test_home_form_controls_have_programmatic_labels_and_native_upload_button():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "js/app.js").read_text(encoding="utf-8")

    assert 'for="share-content"' in html
    assert '<button type="button" class="file-dropzone" id="file-dropzone"' in html
    assert 'aria-describedby="dropzone-hint"' in html
    assert "dz.addEventListener('keydown'" not in js


def test_shared_shell_uses_design_tokens_without_layout_transitions():
    css = (STATIC_DIR / "css/app-shell.css").read_text(encoding="utf-8")

    assert "--shell-bg: #F6F8FB;" in css
    assert "--shell-sidebar-bg: #EEF2F7;" in css
    assert "--shell-accent: #2868D8;" in css
    assert "transition: width 180ms" not in css
    assert "backdrop-filter: blur(18px);" not in css


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _theme_token_values(css: str, token: str) -> list[str]:
    return re.findall(rf"{re.escape(token)}:\s*(#[0-9A-Fa-f]{{6}})", css)


def test_home_linear_theme_is_scoped_and_meets_wcag_contrast_contracts():
    css = (STATIC_DIR / "css/home-linear.css").read_text(encoding="utf-8")
    product_css = (STATIC_DIR / "css/product-linear.css").read_text(encoding="utf-8")

    assert "body.app-shell.home-linear" in css
    assert "--home-surface: var(--product-surface);" in css
    assert '[data-theme="dark"] body.product-linear' in product_css
    assert "!important" not in css
    for naked_selector in ("\n:root {", "\nbody {", "\nbutton {", "\n.sidebar {"):
        assert naked_selector not in css

    tokens = {
        token: _theme_token_values(product_css, token)
        for token in (
            "--product-surface",
            "--product-ink",
            "--product-muted",
            "--product-subtle",
            "--product-line-strong",
            "--product-focus",
        )
    }
    assert all(len(values) == 2 for values in tokens.values())

    for theme_index in (0, 1):
        surface = tokens["--product-surface"][theme_index]
        for text_token in ("--product-ink", "--product-muted", "--product-subtle"):
            assert _contrast_ratio(tokens[text_token][theme_index], surface) >= 4.5
        for ui_token in ("--product-line-strong", "--product-focus"):
            assert _contrast_ratio(tokens[ui_token][theme_index], surface) >= 3
