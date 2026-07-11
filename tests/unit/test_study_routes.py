from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _fake_verify_token():
    return {"user_id": "test-user", "api_key": "sk-test"}


def _build_app():
    from video_transcript_api.api.routes import study
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(study.router)
    app.dependency_overrides[verify_token] = _fake_verify_token
    return app


def test_get_study_session_returns_read_model(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    service.get_session.return_value = {
        "state": "ready",
        "metadata": {"title": "lesson.mp4"},
        "playback": {"source_available": True},
        "transcript": {"lines": []},
        "ai": {"overview": ""},
        "notes": [],
    }
    monkeypatch.setattr(study, "get_study_service", lambda: service)

    client = TestClient(_build_app())
    response = client.get("/api/study/view-123")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["metadata"]["title"] == "lesson.mp4"
    service.get_session.assert_called_once_with("view-123")


def test_get_study_session_returns_404_for_missing_token(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    service.get_session.return_value = None
    monkeypatch.setattr(study, "get_study_service", lambda: service)

    client = TestClient(_build_app())
    response = client.get("/api/study/missing")

    assert response.status_code == 404


def test_create_study_note(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    service.create_note.return_value = {
        "id": "note-1",
        "view_token": "view-123",
        "time_seconds": 8.5,
        "body": "重点",
    }
    monkeypatch.setattr(study, "get_study_service", lambda: service)

    client = TestClient(_build_app())
    response = client.post(
        "/api/study/view-123/notes",
        json={"time_seconds": 8.5, "body": "重点"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == "note-1"
    service.create_note.assert_called_once_with("view-123", 8.5, "重点")


def test_ask_study_ai(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    threadpool_call = {}
    service.ask_ai.return_value = {
        "answer": "这是 AI 回答",
        "model": "deepseek-v4-pro",
        "reasoning_effort": "high",
        "time_seconds": None,
    }

    async def fake_run_in_threadpool(func, *args, **kwargs):
        threadpool_call["func"] = func
        threadpool_call["args"] = args
        return func(*args, **kwargs)

    monkeypatch.setattr(study, "get_study_service", lambda: service)
    monkeypatch.setattr(study, "run_in_threadpool", fake_run_in_threadpool)

    client = TestClient(_build_app())
    response = client.post(
        "/api/study/view-123/ai-chat",
        json={
            "question": "这段视频讲的稳定系统是什么意思？",
            "history": [{"role": "user", "content": "先前问题"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["answer"] == "这是 AI 回答"
    assert body["data"]["model"] == "deepseek-v4-pro"
    assert body["data"]["reasoning_effort"] == "high"
    assert threadpool_call["func"] == service.ask_ai
    service.ask_ai.assert_called_once_with(
        "view-123",
        "这段视频讲的稳定系统是什么意思？",
        None,
        [{"role": "user", "content": "先前问题"}],
    )


def test_study_upload_preserves_source_file(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import study

    cache_manager = MagicMock()
    cache_manager.create_task.return_value = {
        "task_id": "task-1",
        "view_token": "view-1",
    }
    background_calls = []

    def fake_process_local_upload(*args):
        background_calls.append(args)

    monkeypatch.setattr(study, "cache_manager", cache_manager)
    monkeypatch.setattr(study, "process_local_upload", fake_process_local_upload)
    monkeypatch.setattr(study, "get_source_root", lambda: tmp_path / "sources")

    client = TestClient(_build_app())
    response = client.post(
        "/api/study/upload",
        files={"file": ("lesson.mp4", b"fake-video", "video/mp4")},
    )

    assert response.status_code == 202
    assert response.json()["data"]["view_token"] == "view-1"
    assert cache_manager.create_task.call_args.kwargs["url"].startswith("local://study-source/")
    assert background_calls
    assert background_calls[0][-3:-1] == (True, True)
    assert background_calls[0][-1] is False


def test_study_upload_only_enables_fast_path_when_explicit(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import study

    cache_manager = MagicMock()
    cache_manager.create_task.side_effect = [
        {"task_id": "task-1", "view_token": "view-1"},
        {"task_id": "task-2", "view_token": "view-2"},
    ]
    background_calls = []
    monkeypatch.setattr(study, "cache_manager", cache_manager)
    monkeypatch.setattr(
        study, "process_local_upload", lambda *args: background_calls.append(args)
    )
    monkeypatch.setattr(study, "get_source_root", lambda: tmp_path / "sources")
    client = TestClient(_build_app())

    legacy = client.post(
        "/api/study/upload",
        files={"file": ("legacy.pdf", b"pdf", "application/pdf")},
    )
    visual = client.post(
        "/api/study/upload",
        data={"visual_fast_path": "true"},
        files={"file": ("visual.pdf", b"pdf", "application/pdf")},
    )

    assert legacy.status_code == 202
    assert visual.status_code == 202
    assert background_calls[0][-1] is False
    assert background_calls[1][-1] is True


def test_study_text_creates_controlled_markdown_source(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import study

    cache_manager = MagicMock()
    cache_manager.create_task.return_value = {
        "task_id": "task-text-1",
        "view_token": "view-text-1",
    }
    background_calls = []

    def fake_process_local_upload(*args):
        background_calls.append(args)

    monkeypatch.setattr(study, "cache_manager", cache_manager)
    monkeypatch.setattr(study, "process_local_upload", fake_process_local_upload)
    monkeypatch.setattr(study, "get_source_root", lambda: tmp_path / "sources")

    response = TestClient(_build_app()).post(
        "/api/study/text",
        json={
            "title": "",
            "content": "\n## 第一章 Agent 的基本结构\n\nLLM 负责推理，工具负责行动。\n",
        },
    )

    assert response.status_code == 202
    assert response.json()["data"]["view_token"] == "view-text-1"
    source_files = list((tmp_path / "sources" / "study_texts").glob("*.md"))
    assert len(source_files) == 1
    assert source_files[0].read_text(encoding="utf-8") == (
        "## 第一章 Agent 的基本结构\n\nLLM 负责推理，工具负责行动。"
    )
    assert "Agent" not in source_files[0].name
    assert cache_manager.create_task.call_args.kwargs["url"].startswith(
        "local://study-text/"
    )
    assert background_calls[0][2] == "第一章 Agent 的基本结构.md"
    assert background_calls[0][-3:] == (True, True, False)


def test_study_text_rejects_blank_content():
    response = TestClient(_build_app()).post(
        "/api/study/text",
        json={"title": "空白", "content": " \n\t "},
    )

    assert response.status_code == 422


def test_study_text_keeps_user_title_out_of_file_path(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import study

    cache_manager = MagicMock()
    cache_manager.create_task.return_value = {
        "task_id": "task-text-2",
        "view_token": "view-text-2",
    }
    monkeypatch.setattr(study, "cache_manager", cache_manager)
    monkeypatch.setattr(study, "process_local_upload", lambda *args: None)
    monkeypatch.setattr(study, "get_source_root", lambda: tmp_path / "sources")

    response = TestClient(_build_app()).post(
        "/api/study/text",
        json={"title": "../../季度复盘", "content": "这是正文。"},
    )

    assert response.status_code == 202
    source_files = list((tmp_path / "sources" / "study_texts").glob("*.md"))
    assert len(source_files) == 1
    assert "季度复盘" not in str(source_files[0])


def test_export_study_markdown(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    service.export_markdown.return_value = "# lesson\n\n## 我的笔记"
    monkeypatch.setattr(study, "get_study_service", lambda: service)

    client = TestClient(_build_app())
    response = client.get("/api/study/view-123/export/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "# lesson" in response.text
    service.export_markdown.assert_called_once_with("view-123")
