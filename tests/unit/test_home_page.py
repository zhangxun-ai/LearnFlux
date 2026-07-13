def test_home_page_exposes_local_video_study_entry():
    from video_transcript_api.api.routes.views import _HOME_HTML

    assert "本地视频学习" in _HOME_HTML
    assert "/add_task_by_web#local-video-study" in _HOME_HTML


def test_home_page_keeps_opportunity_entry_inside_flywheel():
    from video_transcript_api.api.routes.views import _HOME_HTML

    assert "选题机会" in _HOME_HTML
    assert "机会雷达" not in _HOME_HTML
    assert "/flywheel#opportunities" not in _HOME_HTML


def test_workbench_opens_local_file_panel_from_study_hash():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "#local-video-study" in app_js
    assert "tab-file" in app_js


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


def test_workbench_submits_pasted_text_and_opens_study():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    app_js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "submitStudyText" in app_js
    assert "'/api/study/text'" in app_js
    assert "study-text-form" in app_js
    assert "study-text-content" in app_js
    assert "'/study/' + data.data.view_token" in app_js
