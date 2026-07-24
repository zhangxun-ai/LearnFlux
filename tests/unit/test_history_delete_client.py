"""Regression tests for the homepage task-history deletion flow."""

from pathlib import Path


APP_JS = (
    Path(__file__).resolve().parents[2]
    / "src/web/static/js/app.js"
)


def test_history_delete_invalidates_server_cache_before_removing_local_entry():
    """Deleting history must not leave a reusable server-side transcript cache."""
    source = APP_JS.read_text(encoding="utf-8")
    history_class = source.split("class TaskHistoryManager", 1)[1]
    method = history_class.split("static async deleteTask(taskId)", 1)[1].split(
        "/**", 1
    )[0]

    assert "await APIManager.deleteTask(taskId)" in method
    assert method.index("await APIManager.deleteTask(taskId)") < method.index(
        "StorageManager.set"
    )
