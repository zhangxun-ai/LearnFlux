"""
History route tests.

Covers:
- GET /api/audit/history  : filter combos, pagination, empty, cross-DB JOIN, DB locked
- GET /api/audit/filter-options : distinct webhook/platform/author per API key
- GET /api/audit/summary  : happy path, 404, 202 (processing), 403 (cross-user)

Strategy: real SQLite temp DBs (not mocks) so ATTACH JOIN actually runs.
Module-level singletons are patched to point at the temp files.

All console output must be in English only (no emoji, no Chinese).
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.utils.logging.audit_logger import AuditLogger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_KEY      = "sk-test-key-123456"
_API_KEY_MASK = "sk-t**********3456"   # len=18, first4="sk-t", last4="3456"
_WEBHOOK_A    = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aaa"
_WEBHOOK_B    = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bbb"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_pair(tmp_path):
    """
    Create a real audit.db + cache.db pair in a temp directory.

    Returns a dict with:
      - audit_logger: real AuditLogger instance
      - cache_db_path: str path to the cache SQLite file
      - insert_task: helper to insert a row in task_status
    """
    audit_db_path = str(tmp_path / "audit.db")
    cache_db_path = str(tmp_path / "cache.db")

    # Real AuditLogger (runs migrations, creates api_audit_logs)
    al = AuditLogger(db_path=audit_db_path)

    # Minimal cache.db matching production task_status schema
    conn = sqlite3.connect(cache_db_path)
    conn.execute('''
        CREATE TABLE task_status (
            task_id    TEXT PRIMARY KEY,
            view_token TEXT NOT NULL,
            url        TEXT,
            platform   TEXT,
            media_id   TEXT,
            use_speaker_recognition INTEGER DEFAULT 0,
            status     TEXT NOT NULL DEFAULT 'queued',
            title      TEXT,
            author     TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            cache_id   TEXT,
            llm_config TEXT,
            download_url TEXT,
            source_file_path TEXT,
            owner_user_id TEXT,
            error_message TEXT
        )
    ''')
    conn.commit()
    conn.close()

    def insert_task(task_id, view_token, platform="youtube", title="Test Title",
                    author="Test Author", status="success", source_file_path=None, url=None,
                    owner_user_id=None, error_message=None, created_at=None):
        c = sqlite3.connect(cache_db_path)
        c.execute(
            "INSERT OR IGNORE INTO task_status "
            "(task_id, view_token, url, platform, title, author, status, source_file_path, "
            "owner_user_id, error_message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
            (task_id, view_token, url, platform, title, author, status, source_file_path,
             owner_user_id, error_message, created_at),
        )
        c.commit()
        c.close()

    return {
        "audit_logger": al,
        "cache_db_path": cache_db_path,
        "insert_task": insert_task,
    }


@pytest.fixture()
def history_client(db_pair):
    """
    Build a TestClient with /api/audit/* routes, backed by real temp DBs.
    Patches:
      - audit.audit_logger  -> real AuditLogger (temp DB)
      - audit.get_cache_manager -> mock whose .db_path = temp cache.db
    """
    al = db_pair["audit_logger"]

    mock_cache = MagicMock()
    mock_cache.db_path = Path(db_pair["cache_db_path"])

    async def _fake_verify_token():
        return {"user_id": "test-user", "api_key": _API_KEY, "wechat_webhook": None}

    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.api.routes import audit

    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[verify_token] = _fake_verify_token

    with patch("video_transcript_api.api.routes.audit.audit_logger", al), \
         patch("video_transcript_api.api.routes.audit.get_cache_manager", return_value=mock_cache):
        yield TestClient(app), db_pair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(al, task_id, webhook=_WEBHOOK_A, status_code=202,
         video_url="https://youtube.com/watch?v=abc"):
    """Insert one audit row using the real AuditLogger."""
    al.log_api_call(
        api_key=_API_KEY,
        user_id="test-user",
        endpoint="/api/transcribe",
        video_url=video_url,
        status_code=status_code,
        task_id=task_id,
        wechat_webhook=webhook,
    )


# ===========================================================================
# GET /api/audit/history
# ===========================================================================

class TestHistoryEndpoint:
    """Tests for GET /api/audit/history."""

    def test_empty_history_returns_empty_list(self, history_client):
        """No records -> 200 with empty items list."""
        client, _ = history_client
        resp = client.get("/api/audit/history")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    def test_content_type_filter_groups_posts_and_local_documents(self, history_client):
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "post-task", video_url="https://x.com/author/status/123")
        insert("post-task", "post-vt", platform="twitter", title="X post")
        _log(al, "file-task", video_url="local://reading-notes.pdf")
        insert(
            "file-task", "file-vt", platform="local", title="reading-notes.pdf",
            source_file_path="/tmp/reading-notes.pdf",
        )
        _log(al, "video-task")
        insert("video-task", "video-vt", platform="youtube", title="Lesson")

        posts = client.get("/api/audit/history?content_type=post").json()["data"]
        files = client.get("/api/audit/history?content_type=file").json()["data"]
        videos = client.get("/api/audit/history?content_type=video").json()["data"]

        assert [item["task_id"] for item in posts["items"]] == ["post-task"]
        assert posts["items"][0]["content_type"] == "post"
        assert [item["task_id"] for item in files["items"]] == ["file-task"]
        assert files["items"][0]["content_type"] == "file"
        assert [item["task_id"] for item in videos["items"]] == ["video-task"]

    def test_rejects_unknown_content_type(self, history_client):
        client, _ = history_client
        assert client.get("/api/audit/history?content_type=unknown").status_code == 422

    def test_returns_completed_by_default(self, history_client):
        """Default status filter returns only completed tasks (LEFT JOIN match)."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "task-done")
        _log(al, "task-proc")
        insert("task-done", "vt-done", status="success")
        insert("task-proc", "vt-proc", status="processing")

        resp = client.get("/api/audit/history")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        task_ids = {i["task_id"] for i in items}
        assert "task-done" in task_ids
        assert "task-proc" not in task_ids

    def test_status_all_returns_every_record(self, history_client):
        """status=all should bypass the default completed filter."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "task-done")
        _log(al, "task-proc")
        insert("task-done", "vt-done", status="success")
        insert("task-proc", "vt-proc", status="processing")

        resp = client.get("/api/audit/history?status=all")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "task-done" in task_ids
        assert "task-proc" in task_ids

    def test_filter_by_webhook(self, history_client):
        """webhook filter should return only matching rows."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "ta", webhook=_WEBHOOK_A)
        _log(al, "tb", webhook=_WEBHOOK_B)
        insert("ta", "vt-a"); insert("tb", "vt-b")

        resp = client.get(f"/api/audit/history?webhook={_WEBHOOK_A}")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["task_id"] == "ta"

    def test_filter_by_platform(self, history_client):
        """platform filter joins cache.db and returns matching rows only."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "yt-task"); _log(al, "bili-task")
        insert("yt-task", "vt-yt", platform="youtube")
        insert("bili-task", "vt-bili", platform="bilibili")

        resp = client.get("/api/audit/history?platform=youtube")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert all(i["platform"] == "youtube" for i in items)
        task_ids = {i["task_id"] for i in items}
        assert "bili-task" not in task_ids

    def test_filter_by_author(self, history_client):
        """author filter returns only tasks from that channel."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "t1"); _log(al, "t2")
        insert("t1", "vt1", author="Channel A")
        insert("t2", "vt2", author="Channel B")

        resp = client.get("/api/audit/history?author=Channel+A")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["author"] == "Channel A"

    def test_filter_by_multiple_authors(self, history_client):
        """author=A,B (comma-separated) returns tasks from both channels."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "t1"); _log(al, "t2"); _log(al, "t3")
        insert("t1", "vt1", author="Channel A")
        insert("t2", "vt2", author="Channel B")
        insert("t3", "vt3", author="Channel C")

        resp = client.get("/api/audit/history?author=Channel+A,Channel+B")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        authors = {i["author"] for i in items}
        assert authors == {"Channel A", "Channel B"}
        assert resp.json()["data"]["total"] == 2

    def test_filter_by_single_author_still_works(self, history_client):
        """Single author (no comma) still works as exact match."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "t1"); _log(al, "t2")
        insert("t1", "vt1", author="Only This")
        insert("t2", "vt2", author="Not This")

        resp = client.get("/api/audit/history?author=Only+This")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1
        assert resp.json()["data"]["items"][0]["author"] == "Only This"

    def test_filter_by_date_range(self, history_client):
        """start_date and end_date filter by request_time."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        # Insert records at specific times via direct SQL
        conn = sqlite3.connect(al.db_path)
        conn.execute(
            "INSERT INTO api_audit_logs "
            "(api_key_masked, user_id, endpoint, task_id, wechat_webhook, request_time, status_code)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_API_KEY_MASK, "test-user", "/api/transcribe", "old-task",
             _WEBHOOK_A, "2023-01-01 10:00:00", 202),
        )
        conn.execute(
            "INSERT INTO api_audit_logs "
            "(api_key_masked, user_id, endpoint, task_id, wechat_webhook, request_time, status_code)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_API_KEY_MASK, "test-user", "/api/transcribe", "new-task",
             _WEBHOOK_A, "2025-06-15 10:00:00", 202),
        )
        conn.commit()
        conn.close()
        insert("old-task", "vt-old", created_at="2023-01-01 10:00:00")
        insert("new-task", "vt-new", created_at="2025-06-15 10:00:00")

        resp = client.get("/api/audit/history?start_date=2025-01-01&end_date=2025-12-31")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "new-task" in task_ids
        assert "old-task" not in task_ids

    def test_pagination_limit_and_offset(self, history_client):
        """limit and offset should correctly slice results."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        for i in range(5):
            _log(al, f"task-{i}")
            insert(f"task-{i}", f"vt-{i}")

        resp = client.get("/api/audit/history?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["items"]) == 2
        assert data["total"] == 5

        resp2 = client.get("/api/audit/history?limit=2&offset=4")
        assert resp2.status_code == 200
        assert len(resp2.json()["data"]["items"]) == 1

    def test_total_reflects_filtered_count(self, history_client):
        """total should be the filtered count, not the overall table count."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "ta", webhook=_WEBHOOK_A)
        _log(al, "tb", webhook=_WEBHOOK_A)
        _log(al, "tc", webhook=_WEBHOOK_B)
        insert("ta", "vt-a"); insert("tb", "vt-b"); insert("tc", "vt-c")

        resp = client.get(f"/api/audit/history?webhook={_WEBHOOK_A}")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 2

    def test_left_join_null_task_included_when_status_all(self, history_client):
        """Audit rows with no matching task_status (no cache record) still appear with status=all."""
        client, setup = history_client
        al = setup["audit_logger"]

        # Insert audit row but no matching cache row
        _log(al, "orphan-task")

        resp = client.get("/api/audit/history?status=all")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "orphan-task" in task_ids

    def test_response_includes_view_token_and_title(self, history_client):
        """Items should carry view_token and title from the cache JOIN."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "task-vt")
        insert("task-vt", "my-view-token-abc", title="My Video Title")

        resp = client.get("/api/audit/history")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["data"]["items"] if i["task_id"] == "task-vt")
        assert item["view_token"] == "my-view-token-abc"
        assert item["title"] == "My Video Title"

    def test_history_marks_retained_media_as_available_for_study(self, history_client, tmp_path):
        client, setup = history_client
        source = tmp_path / "lesson.mp4"
        source.write_bytes(b"video")
        _log(setup["audit_logger"], "task-study")
        setup["insert_task"](
            "task-study",
            "view-study",
            title="Lesson.mp4",
            source_file_path=str(source),
        )

        response = client.get("/api/audit/history")

        assert response.status_code == 200
        item = next(
            value
            for value in response.json()["data"]["items"]
            if value["task_id"] == "task-study"
        )
        assert item["study_available"] is True
        assert item["study_url"] == "/study/view-study"

    def test_history_deduplicates_task_audit_rows_and_formats_local_time(self, history_client):
        """Multiple audit rows for one task should display as one local-time history item."""
        client, setup = history_client
        al = setup["audit_logger"]
        cache_db_path = setup["cache_db_path"]

        conn = sqlite3.connect(al.db_path)
        rows = [
            (None, "http://xhslink.com/o/5D5gM73GKqp", "2026-06-30 13:24:52", None),
            ("task-xhs", "http://xhslink.com/o/5D5gM73GKqp", "2026-06-30 13:24:53", 202),
            ("task-xhs", None, "2026-06-30 13:24:53", 202),
            ("task-xhs", None, "2026-06-30 13:28:14", 200),
        ]
        for task_id, video_url, request_time, status_code in rows:
            conn.execute(
                "INSERT INTO api_audit_logs "
                "(api_key_masked, user_id, endpoint, task_id, video_url, request_time, status_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_API_KEY_MASK, "test-user", "/api/transcribe", task_id, video_url, request_time, status_code),
            )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(cache_db_path)
        conn.execute(
            "INSERT INTO task_status "
            "(task_id, view_token, url, platform, media_id, status, title, author, created_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "task-xhs",
                "view-xhs",
                "http://xhslink.com/o/5D5gM73GKqp",
                "xiaohongshu",
                "6a2fd6d1000000001702f4b6",
                "success",
                "分享一个做好决策的方法",
                "加肯",
                "2026-06-30 13:24:53",
                "2026-06-30 13:26:57",
            ),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/audit/history")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["task_id"] == "task-xhs"
        assert item["video_url"] == "http://xhslink.com/o/5D5gM73GKqp"
        assert item["request_time"] == "2026-06-30 13:24:53"
        assert item["request_time_display"] == "2026-06-30 21:24"

    def test_api_key_masked_in_response(self, history_client):
        """Response data should include api_key_masked for localStorage key construction."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "task-x")
        insert("task-x", "vt-x")

        resp = client.get("/api/audit/history")
        assert resp.status_code == 200
        assert resp.json()["data"]["api_key_masked"] == _API_KEY_MASK

    def test_different_api_key_sees_no_records(self, history_client):
        """Records belonging to one API key should not be visible to another."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        # Insert record with a DIFFERENT key
        al.log_api_call(
            api_key="other-key-9999",
            user_id="other-user",
            endpoint="/api/transcribe",
            task_id="other-task",
        )
        insert("other-task", "vt-other")

        resp = client.get("/api/audit/history?status=all")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "other-task" not in task_ids


# ===========================================================================
# GET /api/audit/history — search (q parameter)
# ===========================================================================

class TestHistorySearch:
    """Tests for full-text search via ?q= parameter in /api/audit/history."""

    def test_search_by_title_returns_match(self, history_client):
        """q matching part of a title returns that task."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "task-a"); _log(al, "task-b")
        insert("task-a", "vt-a", title="Python 编程实战")
        insert("task-b", "vt-b", title="JavaScript 入门教程")

        resp = client.get("/api/audit/history?q=Python")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        task_ids = {i["task_id"] for i in items}
        assert "task-a" in task_ids
        assert "task-b" not in task_ids

    def test_search_by_author_returns_match(self, history_client):
        """q matching part of author/channel name returns that task."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "ta"); _log(al, "tb")
        insert("ta", "vt-a", author="技术蛋老师")
        insert("tb", "vt-b", author="李永乐老师")

        resp = client.get("/api/audit/history?q=技术蛋")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "ta" in task_ids
        assert "tb" not in task_ids

    def test_search_by_video_url_returns_match(self, history_client):
        """q matching part of video_url returns that task."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        # Insert audit record with specific URL
        al.log_api_call(
            api_key=_API_KEY, user_id="test-user", endpoint="/api/transcribe",
            video_url="https://youtu.be/abc123xyz", status_code=202, task_id="task-url",
            wechat_webhook=_WEBHOOK_A,
        )
        al.log_api_call(
            api_key=_API_KEY, user_id="test-user", endpoint="/api/transcribe",
            video_url="https://bilibili.com/video/BV999", status_code=202, task_id="task-other-url",
            wechat_webhook=_WEBHOOK_A,
        )
        insert("task-url", "vt-url"); insert("task-other-url", "vt-other-url")

        resp = client.get("/api/audit/history?q=abc123xyz")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "task-url" in task_ids
        assert "task-other-url" not in task_ids

    def test_search_no_match_returns_empty(self, history_client):
        """q that matches nothing returns empty list and total=0."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "task-x")
        insert("task-x", "vt-x", title="机器学习入门")

        resp = client.get("/api/audit/history?q=不存在的关键词xyz")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    def test_search_empty_q_returns_all(self, history_client):
        """q='' (empty string) behaves same as no q — returns all records."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "t1"); _log(al, "t2")
        insert("t1", "vt1"); insert("t2", "vt2")

        resp = client.get("/api/audit/history?q=")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 2

    def test_search_combined_with_platform_filter(self, history_client):
        """q + platform together narrow results correctly."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "yt"); _log(al, "bili")
        insert("yt",   "vt-yt",   title="AI 教程", platform="youtube")
        insert("bili", "vt-bili", title="AI 入门",  platform="bilibili")

        resp = client.get("/api/audit/history?q=AI&platform=youtube")
        assert resp.status_code == 200
        task_ids = {i["task_id"] for i in resp.json()["data"]["items"]}
        assert "yt" in task_ids
        assert "bili" not in task_ids

    def test_large_limit_for_client_side_filtering(self, history_client):
        """limit=10000 should be accepted (needed when client applies read filter)."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        _log(al, "t1"); insert("t1", "vt1")

        resp = client.get("/api/audit/history?limit=10000")
        assert resp.status_code == 200
        assert resp.json()["data"]["limit"] == 10000

    def test_search_total_reflects_filtered_count(self, history_client):
        """total in response equals the number of records matching q."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        for i in range(3):
            _log(al, f"match-{i}")
            insert(f"match-{i}", f"vt-m{i}", title="深度学习")
        _log(al, "nomatch")
        insert("nomatch", "vt-nm", title="其他内容")

        resp = client.get("/api/audit/history?q=深度学习")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 3


# ===========================================================================
# GET /api/audit/filter-options
# ===========================================================================

class TestFilterOptionsEndpoint:
    """Tests for GET /api/audit/filter-options."""

    def test_empty_db_returns_empty_lists(self, history_client):
        """No audit records -> all filter options are empty lists."""
        client, _ = history_client
        resp = client.get("/api/audit/filter-options")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["webhooks"] == []
        assert data["platforms"] == []
        assert data["authors"] == []

    def test_returns_distinct_webhooks(self, history_client):
        """Repeated webhook calls should appear only once."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        for i in range(3):
            _log(al, f"t{i}", webhook=_WEBHOOK_A)
        _log(al, "t3", webhook=_WEBHOOK_B)
        for i in range(4):
            insert(f"t{i}", f"vt{i}")

        resp = client.get("/api/audit/filter-options")
        assert resp.status_code == 200
        webhooks = resp.json()["data"]["webhooks"]
        assert len(webhooks) == 2
        assert _WEBHOOK_A in webhooks
        assert _WEBHOOK_B in webhooks

    def test_returns_distinct_platforms(self, history_client):
        """Platforms are deduplicated from the cache JOIN."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        for i, plat in enumerate(["youtube", "youtube", "bilibili"]):
            _log(al, f"tp{i}")
            insert(f"tp{i}", f"vtp{i}", platform=plat)

        resp = client.get("/api/audit/filter-options")
        assert resp.status_code == 200
        platforms = resp.json()["data"]["platforms"]
        assert set(platforms) == {"youtube", "bilibili"}
        counts = {item["platform"]: item["count"] for item in resp.json()["data"]["platform_counts"]}
        assert counts == {"youtube": 2, "bilibili": 1}

    def test_platform_options_include_legacy_url_join(self, history_client):
        client, setup = history_client
        al = setup["audit_logger"]
        source_url = "https://bilibili.com/video/BV123"
        al.log_api_call(
            api_key=_API_KEY,
            user_id="test-user",
            endpoint="/api/transcribe",
            video_url=source_url,
            status_code=202,
            task_id=None,
        )
        setup["insert_task"](
            "legacy-url-task", "legacy-url-vt", platform="bilibili",
            title="Legacy URL task", url=source_url,
        )

        options = client.get("/api/audit/filter-options").json()["data"]
        history = client.get("/api/audit/history?platform=bilibili").json()["data"]

        assert options["platforms"] == ["bilibili"]
        assert options["platform_counts"] == [{"platform": "bilibili", "count": 1}]
        assert [item["task_id"] for item in history["items"]] == ["legacy-url-task"]

    def test_returns_distinct_authors(self, history_client):
        """Authors are deduplicated, ordered by frequency."""
        client, setup = history_client
        al = setup["audit_logger"]
        insert = setup["insert_task"]

        for i, author in enumerate(["Chan A", "Chan A", "Chan B"]):
            _log(al, f"ta{i}")
            insert(f"ta{i}", f"vta{i}", author=author)

        resp = client.get("/api/audit/filter-options")
        assert resp.status_code == 200
        authors = resp.json()["data"]["authors"]
        # Chan A appears twice so should come first
        assert authors[0] == "Chan A"
        assert "Chan B" in authors

    def test_webhooks_isolated_per_api_key(self, history_client):
        """Webhooks from another API key must not appear in filter-options."""
        client, setup = history_client
        al = setup["audit_logger"]

        al.log_api_call(
            api_key="other-key-9999",
            user_id="other",
            endpoint="/api/transcribe",
            wechat_webhook="https://other-webhook.example.com",
        )

        resp = client.get("/api/audit/filter-options")
        assert resp.status_code == 200
        assert "https://other-webhook.example.com" not in resp.json()["data"]["webhooks"]


# ===========================================================================
# GET /api/audit/summary
# ===========================================================================


@pytest.fixture()
def summary_setup(db_pair):
    """
    Fixture for summary endpoint tests.

    Yields (client, db_pair, mock_cache) with patches active for the entire test.
    Tests configure mock_cache return values before calling client.get().
    """
    al = db_pair["audit_logger"]

    mock_cache = MagicMock()
    mock_cache.db_path = Path(db_pair["cache_db_path"])

    async def _fake_verify_token():
        return {"user_id": "test-user", "api_key": _API_KEY, "wechat_webhook": None}

    from video_transcript_api.api.services.transcription import verify_token
    from video_transcript_api.api.routes import audit

    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[verify_token] = _fake_verify_token

    # Keep patches active for the lifetime of the test (yield, not return)
    with patch("video_transcript_api.api.routes.audit.audit_logger", al), \
         patch("video_transcript_api.api.routes.audit.get_cache_manager", return_value=mock_cache):
        yield TestClient(app), db_pair, mock_cache


class TestSummaryEndpoint:
    """Tests for GET /api/audit/summary."""

    def test_returns_summary_for_completed_task(self, summary_setup):
        """Happy path: completed task with summary returns 200 and preview text (max 300 chars)."""
        client, db_pair, mock_cache = summary_setup
        al = db_pair["audit_logger"]
        _log(al, "task-sum")   # audit record lets auth pass

        long_summary = "A" * 500
        mock_cache.get_task_by_view_token.return_value = {"task_id": "task-sum", "status": "success"}
        mock_cache.get_view_data_by_token.return_value = {"status": "success", "summary": long_summary}

        resp = client.get("/api/audit/summary?view_token=vt-sum")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "success"
        assert len(data["summary"]) == 300
        assert data["summary"] == long_summary[:300]

    def test_returns_202_for_processing_task(self, summary_setup):
        """A task still processing returns code=202 with empty summary."""
        client, setup, mock_cache = summary_setup
        _log(setup["audit_logger"], "task-proc")
        mock_cache.get_task_by_view_token.return_value = {"task_id": "task-proc", "status": "processing"}

        resp = client.get("/api/audit/summary?view_token=vt-proc")
        assert resp.status_code == 200
        assert resp.json()["code"] == 202
        assert resp.json()["data"]["summary"] == ""

    def test_returns_404_for_unknown_view_token(self, summary_setup):
        """Unknown view_token returns 404."""
        client, _, mock_cache = summary_setup
        mock_cache.get_task_by_view_token.return_value = None

        resp = client.get("/api/audit/summary?view_token=does-not-exist")
        assert resp.status_code == 404

    def test_returns_403_for_cross_user_access(self, summary_setup):
        """A task belonging to a different API key returns 403."""
        client, db_pair, mock_cache = summary_setup
        al = db_pair["audit_logger"]

        # Audit record under a DIFFERENT API key (not _API_KEY)
        al.log_api_call(
            api_key="other-key-9999",
            user_id="other-user",
            endpoint="/api/transcribe",
            task_id="task-other",
        )

        mock_cache.get_task_by_view_token.return_value = {"task_id": "task-other", "status": "success"}
        mock_cache.get_view_data_by_token.return_value = {"status": "success", "summary": "secret"}

        resp = client.get("/api/audit/summary?view_token=vt-other")
        assert resp.status_code == 403

    def test_empty_summary_returns_empty_string(self, summary_setup):
        """Completed task with empty summary text returns 200 with empty string."""
        client, db_pair, mock_cache = summary_setup
        al = db_pair["audit_logger"]
        _log(al, "task-nosumm")

        mock_cache.get_task_by_view_token.return_value = {"task_id": "task-nosumm", "status": "success"}
        mock_cache.get_view_data_by_token.return_value = {"status": "success", "summary": ""}

        resp = client.get("/api/audit/summary?view_token=vt-ns")
        assert resp.status_code == 200
        assert resp.json()["data"]["summary"] == ""

    def test_summary_missing_key_returns_empty_string(self, summary_setup):
        """view_data without 'summary' key degrades gracefully to empty string."""
        client, db_pair, mock_cache = summary_setup
        al = db_pair["audit_logger"]
        _log(al, "task-nokey")

        mock_cache.get_task_by_view_token.return_value = {"task_id": "task-nokey", "status": "success"}
        mock_cache.get_view_data_by_token.return_value = {"status": "success"}  # no 'summary' key

        resp = client.get("/api/audit/summary?view_token=vt-nk")
        assert resp.status_code == 200
        assert resp.json()["data"]["summary"] == ""


class TestDurableHistoryScope:
    """History and metadata share durable ownership and deduplication rules."""

    def test_owned_task_without_audit_is_visible_with_failure_details(self, history_client):
        client, setup = history_client
        setup["insert_task"](
            "owned-no-audit", "owned-view", owner_user_id="test-user",
            status="failed", title="Retained lesson", error_message="Download unavailable",
        )
        data = client.get("/api/audit/history?status=all").json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["view_token"] == "owned-view"
        assert data["items"][0]["error"] == "Download unavailable"

    def test_explicit_other_owner_overrides_current_key_audit(self, history_client):
        client, setup = history_client
        _log(setup["audit_logger"], "other-owned")
        setup["insert_task"]("other-owned", "other-view", owner_user_id="other-user")
        assert client.get("/api/audit/history?status=all").json()["data"]["total"] == 0
        assert client.get("/api/audit/filter-options").json()["data"]["total"] == 0

    def test_regular_user_does_not_inherit_unowned_task_without_audit(self, history_client):
        client, setup = history_client
        setup["insert_task"]("unowned", "unowned-view")
        assert client.get("/api/audit/history?status=all").json()["data"]["total"] == 0

    def test_legacy_scope_includes_unowned_but_not_other_owner(self, history_client):
        from video_transcript_api.api.services.transcription import verify_token
        client, setup = history_client

        async def legacy_user():
            return {"user_id": "legacy_user", "api_key": _API_KEY, "is_legacy": True}

        client.app.dependency_overrides[verify_token] = legacy_user
        setup["insert_task"]("legacy", "legacy-view")
        setup["insert_task"]("owned-other", "other-view", owner_user_id="other-user")
        data = client.get("/api/audit/history?status=all").json()["data"]
        assert [row["task_id"] for row in data["items"]] == ["legacy"]

    def test_metadata_counts_deduplicated_views_and_unknown_audit_rows(self, history_client):
        client, setup = history_client
        insert = setup["insert_task"]
        insert("old", "shared-view", platform="youtube", owner_user_id="test-user",
               created_at="2026-10-01 10:00:00")
        insert("latest", "shared-view", platform="bilibili", owner_user_id="test-user",
               created_at="2026-10-02 10:00:00")
        _log(setup["audit_logger"], "audit-only")
        history = client.get("/api/audit/history?status=all").json()["data"]
        metadata = client.get("/api/audit/filter-options").json()["data"]
        assert history["total"] == metadata["total"] == 2
        assert sum(item["count"] for item in metadata["platform_counts"]) == 2
        assert metadata["platform_counts"] == [
            {"platform": "bilibili", "count": 1}, {"platform": "generic", "count": 1},
        ]
        assert "old" not in {item["task_id"] for item in history["items"]}

    def test_empty_page_keeps_filtered_total(self, history_client):
        client, setup = history_client
        setup["insert_task"]("owned", "view", owner_user_id="test-user")
        data = client.get("/api/audit/history?offset=100").json()["data"]
        assert data["items"] == []
        assert data["total"] == 1

    def test_date_filter_matches_displayed_import_time(self, history_client):
        client, setup = history_client
        _log(setup["audit_logger"], "old-task")
        setup["insert_task"]("old-task", "view", created_at="2023-01-01 10:00:00")
        data = client.get("/api/audit/history?start_date=2023-01-01&end_date=2023-01-01").json()["data"]
        assert data["total"] == 1
        assert str(data["items"][0]["request_time"]).startswith("2023-01-01")
        assert client.get("/api/audit/history?start_date=invalid").status_code == 422

    def test_processing_filter_includes_queued_and_calibrating(self, history_client):
        client, setup = history_client
        for status in ("queued", "processing", "calibrating", "awaiting_cloud_confirmation"):
            setup["insert_task"](status, "view-" + status,
                                 owner_user_id="test-user", status=status)
        data = client.get("/api/audit/history?status=processing").json()["data"]
        assert {item["status"] for item in data["items"]} == {"queued", "processing", "calibrating"}
        waiting = client.get("/api/audit/history?status=awaiting_cloud_confirmation").json()["data"]
        assert waiting["total"] == 1

    def test_history_reads_do_not_create_marks_tables(self, history_client):
        client, setup = history_client
        setup["insert_task"]("owned", "view", owner_user_id="test-user")
        for endpoint in ("/api/audit/history", "/api/audit/filter-options"):
            assert client.get(endpoint).status_code == 200
        with sqlite3.connect(setup["cache_db_path"]) as conn:
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'content_marks'"
            ).fetchone() is None


def test_postgres_history_uses_one_read_statement_per_endpoint(db_pair, monkeypatch):
    """Exercise the unified-schema branch without a remote database or DDL."""
    from video_transcript_api.api.routes import audit
    from video_transcript_api.api.services.transcription import verify_token
    setup = db_pair
    setup["insert_task"]("owned", "view", owner_user_id="test-user")
    statements = []

    def connect():
        conn = sqlite3.connect(setup["audit_logger"].db_path)
        conn.execute("ATTACH DATABASE ? AS cache", (setup["cache_db_path"],))
        conn.execute("CREATE TEMP VIEW task_status AS SELECT * FROM cache.task_status")
        conn.execute("CREATE TEMP TABLE content_marks (id TEXT, owner_type TEXT, owner_id TEXT, user_key TEXT)")
        conn.set_trace_callback(statements.append)
        return conn

    cache = MagicMock()
    cache._is_postgres = True
    cache.database.connect.side_effect = connect
    monkeypatch.setattr(audit, "audit_logger", setup["audit_logger"])
    monkeypatch.setattr(audit, "get_cache_manager", lambda: cache)
    app = FastAPI()
    app.include_router(audit.router)

    async def user():
        return {"user_id": "test-user", "api_key": _API_KEY}

    app.dependency_overrides[verify_token] = user
    client = TestClient(app)
    history = client.get("/api/audit/history").json()["data"]
    options = client.get("/api/audit/filter-options").json()["data"]
    assert history["total"] == options["total"] == 1
    assert len(statements) == 2
    assert all(statement.lstrip().startswith("WITH owned_audits") for statement in statements)
    assert cache.database.connect.call_count == 2


def test_history_calendar_filter_uses_display_timezone(history_client, monkeypatch):
    from datetime import timezone, timedelta
    from video_transcript_api.api.routes import audit
    monkeypatch.setattr(audit, "get_configured_timezone", lambda: timezone(timedelta(hours=8)))
    client, setup = history_client
    setup["insert_task"]("night", "night-view", owner_user_id="test-user",
                         created_at="2026-10-17 17:30:00")
    day = client.get("/api/audit/history?start_date=2026-10-18&end_date=2026-10-18").json()["data"]
    previous = client.get("/api/audit/history?start_date=2026-10-17&end_date=2026-10-17").json()["data"]
    assert day["total"] == 1
    assert previous["total"] == 0


class TestSummaryDurableOwnership:
    def test_owner_without_audit_can_read_summary(self, summary_setup):
        client, _, cache = summary_setup
        cache.get_task_by_view_token.return_value = {
            "task_id": "owned", "owner_user_id": "test-user", "status": "success",
        }
        cache.get_view_data_by_token.return_value = {"status": "success", "summary": "Owner preview"}
        response = client.get("/api/audit/summary?view_token=owned-view")
        assert response.status_code == 200
        assert response.json()["data"]["summary"] == "Owner preview"

    def test_key_rotation_preserves_owner_access(self, summary_setup):
        client, setup, cache = summary_setup
        setup["audit_logger"].log_api_call(
            api_key="previous-owner-key-9999", user_id="test-user",
            endpoint="/api/transcribe", task_id="rotated",
        )
        cache.get_task_by_view_token.return_value = {
            "task_id": "rotated", "owner_user_id": "test-user", "status": "success",
        }
        cache.get_view_data_by_token.return_value = {"status": "success", "summary": "Rotated key"}
        assert client.get("/api/audit/summary?view_token=rotated-view").status_code == 200

    @pytest.mark.parametrize("has_audit", [False, True])
    def test_explicit_other_owner_cannot_read_even_with_current_key_audit(self, summary_setup, has_audit):
        client, setup, cache = summary_setup
        if has_audit:
            _log(setup["audit_logger"], "other-owned")
        cache.get_task_by_view_token.return_value = {
            "task_id": "other-owned", "owner_user_id": "other-user", "status": "success",
        }
        assert client.get("/api/audit/summary?view_token=other-view").status_code == 403
        cache.get_view_data_by_token.assert_not_called()

    def test_unowned_without_audit_is_not_visible_to_regular_user(self, summary_setup):
        client, _, cache = summary_setup
        cache.get_task_by_view_token.return_value = {"task_id": "unowned", "status": "success"}
        assert client.get("/api/audit/summary?view_token=unowned-view").status_code == 403
        cache.get_view_data_by_token.assert_not_called()

    def test_legacy_user_can_read_unowned_task_without_audit(self, summary_setup):
        from video_transcript_api.api.services.transcription import verify_token
        client, _, cache = summary_setup

        async def legacy():
            return {"user_id": "legacy_user", "api_key": _API_KEY, "is_legacy": True}

        client.app.dependency_overrides[verify_token] = legacy
        cache.get_task_by_view_token.return_value = {"task_id": "unowned", "status": "success"}
        cache.get_view_data_by_token.return_value = {"status": "success", "summary": "Legacy preview"}
        assert client.get("/api/audit/summary?view_token=unowned-view").status_code == 200

    def test_legacy_url_audit_keeps_preview_access(self, summary_setup):
        client, setup, cache = summary_setup
        url = "https://example.com/legacy-upload"
        _log(setup["audit_logger"], None, video_url=url)
        cache.get_task_by_view_token.return_value = {
            "task_id": "legacy-url", "url": url, "status": "success",
        }
        cache.get_view_data_by_token.return_value = {"status": "success", "summary": "URL preview"}
        assert client.get("/api/audit/summary?view_token=legacy-url-view").status_code == 200

    def test_ownership_lookup_failure_does_not_allow_access(self, summary_setup):
        client, setup, cache = summary_setup
        cache.get_task_by_view_token.return_value = {"task_id": "unowned", "status": "success"}
        with patch.object(setup["audit_logger"], "_get_cursor", side_effect=RuntimeError("unavailable")):
            assert client.get("/api/audit/summary?view_token=unowned-view").status_code == 503
        cache.get_view_data_by_token.assert_not_called()
