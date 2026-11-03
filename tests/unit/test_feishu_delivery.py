"""Owner isolation, bounded local reads, and safe archive retry requests."""

import json
import sqlite3
import time
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from video_transcript_api.api.routes import delivery
from video_transcript_api.api.services.transcription import verify_token
from video_transcript_api.exports.feishu import ArchiveWorker


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = {"enabled": True, "state_db": str(tmp_path / "archive.db"),
              "parent_node_token": "parent", "api_user_name": "Archive owner"}
    job = ArchiveWorker(config, source=Mock(), cli=Mock())
    job.db.execute("""INSERT INTO exports
        (source_key,task_id,status,document_url,attempts,next_retry,last_error,updated_at)
        VALUES(?,?,?,?,?,?,?,?)""", ("parent:view", "task", "verifying",
        "https://my.feishu.cn/docx/example", 12, time.time() + 3600,
        "Document readback differs from complete source content", time.time()))
    job.db.commit()
    task = {"task_id": "task", "view_token": "view", "status": "success", "owner_user_id": "owner"}
    manager = Mock()
    manager.list_all_users.return_value = [{"user_id": "owner", "name": "Archive owner", "enabled": True}]
    cache = Mock()
    cache.get_task_by_id.return_value = task
    monkeypatch.setattr(delivery, "get_cache_manager", lambda: cache)
    monkeypatch.setattr(delivery, "get_user_manager", lambda: manager)
    monkeypatch.setattr(delivery, "load_archive_config", lambda: config)
    user = {"user_id": "owner", "api_key": "test-key"}
    app = FastAPI()
    app.include_router(delivery.router)

    async def current_user():
        return user

    app.dependency_overrides[verify_token] = current_user
    with TestClient(app) as client:
        yield client, job, task, user, config
    job.db.close()


def test_status_describes_readback_failure_without_leaking_body_or_paths(setup):
    client, _, _, _, config = setup
    response = client.get("/api/tasks/task/delivery/feishu")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "needs_attention" and data["can_retry"] is True
    assert data["document_url"].startswith("https://my.feishu.cn/")
    assert data["updated_at"].endswith("+00:00")
    body = response.text
    assert config["state_db"] not in body
    assert "Document readback differs" not in body


def test_retry_resets_backoff_without_resetting_uncertain_creation(setup):
    client, job, *_ = setup
    job.db.execute("UPDATE exports SET status='uncertain'")
    job.db.commit()
    assert client.post("/api/tasks/task/delivery/feishu/retry").status_code == 200
    row = job.db.execute("SELECT status,next_retry FROM exports").fetchone()
    assert tuple(row) == ("uncertain", 0)


def test_cross_owner_cannot_read_or_retry_archive(setup):
    client, job, _, user, _ = setup
    user["user_id"] = "someone-else"
    before = tuple(job.db.execute("SELECT status,next_retry FROM exports").fetchone())
    for method, suffix in (("get", ""), ("post", "/retry")):
        assert getattr(client, method)("/api/tasks/task/delivery/feishu" + suffix).status_code == 403
    assert tuple(job.db.execute("SELECT status,next_retry FROM exports").fetchone()) == before


def test_archive_is_hidden_for_different_configured_identity(setup):
    client, _, _, _, config = setup
    config["api_user_name"] = "Other identity"
    assert client.get("/api/tasks/task/delivery/feishu").json()["data"]["state"] == "unavailable"


def test_retry_does_not_discard_remote_edit_conflict_or_reopen_success(setup):
    client, job, *_ = setup
    for status in ("done", "conflict"):
        job.db.execute("UPDATE exports SET status=?,next_retry=42", (status,))
        job.db.commit()
        client.post("/api/tasks/task/delivery/feishu/retry")
        assert tuple(job.db.execute("SELECT status,next_retry FROM exports").fetchone()) == (status, 42)


def test_interrupted_update_is_visible_and_retry_only_rechecks_the_same_document(setup):
    client, job, *_ = setup
    job.db.execute("UPDATE exports SET status='updating',last_error='Update timed out'")
    job.db.commit()
    data = client.get("/api/tasks/task/delivery/feishu").json()["data"]
    assert data["state"] == "needs_attention" and data["can_retry"] is True
    client.post("/api/tasks/task/delivery/feishu/retry")
    assert tuple(job.db.execute("SELECT status,next_retry FROM exports").fetchone()) == ("updating", 0)


def test_status_request_does_not_create_missing_database(setup):
    client, _, _, _, config = setup
    from pathlib import Path

    path = Path(config["state_db"]).with_name("absent.db")
    config["state_db"] = str(path)
    assert client.get("/api/tasks/task/delivery/feishu").json()["data"]["state"] == "pending"
    assert not path.exists()


def test_config_path_can_be_selected_without_committing_private_settings(tmp_path, monkeypatch):
    from video_transcript_api.exports.delivery import load_archive_config

    path = tmp_path / "config.json"
    monkeypatch.setenv("LEARNFLUX_FEISHU_ARCHIVE_CONFIG", str(path))
    assert load_archive_config() is None
    path.write_text(json.dumps({"enabled": True, "state_db": "private"}))
    assert load_archive_config()["state_db"] == "private"
