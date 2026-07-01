def test_home_page_exposes_local_video_study_entry():
    from video_transcript_api.api.routes.views import _HOME_HTML

    assert "本地视频学习" in _HOME_HTML
    assert "/add_task_by_web#local-video-study" in _HOME_HTML


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
