"""Responsive reading-layout contracts for the transcript result page."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT_ROOT / "src/web/templates/transcript.html"


def _source() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_transcript_uses_a_page_specific_body_scope():
    source = _source()

    assert "{% block body_class %}page-result transcript-result-page page-transcript workbench-meadow{% endblock %}" in source
    assert '/static/css/workbench-wildwood.css?v={{ asset_ver }}' in source


def test_mobile_gutters_override_the_late_desktop_paper_padding():
    source = _source()
    desktop_padding = source.index("padding: 64px 80px;")
    mobile_override = source.rindex("@media (max-width: 720px)")

    assert mobile_override > desktop_padding
    responsive = source[mobile_override:]
    assert "body.transcript-result-page.app-shell .page-stage" in responsive
    assert "padding: 16px 0 40px;" in responsive
    assert "body.transcript-result-page.app-shell .page-stage > .container" in responsive
    assert "padding: 24px max(20px, env(safe-area-inset-right)) 48px max(20px, env(safe-area-inset-left));" in responsive
    assert "border-right: 0;" in responsive
    assert "border-left: 0;" in responsive
    assert "@media (max-width: 360px)" in responsive
    assert "padding-right: max(16px, env(safe-area-inset-right));" in responsive
    assert "padding-left: max(16px, env(safe-area-inset-left));" in responsive


def test_mobile_title_actions_and_reading_content_can_reflow():
    source = _source()
    responsive = source[source.rindex("@media (max-width: 720px)"):]

    assert "body.transcript-result-page .header {" in source
    assert "padding: 0 0 28px;" in source
    assert "white-space: normal;" in responsive
    assert "overflow-wrap: anywhere;" in responsive
    assert "body.transcript-result-page .top-actions" in responsive
    assert "flex-wrap: wrap;" in responsive
    assert "min-height: 44px;" in responsive
    assert "body.transcript-result-page .section-header" in responsive
    assert "flex-direction: column;" in responsive
    assert "body.transcript-result-page .content table" in responsive
    assert "display: block;" in responsive
    assert "overflow-x: auto;" in responsive
    assert "body.transcript-result-page .content :is(img, video, svg, canvas)" in responsive
    assert "max-width: 100%;" in responsive
    assert "body.transcript-result-page .floating-toc-mobile-btn" in responsive
    assert "min-width: 52px;" in responsive
    assert "height: 52px;" in responsive
    assert "bottom: max(16px, calc(env(safe-area-inset-bottom) + 8px));" in responsive
