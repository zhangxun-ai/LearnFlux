from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
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


def _build_app_with_obsidian():
    from video_transcript_api.api.routes import obsidian, study
    from video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(obsidian.router)
    app.include_router(study.router)
    app.dependency_overrides[verify_token] = _fake_verify_token
    return app


def _study_session(title="Lesson"):
    return {
        "metadata": {"title": title},
        "transcript": {"lines": [{"text": "body", "seekable": False}]},
    }


def test_obsidian_sync_service_is_shared_across_requests(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import obsidian

    cache_manager = MagicMock()
    cache_manager.db_path = tmp_path / "study.db"
    monkeypatch.setattr(
        obsidian,
        "_configured_settings",
        lambda: {
            "vault_id": "vault-1",
            "vault_path": str(tmp_path / "vault"),
        },
    )
    monkeypatch.setattr(obsidian, "get_cache_manager", lambda: cache_manager)

    obsidian.get_obsidian_sync_service.cache_clear()
    try:
        first = obsidian.get_obsidian_sync_service()
        second = obsidian.get_obsidian_sync_service()
    finally:
        obsidian.get_obsidian_sync_service.cache_clear()

    assert first is second


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
    media_access = MagicMock()
    media_access.issue_single.return_value = "signed-media-token"
    monkeypatch.setattr(study, "get_study_media_access", lambda: media_access)

    client = TestClient(_build_app())
    response = client.get("/api/study/view-123")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["data"]["metadata"]["title"] == "lesson.mp4"
    assert body["data"]["playback"]["source_url"] == (
        "/api/study/view-123/source-file?media_token=signed-media-token"
    )
    assert "sk-test" not in body["data"]["playback"]["source_url"]
    service.get_session.assert_called_once_with("view-123")


def test_study_source_file_requires_valid_signed_media_token(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import study

    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"video")
    service = MagicMock()
    service.get_source_file.return_value = source
    media_access = MagicMock()
    monkeypatch.setattr(study, "get_study_service", lambda: service)
    monkeypatch.setattr(study, "get_study_media_access", lambda: media_access)
    client = TestClient(_build_app())

    missing = client.get("/api/study/view-123/source-file")
    media_access.verify_single.side_effect = ValueError("invalid media token")
    invalid = client.get("/api/study/view-123/source-file?media_token=bad")
    media_access.verify_single.side_effect = None
    valid = client.get("/api/study/view-123/source-file?media_token=good")

    assert missing.status_code == 422
    assert invalid.status_code == 404
    assert valid.status_code == 200
    assert valid.headers["cache-control"] == "private, no-store"
    media_access.verify_single.assert_called_with("good", view_token="view-123")


def test_study_library_static_route_is_not_consumed_as_view_token(monkeypatch):
    from video_transcript_api.api.routes import study

    library = MagicMock()
    library.list.return_value = {"items": [], "total": 0}
    session_service = MagicMock()
    monkeypatch.setattr(study, "get_study_library_service", lambda: library)
    monkeypatch.setattr(study, "get_study_service", lambda: session_service)

    response = TestClient(_build_app()).get("/api/study/library?kind=single")

    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "total": 0}
    library.list.assert_called_once_with(
        kind="single",
        user_id="test-user",
        q="",
        limit=20,
        offset=0,
    )
    session_service.get_session.assert_not_called()


def test_get_study_session_returns_404_for_missing_token(monkeypatch):
    from video_transcript_api.api.routes import study

    service = MagicMock()
    service.get_session.return_value = None
    monkeypatch.setattr(study, "get_study_service", lambda: service)

    client = TestClient(_build_app())
    response = client.get("/api/study/missing")

    assert response.status_code == 404


def test_multi_user_study_session_hides_other_users_task(monkeypatch):
    from video_transcript_api.api.routes import study

    user_manager = MagicMock()
    user_manager.is_multi_user_mode.return_value = True
    cache = MagicMock()
    cache.get_task_by_view_token.return_value = {"task_id": "task-other"}
    audit = MagicMock()
    audit.get_recent_calls.return_value = [{"task_id": "task-owned"}]
    monkeypatch.setattr(study, "user_manager", user_manager)
    monkeypatch.setattr(study, "cache_manager", cache)
    monkeypatch.setattr(study, "audit_logger", audit)

    response = TestClient(_build_app()).get("/api/study/view-other")

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


def test_single_note_document_get_and_put_use_owned_context(monkeypatch):
    from video_transcript_api.api.routes import study
    from video_transcript_api.study.repository import StudyRevisionConflict

    study_service = MagicMock()
    study_service.get_session.return_value = _study_session()
    sync_service = MagicMock()
    sync_service.load_note.return_value = {
        "document": {"id": "doc-1", "body": "draft", "revision": 2},
        "state": "app_dirty",
    }
    sync_service.save_note.return_value = {
        "id": "doc-1",
        "body": "updated",
        "revision": 3,
    }
    monkeypatch.setattr(study, "get_study_service", lambda: study_service)
    monkeypatch.setattr(study, "get_obsidian_sync_service", lambda: sync_service)
    client = TestClient(_build_app_with_obsidian())

    loaded = client.get("/api/study/view-123/note-document")
    saved = client.put(
        "/api/study/view-123/note-document",
        json={"body": "updated", "expected_revision": 2},
    )

    assert loaded.status_code == 200
    assert loaded.json()["data"]["document"]["body"] == "draft"
    assert saved.status_code == 200
    context = sync_service.load_note.call_args.args[0]
    assert context.view_token == "view-123"
    assert context.collection_id == ""
    assert context.owner_user_id == "test-user"
    sync_service.save_note.assert_called_once_with(
        context, body="updated", expected_revision=2
    )

    sync_service.save_note.side_effect = StudyRevisionConflict(
        {"id": "doc-1", "body": "newer", "revision": 4}
    )
    conflict = client.put(
        "/api/study/view-123/note-document",
        json={"body": "stale", "expected_revision": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current"]["body"] == "newer"


def test_collection_note_and_binding_use_collection_scope(monkeypatch):
    from video_transcript_api.api.routes import study

    collection_service = MagicMock()
    collection_service.repository.get_collection.return_value = {
        "id": "c1",
        "owner_user_id": "test-user",
    }
    collection_service.get_source_detail.return_value = {
        "id": "s1",
        "view_token": "view-shared",
        "title": "Episode 1",
    }
    collection_service.get_collection_detail.return_value = {
        "id": "c1",
        "title": "Course",
        "sources": [],
    }
    study_service = MagicMock()
    study_service.get_collection_session.return_value = _study_session("Episode 1")
    sync_service = MagicMock()
    sync_service.load_note.return_value = {
        "document": {"id": "doc-c1-s1", "body": "", "revision": 1},
        "state": "skipped_empty",
    }
    sync_service.save_binding.return_value = {
        "id": "binding-c1",
        "scope_type": "collection",
        "revision": 1,
    }
    monkeypatch.setattr(study, "get_collection_service", lambda: collection_service)
    monkeypatch.setattr(study, "get_study_service", lambda: study_service)
    monkeypatch.setattr(study, "get_obsidian_sync_service", lambda: sync_service)
    client = TestClient(_build_app_with_obsidian())

    note = client.get("/api/study/collections/c1/sources/s1/note-document")
    binding = client.put(
        "/api/study/collections/c1/obsidian-binding",
        json={
            "transcript_directory": "raw/Course",
            "note_directory": "Course/笔记",
            "expected_revision": None,
        },
    )

    assert note.status_code == 200
    assert binding.status_code == 200
    note_context = sync_service.load_note.call_args.args[0]
    binding_context = sync_service.save_binding.call_args.args[0]
    assert (note_context.collection_id, note_context.source_id) == ("c1", "s1")
    assert (binding_context.collection_id, binding_context.source_id) == ("c1", "")
    assert binding_context.course == "Course"


@pytest.mark.parametrize(
    ("result", "status_code"),
    [
        (
            {
                "overall": "success",
                "transcript": {"status": "created"},
                "note": {"status": "created"},
            },
            200,
        ),
        (
            {
                "overall": "partial",
                "transcript": {"status": "created"},
                "note": {"status": "failed"},
            },
            207,
        ),
        (
            {
                "overall": "failed",
                "transcript": {"status": "failed"},
                "note": {"status": "failed"},
            },
            500,
        ),
    ],
)
def test_single_obsidian_sync_maps_per_file_result_status(monkeypatch, result, status_code):
    from video_transcript_api.api.routes import study

    study_service = MagicMock()
    study_service.get_session.return_value = _study_session()
    sync_service = MagicMock()
    sync_service.sync.return_value = result
    monkeypatch.setattr(study, "get_study_service", lambda: study_service)
    monkeypatch.setattr(study, "get_obsidian_sync_service", lambda: sync_service)

    response = TestClient(_build_app_with_obsidian()).post(
        "/api/study/view-123/obsidian-sync"
    )

    assert response.status_code == status_code
    assert response.json()["data"] == result


def test_obsidian_conflict_payload_returns_409(monkeypatch):
    from video_transcript_api.api.routes import study
    from video_transcript_api.obsidian.service import ObsidianConflict

    study_service = MagicMock()
    study_service.get_session.return_value = _study_session()
    sync_service = MagicMock()
    sync_service.sync.side_effect = ObsidianConflict(
        {
            "code": "conflict",
            "state": "conflict",
            "preconditions": {
                "expected_revision": 2,
                "expected_obsidian_hash": "obs-hash",
                "expected_baseline_hash": "base-hash",
            },
        }
    )
    monkeypatch.setattr(study, "get_study_service", lambda: study_service)
    monkeypatch.setattr(study, "get_obsidian_sync_service", lambda: sync_service)

    response = TestClient(_build_app_with_obsidian()).post(
        "/api/study/view-123/obsidian-sync"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "conflict"


def test_conflict_resolution_forwards_all_stale_preconditions(monkeypatch):
    from video_transcript_api.api.routes import study

    study_service = MagicMock()
    study_service.get_session.return_value = _study_session()
    sync_service = MagicMock()
    sync_service.resolve_conflict.return_value = {
        "document": {"body": "kept", "revision": 3},
        "note_relative_path": "Course/笔记/Lesson.md",
    }
    monkeypatch.setattr(study, "get_study_service", lambda: study_service)
    monkeypatch.setattr(study, "get_obsidian_sync_service", lambda: sync_service)

    response = TestClient(_build_app_with_obsidian()).post(
        "/api/study/view-123/obsidian-conflict/resolve",
        json={
            "choice": "recreate_from_app",
            "expected_revision": 2,
            "expected_obsidian_hash": "__absent__",
            "expected_baseline_hash": "base-hash",
        },
    )

    assert response.status_code == 200
    context = sync_service.resolve_conflict.call_args.args[0]
    sync_service.resolve_conflict.assert_called_once_with(
        context,
        choice="recreate_from_app",
        expected_revision=2,
        expected_obsidian_hash="__absent__",
        expected_baseline_hash="base-hash",
    )


def test_obsidian_global_status_and_directories_are_authenticated_and_redacted(
    monkeypatch, tmp_path
):
    from video_transcript_api.api.routes import obsidian

    vault = tmp_path / "SecretVault"
    (vault / "raw" / "Course").mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    monkeypatch.setattr(
        obsidian,
        "get_obsidian_settings",
        lambda: {
            "enabled": True,
            "vault_id": "vault-1",
            "vault_path": str(vault),
        },
    )
    client = TestClient(_build_app_with_obsidian())

    status = client.get("/api/obsidian/status")
    directories = client.get("/api/obsidian/directories?root=vault")
    created = client.post(
        "/api/obsidian/directories",
        json={"parent_relative_path": "raw/Course", "name": "笔记"},
    )

    assert status.status_code == 200
    assert status.json()["data"]["available"] is True
    assert str(tmp_path) not in status.text
    assert ".obsidian" not in directories.text
    assert created.json()["data"]["relative_path"] == "raw/Course/笔记"

    async def unauthorized():
        raise HTTPException(status_code=401, detail="unauthorized")

    from video_transcript_api.api.services.transcription import verify_token

    unauthorized_app = FastAPI()
    unauthorized_app.include_router(obsidian.router)
    unauthorized_app.dependency_overrides[verify_token] = unauthorized
    assert TestClient(unauthorized_app).get("/api/obsidian/status").status_code == 401


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
    audit_logger = MagicMock()
    monkeypatch.setattr(study, "audit_logger", audit_logger)

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
    assert audit_logger.log_api_call.call_args.kwargs["task_id"] == "task-1"
    assert audit_logger.log_api_call.call_args.kwargs["user_id"] == "test-user"


def test_retry_failed_single_study_creates_new_task_and_audits(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import study

    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"video")
    cache = MagicMock()
    cache.get_task_by_view_token.return_value = {
        "task_id": "old-task",
        "view_token": "old-view",
        "status": "failed",
        "url": "local://study-source/media/lesson.mp4",
        "media_id": "media",
        "use_speaker_recognition": False,
        "title": "lesson.mp4",
    }
    cache.create_task.return_value = {"task_id": "new-task", "view_token": "new-view"}
    service = MagicMock()
    service.get_source_file.return_value = source
    audit = MagicMock()
    audit.get_recent_calls.return_value = [{"task_id": "old-task"}]
    monkeypatch.setattr(study, "cache_manager", cache)
    monkeypatch.setattr(study, "audit_logger", audit)
    monkeypatch.setattr(study, "get_study_service", lambda: service)

    response = TestClient(_build_app()).post("/api/study/old-view/retry")

    assert response.status_code == 202
    assert response.json()["data"]["view_token"] == "new-view"
    assert cache.create_task.call_args.kwargs["force_new_view_token"] is True
    assert audit.log_api_call.call_args.kwargs["task_id"] == "new-task"


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
