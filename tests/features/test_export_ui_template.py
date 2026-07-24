from pathlib import Path


TEMPLATE = Path("src/web/templates/transcript.html")


def test_export_menu_keeps_existing_formats_and_adds_scope_options():
    content = TEMPLATE.read_text(encoding="utf-8")

    for scope in ('data-export-scope="analysis"', 'data-export-scope="calibrated"', 'data-export-scope="full"'):
        assert scope in content

    for format_name in ("'markdown'", "'pdf'", "'html'", "'png'"):
        assert f"executeExport({format_name}" in content


def test_export_sections_are_marked_for_scoped_page_exports():
    content = TEMPLATE.read_text(encoding="utf-8")

    for section in (
        'data-export-section="summary"',
        'data-export-section="comment_insight"',
        'data-export-section="calibrated"',
    ):
        assert section in content

    assert "ensureExportTranscriptSection" in content
    assert "/bundle?scope=" in content


def test_pdf_export_has_print_navigation_and_print_styles():
    content = TEMPLATE.read_text(encoding="utf-8")

    assert "buildExportPrintNav" in content
    assert "export-print-nav" in content
    assert "@media print" in content
    assert "afterprint" in content
