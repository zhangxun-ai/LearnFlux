"""Unit tests for flywheel prompt management endpoints."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import MediaType
from src.video_transcript_api.flywheel.prompts import DEFAULT_PROMPTS, VIDEO_SYSTEM_PROMPT
from src.video_transcript_api.flywheel.repositories import (
    SqliteAnalysisCostRepository,
    SqliteAnalysisRepository,
    SqliteBloggerRepository,
    SqliteContentRepository,
    SqlitePromptTemplateRepository,
)


def test_flywheel_prompt_api_view_save_and_reset(tmp_path, monkeypatch):
    from src.video_transcript_api.api.routes import flywheel
    from src.video_transcript_api.api.services import flywheel_service
    from src.video_transcript_api.api.services.transcription import verify_token

    db = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    prompt = SqlitePromptTemplateRepository(db)
    prompt.seed_defaults(DEFAULT_PROMPTS)
    repos = {
        "db": db,
        "blogger": SqliteBloggerRepository(db),
        "content": SqliteContentRepository(db),
        "analysis": SqliteAnalysisRepository(db),
        "cost": SqliteAnalysisCostRepository(db),
        "prompt": prompt,
    }
    monkeypatch.setattr(flywheel_service, "_repos", repos)

    app = FastAPI()
    app.include_router(flywheel.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    listed = client.get("/api/flywheel/prompts")
    assert listed.status_code == 200
    video_prompt = next(item for item in listed.json()["items"] if item["media_type"] == "video")
    assert video_prompt["body"] == VIDEO_SYSTEM_PROMPT
    assert video_prompt["version"] == 1
    assert video_prompt["versions"][0]["version"] == 1

    saved = client.put(
        "/api/flywheel/prompts/video",
        json={"body": "新版视频提示词：必须输出原文证据和可复制模板。"},
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 2
    assert prompt.get_active(MediaType.VIDEO).body.startswith("新版视频提示词")

    reset = client.post("/api/flywheel/prompts/video/reset")
    assert reset.status_code == 200
    assert reset.json()["body"] == VIDEO_SYSTEM_PROMPT
    assert reset.json()["version"] == 3

    db.close()


def test_flywheel_prompt_api_rejects_empty_body(tmp_path, monkeypatch):
    from src.video_transcript_api.api.routes import flywheel
    from src.video_transcript_api.api.services import flywheel_service
    from src.video_transcript_api.api.services.transcription import verify_token

    db = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    prompt = SqlitePromptTemplateRepository(db)
    prompt.seed_defaults(DEFAULT_PROMPTS)
    monkeypatch.setattr(
        flywheel_service,
        "_repos",
        {
            "db": db,
            "blogger": SqliteBloggerRepository(db),
            "content": SqliteContentRepository(db),
            "analysis": SqliteAnalysisRepository(db),
            "cost": SqliteAnalysisCostRepository(db),
            "prompt": prompt,
        },
    )

    app = FastAPI()
    app.include_router(flywheel.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.put("/api/flywheel/prompts/video", json={"body": "   "})

    assert response.status_code == 400
    assert "不能为空" in response.json()["detail"]

    db.close()


def test_flywheel_draft_route_uses_deepseek_v4_pro(monkeypatch):
    from src.video_transcript_api.api.routes import flywheel
    from src.video_transcript_api.api.services.transcription import verify_token

    coordinator = type(
        "Coordinator",
        (),
        {
            "llm_client": object(),
            "config": type("Config", (), {})(),
        },
    )()
    monkeypatch.setattr(flywheel, "get_llm_coordinator", lambda: coordinator)

    captured = {}

    def fake_generate_draft(content_id, generator):
        captured["content_id"] = content_id
        captured["model"] = generator.model
        captured["reasoning_effort"] = generator.reasoning_effort
        return {
            "ok": True,
            "content_id": content_id,
            "markdown": "## 标题候选\n1. 新标题",
            "model": generator.model,
            "reasoning_effort": generator.reasoning_effort,
        }

    monkeypatch.setattr(flywheel.svc, "generate_draft", fake_generate_draft)

    app = FastAPI()
    app.include_router(flywheel.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post("/api/flywheel/content/42/draft")

    assert response.status_code == 200
    assert captured == {
        "content_id": 42,
        "model": "deepseek-v4-pro",
        "reasoning_effort": "high",
    }
    assert response.json()["model"] == "deepseek-v4-pro"
