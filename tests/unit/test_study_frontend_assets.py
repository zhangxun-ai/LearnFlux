from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_study_page_uses_note_and_manuscript_panels():
    html = (PROJECT_ROOT / "src/web/static/study.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "src/web/static/js/study.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/study.css").read_text(encoding="utf-8")

    assert '/static/css/visual-learning.css' in html
    assert '/static/js/visual-learning.js' in html
    assert 'id="visual-learning-overview"' in html
    assert 'id="visual-learning-status"' in html
    assert 'id="visual-expand"' in html
    assert 'id="visual-full-note"' in html
    assert 'id="visual-theme"' in html
    assert 'id="visual-learning-dialog"' in html
    assert 'id="visual-learning-modal-content"' in html
    assert 'id="visual-modal-close"' in html
    assert 'id="visual-export-svg"' in html
    assert 'id="visual-print"' in html
    assert 'id="visual-modal-status"' in html
    assert 'id="visual-regenerate"' in html
    assert 'id="study-source-card"' in html
    assert 'id="study-source-open"' in html
    assert 'id="study-page-context"' in html
    assert 'id="study-workbench-title"' in html
    assert 'id="chat-list"' in html
    assert 'id="chat-question"' in html
    assert 'id="chat-use-time"' not in html
    assert 'class="chat-composer"' in html
    assert 'class="chat-input-row"' in html
    assert 'data-tab="chat"' in html
    assert 'data-tab="notes"' in html
    assert 'data-tab="courseware"' not in html
    assert "课件大纲" not in html
    assert "记当前点" not in html
    assert 'class="markdown-content" id="ai-overview"' in html
    assert "isPendingState" in js
    assert "renderMarkdown" in js
    assert "ensureVisualOverview" in js
    assert "requestVisualGeneration" in js
    assert "/api/visual-learning/study/" in js
    assert "window.VisualLearning.render" in js
    assert "onSourceRef" in js
    assert "readerMode" not in js
    assert "force: true" in js
    assert "visual_source" in js
    assert "full_note" in js
    assert "sendChat" in js
    assert "renderThinking" in js
    assert "startChatThinking" in js
    assert "chatErrorMessage" in js
    assert "正在思考" in js
    assert "阅读视频全文" in js
    assert "time_seconds" not in js
    assert "chatUseTime" not in js
    assert "chatTimeLabel" not in js
    assert "^[-*_]{3,}$" in js
    assert "blockquote" in js
    assert "AI 接口还没有被当前运行中的服务加载" in js
    assert "/ai-chat" in js
    assert "renderCourseware" not in js
    assert "captureVideoFrames" not in js
    assert "buildStudySections" not in js
    assert "generateNoteFrames" not in js
    assert "transcript-segment" in js
    assert "applyEstimatedTranscriptTimes" in js
    assert "renderSourceMode" in js
    assert "source.kind" in js
    assert "is-document-source" in js
    assert "studySourceOpen" in js
    assert "studyPageContext" in js
    assert "studyWorkbenchTitle" in js
    assert "panel-seek" in js
    assert "playerRuntime.sameMediaResource" in js
    assert "正在转录本地视频" in js
    assert "正在生成 AI 总结" in js
    assert "window.setTimeout(loadSession" in js
    assert ".manuscript-reader" in css
    assert ".study-visual-toolbar" in css
    assert ".study-visual-dialog" in css
    assert ".study-visual-preview" in css
    assert ".study-source-card" in css
    assert ".is-document-source" in css
    assert ".chat-message" in css
    assert ".chat-composer" in css
    assert ".chat-thinking" in css
    assert ".chat-thinking-steps" in css
    assert ".chat-answer blockquote" in css
    assert ".chat-time-option" not in css
    assert "position: sticky" in css
    assert "overflow: auto" in css


def test_study_note_editor_supports_autosave_binding_sync_and_conflicts():
    html = (PROJECT_ROOT / "src/web/static/study.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "src/web/static/js/study.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/study.css").read_text(encoding="utf-8")

    for fragment in (
        'id="study-note-editor"',
        'id="study-note-status"',
        'id="study-note-sync"',
        'id="study-note-binding"',
        'id="obsidian-binding-dialog"',
        'id="obsidian-transcript-directory"',
        'id="obsidian-note-directory"',
        'id="obsidian-binding-save"',
        'id="obsidian-conflict-dialog"',
        'id="obsidian-conflict-app"',
        'id="obsidian-conflict-file"',
        'data-choice="app"',
        'data-choice="obsidian"',
        'data-choice="recreate_from_app"',
        'data-choice="accept_external_deletion"',
    ):
        assert fragment in html

    assert "function noteContextKey" in js
    assert "function bindingApiBase" in js
    assert "async function loadStudyNote" in js
    assert "new AbortController()" in js
    assert "async function saveStudyNote" in js
    assert "expected_revision" in js
    assert "window.setTimeout(saveStudyNote" in js
    assert "async function syncStudyNoteToObsidian" in js
    assert "/note-document" in js
    assert "/obsidian-binding" in js
    assert "/obsidian-sync" in js
    assert "/obsidian-conflict/resolve" in js
    assert "/api/obsidian/directories?root=raw" in js
    assert "/api/obsidian/directories?root=vault" in js
    assert "result.overall === 'partial'" in js
    assert "文字稿未就绪，笔记已保存在学习页" in js
    assert "showObsidianConflict" in js
    assert "recreate_from_app" in js
    assert "accept_external_deletion" in js

    assert ".study-note-editor" in css
    assert ".study-note-actions" in css
    assert ".obsidian-dialog" in css
    assert ".obsidian-conflict-grid" in css
    assert ":focus-visible" in css


def test_study_visual_tab_activates_and_renders_both_layers_continuously():
    html = (PROJECT_ROOT / "src/web/static/study.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "src/web/static/js/study.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/study.css").read_text(encoding="utf-8")

    assert 'id="visual-learning-overview"' in html
    assert 'id="visual-full-note-status"' in html
    assert 'id="visual-full-note-retry"' in html
    assert "study-visual-continuous" in html
    assert "overview" in js
    assert "full_note" in js
    assert "activateVisualLearning" in js
    assert "window.VisualLearning.renderTwoLayer" in js
    assert "window.VisualLearning.activeDiagram" in js
    assert "setFullNoteStatus" in js
    assert "requestVisualGeneration('full_note', { force: true })" in js
    assert "visualTabActive" in js
    assert "state.visualActivated = false" in js
    assert "if (state.visualTabActive) activateVisualLearning();" in js
    render_session = js[js.index("function renderSession"):js.index("function renderSourceMode")]
    assert "ensureVisualOverview" not in render_session
    visual_source_ready = js[js.index("function visualSourceReady"):js.index("function setVisualStatus")]
    assert "session.ai" in visual_source_ready
    assert "transcript" not in visual_source_ready
    assert ".study-visual-two-layer" in css
    assert ".study-visual-layer-state" in css
    assert ".vl-two-layer-section" in css
    assert "@media print" in css
    assert "#tab-visual" in css
    assert ".study-visual-toolbar" in css
    assert "overflow: visible" in css
