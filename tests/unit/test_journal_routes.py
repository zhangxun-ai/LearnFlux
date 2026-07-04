from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _fake_verify_token():
    return {"user_id": "test-user", "api_key": "sk-test"}


def _build_app():
    from video_transcript_api.api.routes import journal
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(journal.router)
    app.dependency_overrides[verify_token] = _fake_verify_token
    return app


def test_get_journal_entry(monkeypatch):
    from video_transcript_api.api.routes import journal

    service = MagicMock()
    service.get_entry.return_value = {
        "entry_date": "2026-07-02",
        "entry_type": "daily",
        "body": "今天记录",
    }
    monkeypatch.setattr(journal, "get_journal_service", lambda: service)

    client = TestClient(_build_app())
    response = client.get("/api/journal/entry?entry_date=2026-07-02&entry_type=daily")

    assert response.status_code == 200
    assert response.json()["data"]["body"] == "今天记录"
    service.get_entry.assert_called_once_with("test-user", "2026-07-02", "daily")


def test_save_journal_entry(monkeypatch):
    from video_transcript_api.api.routes import journal

    service = MagicMock()
    service.save_entry.return_value = {
        "entry_date": "2026-07-02",
        "entry_type": "daily",
        "title": "今天记录",
        "body": "正文",
    }
    monkeypatch.setattr(journal, "get_journal_service", lambda: service)

    client = TestClient(_build_app())
    response = client.post(
        "/api/journal/entries",
        json={
            "entry_date": "2026-07-02",
            "entry_type": "daily",
            "title": "今天记录",
            "body": "正文",
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "记录已保存"
    service.save_entry.assert_called_once_with(
        user_id="test-user",
        entry_date="2026-07-02",
        entry_type="daily",
        title="今天记录",
        body="正文",
    )


def test_list_journal_entries(monkeypatch):
    from video_transcript_api.api.routes import journal

    service = MagicMock()
    service.list_entries.return_value = [{"title": "本月记录"}]
    monkeypatch.setattr(journal, "get_journal_service", lambda: service)

    client = TestClient(_build_app())
    response = client.get("/api/journal/entries?month=2026-07")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["title"] == "本月记录"
    service.list_entries.assert_called_once_with(
        user_id="test-user",
        month="2026-07",
        start_date=None,
        end_date=None,
        entry_type=None,
        limit=60,
    )


def test_create_journal_review(monkeypatch):
    from video_transcript_api.api.routes import journal

    service = MagicMock()
    service.review.return_value = {
        "answer": "保留每日记录。",
        "model": "deepseek-v4-pro",
        "reasoning_effort": "high",
    }

    async def fake_run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(journal, "get_journal_service", lambda: service)
    monkeypatch.setattr(journal, "run_in_threadpool", fake_run_in_threadpool)

    client = TestClient(_build_app())
    response = client.post(
        "/api/journal/reviews",
        json={
            "range_start": "2026-07-01",
            "range_end": "2026-07-07",
            "question": "哪些动作应该保留？",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["answer"] == "保留每日记录。"
    service.review.assert_called_once_with(
        "test-user",
        "2026-07-01",
        "2026-07-07",
        "哪些动作应该保留？",
    )
