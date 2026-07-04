from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_study_page_uses_note_and_manuscript_panels():
    html = (PROJECT_ROOT / "src/web/static/study.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "src/web/static/js/study.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/study.css").read_text(encoding="utf-8")

    assert 'id="ai-notes-list"' in html
    assert 'id="chat-list"' in html
    assert 'id="chat-question"' in html
    assert 'id="chat-use-time"' not in html
    assert 'class="chat-composer"' in html
    assert 'class="chat-input-row"' in html
    assert 'data-tab="chat"' in html
    assert 'data-tab="notes"' not in html
    assert 'data-tab="courseware"' not in html
    assert "课件大纲" not in html
    assert "记当前点" not in html
    assert 'class="markdown-content" id="ai-overview"' in html
    assert "isPendingState" in js
    assert "renderMarkdown" in js
    assert "renderAINotes" in js
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
    assert "captureVideoFrames" in js
    assert "transcript-segment" in js
    assert "applyEstimatedTranscriptTimes" in js
    assert "panel-seek" in js
    assert "正在转录本地视频" in js
    assert "正在生成 AI 总结" in js
    assert "window.setTimeout(loadSession" in js
    assert ".manuscript-reader" in css
    assert ".ai-note-section" in css
    assert ".note-visual" in css
    assert ".chat-message" in css
    assert ".chat-composer" in css
    assert ".chat-thinking" in css
    assert ".chat-thinking-steps" in css
    assert ".chat-answer blockquote" in css
    assert ".chat-time-option" not in css
    assert "position: sticky" in css
    assert "overflow: auto" in css
