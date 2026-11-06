"""History cleanup uses isolated databases and never deletes shared artifacts."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.utils.logging.audit_logger import AuditLogger


@pytest.fixture()
def history_app(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import audit, tasks
    from video_transcript_api.api.services.transcription import verify_token

    manager = CacheManager(cache_dir=str(tmp_path / "cache"))
    logger = AuditLogger(db_path=str(tmp_path / "audit.db"))
    user = {"user_id": "alice", "api_key": "test-alice-history"}
    monkeypatch.setattr(audit, "get_cache_manager", lambda: manager)
    monkeypatch.setattr(audit, "audit_logger", logger)
    monkeypatch.setattr(tasks, "cache_manager", manager)
    app = FastAPI()
    app.include_router(audit.router)
    app.include_router(tasks.router)

    async def authenticate():
        return user

    app.dependency_overrides[verify_token] = authenticate
    with TestClient(app) as client:
        yield client, manager, logger, user
    manager.close()


def create_task(manager, owner="alice", title="Repeated post"):
    task = manager.create_task(url="https://example.com/same", owner_user_id=owner)
    manager.update_task_status(task["task_id"], "success", title=title)
    return task


def remove(client, *tasks):
    return client.post("/api/audit/history/remove", json={"task_ids": [t["task_id"] for t in tasks]})


def test_remove_only_selected_duplicate_and_preserve_results_after_reopen(history_app):
    client, manager, logger, _ = history_app
    first, duplicate = create_task(manager), create_task(manager)
    # Preserve both private source files and the shared cache directory verbatim.
    source = manager.cache_dir / "source.txt"
    source.write_text("Original source", encoding="utf-8")
    cached = manager.save_cache(
        platform="youtube", url="https://example.com/same", media_id="same",
        use_speaker_recognition=False, transcript_data="Shared transcript",
        transcript_type="capswriter", title="Repeated post",
    )
    for task in (first, duplicate):
        logger.log_api_call(api_key="test-alice-history", user_id="alice", endpoint="/api/transcribe",
                            task_id=task["task_id"], status_code=200)

    assert remove(client, first).status_code == 200
    assert remove(client, first).status_code == 200  # Safe retry after a lost response.
    history = client.get("/api/audit/history?status=all").json()["data"]
    assert history["total"] == 1
    assert history["items"][0]["task_id"] == duplicate["task_id"]
    assert client.get("/api/tasks?limit=1").json()["data"]["items"][0]["task_id"] == duplicate["task_id"]
    assert client.get("/api/audit/filter-options").json()["data"]["total"] == 1
    assert source.read_text(encoding="utf-8") == "Original source"
    assert manager.get_task_by_id(first["task_id"]) is not None
    assert manager.get_view_data_by_token(first["view_token"]) is not None
    assert manager.get_cache(platform="youtube", media_id="same") is not None
    assert cached["transcript_file"]
    with sqlite3.connect(logger.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM api_audit_logs").fetchone()[0] == 2
    reopened = CacheManager(cache_dir=str(manager.cache_dir))
    assert [t["task_id"] for t in reopened.list_recent_tasks(owner_user_id="alice")] == [duplicate["task_id"]]
    reopened.close()


def test_retired_delete_preserves_shared_result_and_active_task(history_app):
    client, manager, _, _ = history_app
    url = "https://example.com/shared"
    done = manager.create_task(url=url, platform="generic", media_id="shared", owner_user_id="alice")
    active = manager.create_task(url=url, platform="generic", media_id="shared", owner_user_id="alice")
    manager.update_task_status(done["task_id"], "success")
    manager.update_task_status(active["task_id"], "processing")
    cache = manager.save_cache(
        platform="generic", url=url, media_id="shared", use_speaker_recognition=False,
        transcript_data="Shared transcript", transcript_type="capswriter",
    )

    response = client.delete(f"/api/task/{done['task_id']}")

    assert response.status_code == 410
    assert manager.get_task_by_id(done["task_id"])["status"] == "success"
    assert manager.get_task_by_id(active["task_id"])["status"] == "processing"
    assert manager.get_cache(platform="generic", media_id="shared")["transcript_data"] == "Shared transcript"
    assert cache["transcript_file"]


def test_batch_authorizes_all_before_writing_and_keeps_owner_isolation(history_app):
    client, manager, _, user = history_app
    first, second, foreign = create_task(manager), create_task(manager), create_task(manager, "bob")
    assert remove(client, first, foreign).status_code == 403
    assert len(manager.list_recent_tasks(owner_user_id="alice")) == 2
    assert remove(client, first, second).json()["data"]["removed_count"] == 2
    assert client.get("/api/audit/history?status=all").json()["data"]["total"] == 0
    assert client.get("/api/tasks").json()["data"]["items"] == []
    user.update(user_id="bob", api_key="test-bob-history")
    assert client.get("/api/tasks").json()["data"]["items"][0]["task_id"] == foreign["task_id"]


def test_legacy_audit_only_and_unowned_scope(history_app):
    client, manager, logger, user = history_app
    unowned = create_task(manager, None)
    assert remove(client, unowned).status_code == 403
    for task_id in (unowned["task_id"], "audit-only"):
        logger.log_api_call(api_key=user["api_key"], user_id="alice", endpoint="/api/transcribe",
                            task_id=task_id, status_code=200)
    assert remove(client, unowned, {"task_id": "audit-only"}).status_code == 200
    assert client.get("/api/audit/history?status=all").json()["data"]["total"] == 0
    user.update(user_id="legacy_user", api_key="test-legacy-history", is_legacy=True)
    assert client.get("/api/audit/history?status=all").json()["data"]["total"] == 1


def test_empty_unknown_and_unauthenticated_requests(history_app):
    client, manager, _, _ = history_app
    task = create_task(manager)
    assert client.post("/api/audit/history/remove", json={"task_ids": []}).status_code == 422
    assert remove(client, {"task_id": "missing"}).status_code == 403
    client.app.dependency_overrides.clear()
    assert remove(client, task).status_code in (401, 403)
    assert len(manager.list_recent_tasks(owner_user_id="alice")) == 1
