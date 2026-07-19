from pathlib import Path


def test_local_media_upload_is_added_to_recent_history():
    app_js = Path("src/web/static/js/app.js").read_text(encoding="utf-8")

    local_upload_block = app_js[app_js.index("if (d && d.code === 202"):app_js.index("window.location.href = '/view/'")]

    assert "TaskHistoryManager.addTask({" in local_upload_block
    assert "if (!mediaFile)" not in local_upload_block
