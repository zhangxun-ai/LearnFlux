from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_transcript_page_exposes_inline_visual_view_switcher():
    html = (PROJECT_ROOT / "src/web/templates/transcript.html").read_text(
        encoding="utf-8"
    )
    js = (
        PROJECT_ROOT / "src/web/static/js/transcript-visual-reader.js"
    ).read_text(encoding="utf-8")

    assert "/static/css/visual-learning.css" in html
    assert "/static/js/visual-learning.js" in html
    assert "/static/js/transcript-visual-reader.js" in html
    assert 'id="transcript-reader-text"' in html
    assert 'id="transcript-reader-visual"' in html
    assert 'id="transcript-summary-text-panel"' in html
    assert 'id="transcript-summary-visual-panel"' in html
    assert "transcript-secondary-section" in html
    assert 'id="transcript-immersive-reader"' not in html
    assert 'id="transcript-summary-data"' not in html
    assert "renderImmersiveReader" not in js
    assert "requestedDocumentTypes" in js
    assert "const DOCUMENT_TYPE = 'diagram'" in js
    assert "window.VisualLearning.render" in js
    assert "viewToken" in js
    assert ".accepts(" in js
    assert "secondarySections" in js
    assert "section.hidden = visual" in js
    assert "isActiveVisualState" in js
    assert "continueAfterState" in js
    assert "transcript-visual-progress" in html
    assert "transcript-visual-progress-fill" in html
    assert "document_type: DOCUMENT_TYPE" in js
    assert "full_note" not in js
    assert "overview" not in js
