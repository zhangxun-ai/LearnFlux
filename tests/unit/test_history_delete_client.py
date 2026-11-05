"""Regression tests for the homepage task-history deletion flow."""

from pathlib import Path
import subprocess


APP_JS = (
    Path(__file__).resolve().parents[2]
    / "src/web/static/js/app.js"
)


def test_history_delete_persists_visibility_before_removing_local_entry():
    """History cleanup must retain shared results and wait for server success."""
    source = APP_JS.read_text(encoding="utf-8")
    history_class = source.split("class TaskHistoryManager", 1)[1]
    method = history_class.split("static async deleteTask(taskId)", 1)[1].split(
        "/**", 1
    )[0]

    assert "APIManager.deleteTask(taskId)" not in method
    assert method.index("await APIManager.removeHistoryTasks([taskId])") < method.index(
        "StorageManager.set"
    )


def test_home_history_removal_behaviors():
    result = subprocess.run(
        ["node", "tests/frontend/home_history_removal_behavior.cjs"],
        cwd=APP_JS.parents[4], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
