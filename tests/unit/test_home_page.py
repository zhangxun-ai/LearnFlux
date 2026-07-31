def test_home_page_exposes_local_video_study_entry():
    from video_transcript_api.api.routes.views import _HOME_HTML

    assert "本地视频学习" in _HOME_HTML
    assert "/add_task_by_web#local-video-study" in _HOME_HTML
    assert "单篇深度学习" in _HOME_HTML
    assert "边播边学" in _HOME_HTML
    assert "/static/images/landing/01-single-study.png" in _HOME_HTML
    assert "/static/icon/learnflux-icon-256.png" in _HOME_HTML
    assert _HOME_HTML.count("开始深度学习") >= 3
    assert "请在此处替换" not in _HOME_HTML
    assert "数据不用于模型训练" not in _HOME_HTML


def test_home_page_keeps_opportunity_entry_inside_flywheel():
    from video_transcript_api.api.routes.views import _HOME_HTML

    assert "选题机会" in _HOME_HTML
    assert 'href="/flywheel"' in _HOME_HTML
    assert "机会雷达" not in _HOME_HTML
    assert "/flywheel#opportunities" not in _HOME_HTML


def test_workbench_opens_local_file_panel_from_study_hash():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "#local-video-study" in app_js
    assert "tab-file" in app_js


def test_workbench_javascript_is_syntax_valid():
    from pathlib import Path
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for JavaScript syntax validation")

    project_root = Path(__file__).resolve().parents[2]
    app_js = project_root / "src/web/static/js/app.js"
    result = subprocess.run(
        [node, "--check", str(app_js)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_deep_learning_submit_does_not_route_posts_to_post_insights():
    """单篇深度学习入口必须与帖子洞察解耦，X/公众号链接不得自动跳转 /post。"""
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    submit_fn = app_js[
        app_js.index("async function submitTranscription(") : app_js.index(
            "function initializePage("
        )
    ]
    assert "window.location.href = '/post?url=" not in submit_fn
    assert "/post?url=" not in submit_fn
    assert "开始深度学习" in app_js
    assert "function submitLabelForUrl(url)" in app_js
    # 识别仍可标注平台，但动作必须是深度学习，而不是帖子洞察文案。
    assert "action: '深度学习解析'" in app_js
    assert "action: '帖子精华提炼" not in app_js


def test_workbench_upload_reports_http_errors_before_network_fallback():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "readUploadResponse" in app_js
    assert "response.text()" in app_js
    assert "HTTP ' + status" in app_js
    assert "error && error.message" in app_js


def test_workbench_link_form_exposes_optional_source_preservation():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/index.html").read_text(encoding="utf-8")
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert "preserve_source_file" in app_js
    assert "preserveSourceFile" in app_js

def test_workbench_history_cards_show_content_preview():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")
    css = (project_root / "src/web/static/css/workbench.css").read_text(encoding="utf-8")

    assert "getTaskSummary" in app_js
    assert "/api/audit/summary?view_token=" in app_js
    assert "summaryPreview" in app_js
    assert "hist-preview" in app_js
    assert ".hist-preview" in css


def test_workbench_history_exposes_marked_filter_and_badge():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/index.html").read_text(encoding="utf-8")
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert 'data-filter="marked"' in html
    assert "精华" in html
    assert "task.is_marked" in app_js
    assert "/api/marks/transcripts/" in app_js
    assert "refreshHistoryMarks" in app_js
    assert "/api/audit/history" in app_js
    assert "syncMarkedHistoryFromServer" in app_js
    assert "mergeMarkedHistoryItems" in app_js
    assert "typeFilter === 'marked' && task.is_marked" in app_js


def test_marked_history_keeps_local_media_classified_as_video():
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    assert node, "Node.js is required to verify browser history classification"

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")
    classifier_start = app_js.index("const LOCAL_MEDIA_HISTORY_EXTENSIONS")
    classifier_end = app_js.index("\nfunction buildHistoryCard", classifier_start)
    audit_start = app_js.index("function historyTypeFromAuditItem(item)")
    audit_end = app_js.index("\nfunction mergeMarkedHistoryItems", audit_start)
    function_source = app_js[classifier_start:classifier_end] + app_js[audit_start:audit_end]
    script = function_source + """
const results = [
    historyTypeFromAuditItem({video_url: 'local://lesson.mp4', title: 'lesson.mp4'}),
    historyTypeFromAuditItem({video_url: 'local://notes.pdf', title: 'notes.pdf'}),
    historyTypeFromAuditItem({video_url: 'https://x.com/example', platform: 'x'}),
    historyTypeFromAuditItem({video_url: 'https://example.com/video'}),
    histTypeOf({url: 'local://lesson.mp4', title: 'lesson.mp4', type: 'file'}),
];
process.stdout.write(JSON.stringify(results));
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == ["video", "file", "post", "video", "video"]


def test_workbench_local_upload_adds_file_to_recent_history():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "TaskHistoryManager.addTask" in app_js
    assert "type: mediaFile ? 'video' : 'file'" in app_js
    assert "title: fileObj.name" in app_js


def test_workbench_local_video_upload_opens_analysis_result():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "window.location.href = '/view/' + d.data.view_token;" in app_js


def test_workbench_submission_and_history_statuses_keep_polling():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "watchSubmittedTask" in app_js
    assert "ensureHistoryStatusPolling" in app_js
    assert "refreshRunningHistoryStatuses" in app_js
    assert "updateHistoryEntryFromStatus" in app_js
    assert "任务已提交，正在解析" in app_js
    assert "解析完成" in app_js
    assert "任务提交成功" not in app_js


def test_workbench_exposes_pasted_text_study_entry():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/index.html").read_text(encoding="utf-8")

    assert 'id="tab-text"' in html
    assert 'data-panel="panel-text"' in html
    assert 'id="panel-text"' in html
    assert 'id="study-text-title"' in html
    assert 'id="study-text-content"' in html
    assert 'id="study-text-submit"' in html


def test_home_page_loads_scoped_linear_theme_once_and_versions_it():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/index.html").read_text(encoding="utf-8")
    views = (
        project_root / "src/video_transcript_api/api/routes/views.py"
    ).read_text(encoding="utf-8")

    stylesheet = '/static/css/home-linear.css?v=__ASSET_VERSION__'
    assert html.count(stylesheet) == 1
    assert '<body class="app-shell has-app-shell product-linear page-home home-linear">' in html
    assert html.count('/static/css/product-linear.css?v=__ASSET_VERSION__') == 1
    assert 'static_dir / "css" / "product-linear.css"' in views
    assert 'static_dir / "css" / "home-linear.css"' in views

    assert html.count('/static/js/app.js?v=__ASSET_VERSION__') == 1
    for element_id in (
        "transcribe-form",
        "tab-link",
        "tab-file",
        "tab-text",
        "panel-link",
        "panel-file",
        "panel-text",
        "file-dropzone",
        "study-text-form",
        "history-container",
    ):
        assert f'id="{element_id}"' in html


def test_home_primary_action_uses_reference_control_density():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    css = (
        project_root / "src/web/static/css/workbench.css"
    ).read_text(encoding="utf-8")

    assert ".app-home .submit-btn" in css
    assert "min-height: 3rem !important;" in css
    assert "padding: 0.75rem 1.25rem !important;" in css
    assert "border-radius: var(--radius-control) !important;" in css


def test_workbench_submits_pasted_text_and_opens_study():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "submitStudyText" in app_js
    assert "'/api/study/text'" in app_js
    assert "study-text-form" in app_js
    assert "study-text-content" in app_js
    assert "'/study/' + data.data.view_token" in app_js
def test_transcription_strategy_and_cloud_quote_controls_are_public():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/index.html").read_text(encoding="utf-8")
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "本地转录 (免费)" in html
    assert "云端转录 (极速)" in html
    assert html.count('value="cloud" checked') == 2
    assert 'value="local" checked' not in html
    assert "transcriptionStrategy = 'cloud'" in app_js
    assert "fileStrategyEl ? fileStrategyEl.value : 'cloud'" in app_js
    assert "strategyEl ? strategyEl.value : 'cloud'" in app_js
    assert "transcription_strategy" in app_js
    assert "confirmCloudQuote" in app_js
    assert "useLocalForCloudQuote" in app_js
    assert "refreshCloudQuote" in app_js
    assert "自动推荐" not in html
