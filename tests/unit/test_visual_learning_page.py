from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_visual_learning_page_exposes_text_file_and_diagram_controls():
    html = (
        PROJECT_ROOT / "src/web/static/visual-learning.html"
    ).read_text(encoding="utf-8")

    assert 'id="visual-source-text"' in html
    assert 'id="visual-source-file"' in html
    assert 'id="visual-text-title"' in html
    assert 'id="visual-text-content"' in html
    assert 'id="visual-file-input"' in html
    assert 'id="visual-diagram-type"' in html
    assert 'id="visual-style"' in html
    assert 'id="visual-generate"' in html
    assert 'id="visual-canvas"' in html
    assert 'id="visual-history"' in html
    assert 'id="visual-recommendations"' in html
    assert "css/editorial.css" in html
    assert "visual-learning.css?v=5" in html
    assert '<h1>图解生成</h1>' not in html


def test_visual_learning_workbench_uses_shared_shell_tokens():
    css = (
        PROJECT_ROOT / "src/web/static/css/visual-learning.css"
    ).read_text(encoding="utf-8")

    workbench_css = css[
        css.index(".vl-workbench {") : css.index("@media (max-width: 900px)")
    ]


def test_visual_learning_workbench_uses_existing_ingestion_and_visual_apis():
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning-workbench.js"
    ).read_text(encoding="utf-8")

    assert "/api/study/text" in js
    assert "/api/study/upload" in js
    assert "/api/study/" in js
    assert "/api/visual-learning/study/" in js
    assert "/api/visual-learning/documents?document_type=diagram" in js
    assert "document_id" in js
    assert "window.VisualLearning.render" in js
    assert "window.VisualLearning.exportSvg" in js
    assert "window.print" in js
    assert "openEvidenceDrawer" in js
    assert "evidenceMeta" in js


def test_app_shell_adds_visual_learning_navigation():
    js = (PROJECT_ROOT / "src/web/static/js/app-shell.js").read_text(encoding="utf-8")

    assert "/visual-learning" in js
    assert "图解生成" in js


def test_visual_workbench_is_precached():
    service_worker = (
        PROJECT_ROOT / "src/web/static/service-worker.js"
    ).read_text(encoding="utf-8")

    assert "/visual-learning" in service_worker
    assert "/static/js/visual-learning-workbench.js" in service_worker
