from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "web" / "static" / "js" / "app.js"


def test_recent_tasks_are_restored_from_the_server() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert "static async syncFromServer" in source
    assert "APIManager.getTaskHistory" in source
    assert "TaskHistoryManager.syncFromServer" in source


def test_active_and_cloud_confirmation_tasks_keep_a_stable_view_link() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert "awaiting_cloud_confirmation" in source
    assert "待确认费用" in source
    assert "查看并确认" in source
    assert "查看进度" in source
    assert 'aria-disabled="true">处理中' not in source
