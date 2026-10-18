"""WCAG contrast contracts for the shared product color system."""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "src/web/static"
PRODUCT_COLORS = STATIC_ROOT / "css/product-linear.css"
CORE_STYLES = STATIC_ROOT / "css/product-linear-core.css"
WORKBENCH_STYLES = STATIC_ROOT / "css/workbench.css"
READING_STYLES = STATIC_ROOT / "css/reading.css"
READING_SCRIPT = STATIC_ROOT / "js/reading.js"
SETTINGS_PAGE = STATIC_ROOT / "settings.html"
HISTORY_PAGE = STATIC_ROOT / "history.html"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(source: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", source)
    assert match, f"missing CSS block: {selector}"
    return match.group(1)


def _variables(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def _rgb(color: str) -> tuple[float, float, float]:
    value = color.strip()
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), f"expected opaque hex color, got {value}"
    return tuple(int(value[index : index + 2], 16) / 255 for index in (1, 3, 5))


def _luminance(color: str) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in _rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_product_semantic_text_pairs_meet_wcag_aa_in_light_and_dark_themes():
    source = _source(PRODUCT_COLORS)
    light = _variables(_block(source, "body.product-linear"))
    dark = {**light, **_variables(_block(source, '[data-theme="dark"] body.product-linear'))}

    pairs = (
        ("--product-ink", "--product-page"),
        ("--product-muted", "--product-page"),
        ("--product-subtle", "--product-sidebar"),
        ("--product-on-accent", "--product-accent"),
        ("--product-info", "--product-info-soft"),
        ("--product-success", "--product-success-soft"),
        ("--product-warning", "--product-warning-soft"),
        ("--product-danger", "--product-danger-soft"),
    )

    failures = []
    for theme_name, palette in (("light", light), ("dark", dark)):
        for foreground_name, background_name in pairs:
            ratio = _contrast(palette[foreground_name], palette[background_name])
            if ratio < 4.5:
                failures.append(
                    f"{theme_name} {foreground_name}/{background_name}: {ratio:.2f}:1"
                )

    assert failures == []


def test_primary_controls_use_on_accent_text_instead_of_hardcoded_white():
    contracts = (
        (WORKBENCH_STYLES, ".filter-chip.active"),
        (WORKBENCH_STYLES, ".hist-btn.primary"),
        (WORKBENCH_STYLES, ".app-home .submit-btn"),
        (SETTINGS_PAGE, ".btn"),
        (HISTORY_PAGE, ".btn-primary"),
    )

    for path, selector in contracts:
        declaration = _block(_source(path), selector)
        assert re.search(
            r"color\s*:\s*var\(--product-on-accent(?:\s*,\s*#fff(?:fff)?)?\)",
            declaration,
            re.IGNORECASE,
        ), f"{path.relative_to(PROJECT_ROOT)} {selector} must use --product-on-accent"


def test_collection_activity_statuses_use_semantic_contrast_tokens():
    source = _source(CORE_STYLES)
    active_tab = _block(source, "body.product-linear.page-collections .lc-tab.active")
    assert "background: var(--product-surface)" in active_tab
    assert "color: var(--product-ink)" in active_tab

    contracts = (
        ("ready", "is-ready", "success"),
        ("working", "is-working", "info"),
        ("danger", "is-failed", "danger"),
    )
    for tone, state, token in contracts:
        selector = (
            f'body.product-linear.page-collections .lc-status-pill[data-tone="{tone}"],\n'
            f"body.product-linear.page-collections .lc-summary-status-badge.{state}"
        )
        declaration = _block(source, selector)
        assert f"color: var(--product-{token})" in declaration
        assert f"background: var(--product-{token}-soft)" in declaration

    activity_contracts = (
        ("body.product-linear.page-collections .lc-status.summary_pending", "warning"),
        ("body.product-linear.page-collections .lc-status.success", "success"),
        ("body.product-linear.page-collections .lc-status.failed", "danger"),
        (
            "body.product-linear.page-collections .lc-status.processing,\n"
            "body.product-linear.page-collections .lc-status.calibrating",
            "info",
        ),
    )
    for selector, token in activity_contracts:
        declaration = _block(source, selector)
        assert f"color: var(--product-{token})" in declaration
        assert f"background: var(--product-{token}-soft)" in declaration


def test_reading_error_status_uses_danger_tokens_only_for_errors():
    styles = _source(READING_STYLES)
    script = _source(READING_SCRIPT)

    error_block = _block(
        styles,
        ".reading-status.is-error,\n.reading-import-status.is-error",
    )
    assert "color: var(--product-danger)" in error_block
    assert "background: var(--product-danger-soft)" in error_block
    assert "elements.importStatus.classList.toggle('is-error'" in script
