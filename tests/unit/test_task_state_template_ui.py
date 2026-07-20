from pathlib import Path


TEMPLATE_DIR = Path(__file__).parents[2] / "src" / "web" / "templates"
STATIC_DIR = Path(__file__).parents[2] / "src" / "web" / "static"


def test_error_page_exposes_a_single_clear_alert_and_non_inline_reload_action():
    source = (TEMPLATE_DIR / "error.html").read_text(encoding="utf-8")

    assert 'class="error-panel" role="alert"' in source
    assert 'data-reload-page' in source
    assert 'onclick="window.location.reload()"' not in source


def test_processing_page_respects_reduced_motion_and_describes_progress():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert '@media (prefers-reduced-motion: reduce)' in source
    assert 'role="progressbar"' in source
    assert 'aria-valuetext=' in source
    assert 'setAttribute("aria-valuetext"' in source


def test_transcript_reader_and_export_menu_are_keyboard_accessible():
    template_source = (TEMPLATE_DIR / "transcript.html").read_text(encoding="utf-8")
    reader_source = (STATIC_DIR / "js" / "transcript-visual-reader.js").read_text(
        encoding="utf-8"
    )

    assert 'aria-haspopup="dialog"' in template_source
    assert 'aria-expanded="false"' in template_source
    assert 'role="dialog"' in template_source
    assert 'role="radio"' in template_source
    assert "case 'ArrowRight':" in reader_source
    assert "case 'Home':" in reader_source
