"""Unit tests for flywheel opportunity radar service and route."""

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import (
    Analysis,
    AnalysisStatus,
    Blogger,
    Content,
    ContentSource,
    MediaType,
)
from src.video_transcript_api.flywheel.repositories import (
    SqliteAnalysisCostRepository,
    SqliteAnalysisRepository,
    SqliteBloggerRepository,
    SqliteContentRepository,
    SqlitePromptTemplateRepository,
)


def _repo_env(tmp_path, monkeypatch):
    from src.video_transcript_api.api.services import flywheel_service

    db = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    repos = {
        "db": db,
        "blogger": SqliteBloggerRepository(db),
        "content": SqliteContentRepository(db),
        "analysis": SqliteAnalysisRepository(db),
        "cost": SqliteAnalysisCostRepository(db),
        "prompt": SqlitePromptTemplateRepository(db),
    }
    monkeypatch.setattr(flywheel_service, "_repos", repos)
    return db, repos


def _seed_content(repos, *, item_id, title, likes, collects, comments, one_thing):
    blogger = repos["blogger"].upsert(
        Blogger(
            id=None,
            platform="xiaohongshu",
            platform_user_id=f"user-{item_id}",
            handle=f"@{item_id}",
            is_subscribed=True,
        )
    )
    content = repos["content"].upsert(
        Content(
            id=None,
            blogger_id=blogger.id,
            platform="xiaohongshu",
            platform_item_id=item_id,
            media_type=MediaType.ARTICLE,
            title=title,
            original_url=f"https://x/{item_id}",
            published_at=datetime.now() - timedelta(days=2),
            like_count=likes,
            collect_count=collects,
            comment_count=comments,
            source=ContentSource.FEED,
            analysis_status=AnalysisStatus.SUCCESS,
        )
    )
    analysis = repos["analysis"].create(
        Analysis(
            id=None,
            content_id=content.id,
            media_type=MediaType.ARTICLE,
            status=AnalysisStatus.SUCCESS,
            result_json={
                "one_thing": one_thing,
                "sections": [
                    {
                        "title": "12 下一篇怎么插接",
                        "body": "把模板和清单做成系列选题。",
                    }
                ],
            },
        )
    )
    repos["content"].set_analysis_status(content.id, AnalysisStatus.SUCCESS, analysis.id)
    return content


def test_list_opportunities_ranks_successful_content(tmp_path, monkeypatch):
    from src.video_transcript_api.api.services import flywheel_service

    db, repos = _repo_env(tmp_path, monkeypatch)
    high = _seed_content(
        repos,
        item_id="high",
        title="高机会内容",
        likes=5000,
        collects=3000,
        comments=700,
        one_thing="整理一个可复制模板合集。",
    )
    _seed_content(
        repos,
        item_id="low",
        title="低机会内容",
        likes=30,
        collects=1,
        comments=0,
        one_thing="",
    )

    result = flywheel_service.list_opportunities(limit=2)

    assert result["items"][0]["content_id"] == high.id
    assert result["items"][0]["score"] >= result["items"][1]["score"]
    assert result["items"][0]["level"] == "high"
    assert result["items"][0]["next_action"] == "整理一个可复制模板合集。"
    db.close()


def test_opportunities_route_returns_items(tmp_path, monkeypatch):
    from src.video_transcript_api.api.routes import flywheel
    from src.video_transcript_api.api.services.transcription import verify_token

    db, repos = _repo_env(tmp_path, monkeypatch)
    _seed_content(
        repos,
        item_id="route",
        title="路由内容",
        likes=1200,
        collects=600,
        comments=100,
        one_thing="做一个清单帖。",
    )

    app = FastAPI()
    app.include_router(flywheel.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.get("/api/flywheel/opportunities?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["title"] == "路由内容"
    assert payload["items"][0]["score"] > 0
    assert payload["limit"] == 5
    db.close()
