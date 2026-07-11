from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_transcript_page_exposes_one_click_immersive_visual_reader():
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
    assert 'id="transcript-immersive-reader"' in html
    assert 'id="transcript-summary-data"' in html
    assert "renderImmersiveReader" in js
    assert "requestedDocumentTypes" in js
    assert "viewToken" in js
    assert ".accepts(" in js
    assert "document_type: documentType" in js
