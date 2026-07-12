from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_visual_learning_renderer_exposes_safe_public_api():
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning.js"
    ).read_text(encoding="utf-8")

    assert "window.VisualLearning" in js
    assert "render:" in js
    assert "setTheme:" in js
    assert "exportSvg:" in js
    assert "textContent" in js
    assert ".innerHTML" not in js
    assert "onSourceRef" in js
    assert "data-source-ref" in js


def test_visual_learning_renderer_exposes_safe_two_layer_contract():
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning.js"
    ).read_text(encoding="utf-8")

    assert "renderTwoLayer" in js
    assert "activeDiagram" in js
    assert ":summary:section:" in js
    assert "vl-topic-entry" in js
    assert "data-section-id" in js
    assert "vl-two-layer-review" in js


def test_visual_learning_renderer_exposes_immersive_reader_contract():
    js = (PROJECT_ROOT / "src/web/static/js/visual-learning.js").read_text(
        encoding="utf-8"
    )
    css = (PROJECT_ROOT / "src/web/static/css/visual-learning.css").read_text(
        encoding="utf-8"
    )

    assert "renderImmersiveReader" in js
    assert "createReaderState" in js
    assert "normalizeMarkdownForReader" in js
    assert "captureReaderScroll" in js
    assert "restoreReaderScroll" in js
    assert "current.dataset.readerMode !== mode" in js
    assert "current.dataset.readerSection !== readerSection" in js
    assert "vl-reader-mode-tabs" in js
    assert "vl-reader-sections" in js
    assert "review_questions" in js
    assert "composeVisualAtlasDocument" in js
    assert "visualReaderNavItems" in js
    assert "vl-reader-visual-atlas" in js
    assert "scrollReaderToAnchor" in js
    assert "visualScope === 'global'" in js
    assert "vl-reader-no-sections" in js
    assert ".vl-immersive-reader" in css
    assert ".vl-reader-panel" in css
    assert '.vl-immersive-reader[data-reader-mode="visual"]' in css
    assert '.vl-immersive-reader[data-reader-mode="visual"].vl-reader-no-sections' in css
    assert ".vl-reader-visual-atlas" in css
    assert "prefers-reduced-motion" in css
    assert "原解读已不可用" in js
    assert "data-interpretation-section" in js
    assert "tabIndex = 0" in js
    assert "keydown" in js
    assert "Enter" in js
    assert "pairedSections" in js
    assert "renderSafeMarkdown" in js
    assert "appendInlineMarkdown" in js
    assert "node('blockquote'" in js
    assert "node('ul'" in js
    assert ".innerHTML" not in js


def test_renderer_hides_inline_source_refs_unless_explicitly_enabled():
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning.js"
    ).read_text(encoding="utf-8")
    study_js = (PROJECT_ROOT / "src/web/static/js/study.js").read_text(
        encoding="utf-8"
    )

    assert "readerMode === 'continuous'" in js
    assert "vl-continuous-article" in js
    assert "collectPageReferences" in js
    assert "vl-page-transition" in js
    assert "node('figure'" in js
    assert "renderReferences(block" in js
    assert "showInlineSourceRefs === true" in js
    assert "showSectionEvidence === true" in js
    assert "showInlineSourceRefs: true" in study_js
    assert "onSectionEvidence" in js


def test_visual_learning_renderer_supports_every_schema_block():
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning.js"
    ).read_text(encoding="utf-8")

    for block_type in (
        "hero_summary",
        "concept_chain",
        "process_flow",
        "comparison",
        "paired_contrast",
        "signal_flow",
        "decision_axis",
        "hierarchy",
        "timeline",
        "concept_grid",
        "mind_map",
        "callout",
        "review_questions",
    ):
        assert block_type in js
    css = (
        PROJECT_ROOT / "src/web/static/css/visual-learning.css"
    ).read_text(encoding="utf-8")
    assert "renderPairedContrast" in js
    assert "renderSignalFlow" in js
    assert "renderDecisionAxis" in js
    assert "appendTeachingFields" in js
    assert "item.why_needed" in js
    assert "item.example" in js
    assert "renderComparisonMatrix" in js
    assert "comparisonRows(columns)" in js
    assert "bridge.title = pair.risk_label" in js
    assert ".vl-paired-contrast" in css
    assert ".vl-teaching-fields" in css
    assert ".vl-comparison-matrix" in css
    assert ".vl-hierarchy-tree" in css
    assert "grid-template-columns: minmax(0, 1fr) 34px minmax(0, 1fr)" in css
    assert ".vl-signal-flow" in css
    assert ".vl-decision-axis" in css
    assert ".innerHTML" not in js
    assert "visited" in js


def test_svg_export_inlines_computed_styles_for_standalone_rendering():
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning.js"
    ).read_text(encoding="utf-8")

    assert "inlineComputedStyles" in js
    assert "window.getComputedStyle" in js


def test_visual_learning_styles_define_themes_and_print_layout():
    css = (
        PROJECT_ROOT / "src/web/static/css/visual-learning.css"
    ).read_text(encoding="utf-8")

    assert '[data-vl-theme="study-notes"]' in css
    assert '[data-vl-theme="clean-lecture"]' in css
    assert '[data-vl-theme="chalkboard"]' in css
    assert '[data-vl-theme="technical-blueprint"]' in css
    assert ".vl-process-flow" in css
    assert ".vl-mind-map" in css
    assert ".vl-block-concept_chain" in css
    assert "@media print" in css
    assert "@media (max-width: 720px)" in css


def test_visual_learning_assets_are_precached():
    service_worker = (
        PROJECT_ROOT / "src/web/static/service-worker.js"
    ).read_text(encoding="utf-8")

    assert "/static/css/visual-learning.css" in service_worker
    assert "/static/js/visual-learning.js" in service_worker


def test_visual_learning_workbench_exposes_real_progress_and_page_navigation():
    html = (PROJECT_ROOT / "src/web/static/visual-learning.html").read_text(encoding="utf-8")
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning-workbench.js"
    ).read_text(encoding="utf-8")
    css = (
        PROJECT_ROOT / "src/web/static/css/visual-learning.css"
    ).read_text(encoding="utf-8")

    assert 'id="visual-progress-stage"' in html
    assert 'id="visual-progress-meta"' in html
    assert 'id="visual-progress-fill"' in html
    assert 'id="visual-page-navigation"' in html
    assert "XMLHttpRequest" in js
    assert "upload.onprogress" in js
    assert "renderPageNavigation" in js
    assert "visual_fast_path" in js
    assert "workflow_progress" in js
    assert "lastOverallPercent" in js
    assert "5 * (event.loaded / event.total)" in js
    assert "document_type=diagram" in js
    assert "|| (payload && payload.source_progress)" not in js
    assert "ready_for_generation" in js
    assert "onSectionEvidence" in js
    assert "window.open" not in js
    assert ".vl-page-navigation" in css
    assert ".vl-progress-track" in css


def test_visual_learning_workbench_exposes_continuous_reader_and_evidence_drawer():
    html = (PROJECT_ROOT / "src/web/static/visual-learning.html").read_text(encoding="utf-8")
    js = (
        PROJECT_ROOT / "src/web/static/js/visual-learning-workbench.js"
    ).read_text(encoding="utf-8")
    css = (
        PROJECT_ROOT / "src/web/static/css/visual-learning.css"
    ).read_text(encoding="utf-8")

    assert 'id="visual-reader-exit"' in html
    assert 'id="visual-reading-progress"' in html
    assert 'role="progressbar"' in html
    assert 'id="visual-evidence-layer"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="visual-evidence-title"' in html
    assert "readerMode: 'continuous'" in js
    assert "onSectionEvidence" in js
    assert "openEvidenceDrawer" in js
    assert "aria-current" in js
    assert "window.open" not in js
    assert ".vl-reader-mode" in css
    assert ".vl-evidence-drawer" in css
    assert '[aria-current="location"]' in css
    assert "prefers-reduced-motion" in css
