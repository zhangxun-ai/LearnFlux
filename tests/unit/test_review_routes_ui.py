from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.api.routes import reviews
from video_transcript_api.api.services.transcription import verify_token
from video_transcript_api.reviews import ReviewRepository, ReviewService


def _client(tmp_path):
    db_path = tmp_path / "routes.db"
    app = FastAPI()
    app.include_router(reviews.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "alice"}

    def service_dependency():
        service = ReviewService(ReviewRepository(db_path), {})
        try:
            yield service
        finally:
            service.close()

    app.dependency_overrides[reviews.review_service_dependency] = service_dependency
    return TestClient(app)


def test_daily_weekly_monthly_and_source_routes(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/reviews/daily-events",
        json={
            "review_date": "2026-08-24",
            "title": "Meeting",
            "fact": "I spoke after ten minutes",
            "past": {"thoughts": "Worried"},
        },
    )
    assert created.status_code == 201
    event = created.json()["data"]["record"]
    second = client.post(
        "/api/reviews/daily-events",
        json={"review_date": "2026-08-25", "title": "Follow-up", "fact": "I spoke first"},
    ).json()["data"]["record"]
    assert created.json()["data"]["sync"]["status"] == "not_configured"

    saved = client.patch(
        f"/api/reviews/daily-events/{event['id']}",
        json={"quick_meaning": "Try stating the conclusion first"},
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["record"]["quick_meaning"].startswith("Try")

    weekly = client.get("/api/reviews/weekly/2026-08-26")
    assert weekly.status_code == 200
    assert weekly.json()["data"]["period"] == {
        "start": "2026-08-24", "end": "2026-08-30"
    }
    assert {item["id"] for item in weekly.json()["data"]["daily_events"]} == {
        event["id"], second["id"]
    }

    connection = client.post(
        "/api/reviews/connections",
        json={
            "period_type": "weekly",
            "period_key": "2026-08-24",
            "source_id": event["id"],
            "target_id": second["id"],
            "direction": "forward",
            "title": "A directional relation",
        },
    )
    assert connection.status_code == 201
    assert connection.json()["data"]["target_id"] == second["id"]

    save_week = client.put(
        "/api/reviews/weekly/2026-08-26",
        json={"focus_ids": [event["id"]], "abstraction": {"1": "Possible pattern"}},
    )
    assert save_week.status_code == 200
    weekly_record = save_week.json()["data"]["record"]

    source = client.get(f"/api/reviews/source/weekly/{weekly_record['id']}")
    assert source.status_code == 200
    assert {item["record"]["id"] for item in source.json()["data"]["sources"]} == {
        event["id"], second["id"]
    }

    monthly = client.put(
        "/api/reviews/monthly/2026-08",
        json={"inner": ["担心"], "actions": ["先说结论"], "results": [], "notes": []},
    )
    assert monthly.status_code == 200
    assert monthly.json()["data"]["record"]["inner"] == ["担心"]
    assert {item["type"] for item in monthly.json()["data"]["record"]["source_ids"]} == {"daily", "weekly"}

    insights = client.get("/api/reviews/insights")
    assert insights.status_code == 200
    assert insights.json()["data"]["overview"]["daily_events"] == 2
    assert len(insights.json()["data"]["recent_sources"]) == 2


def test_review_owner_isolation_and_explicit_delete(tmp_path):
    client = _client(tmp_path)
    event = client.post(
        "/api/reviews/daily-events",
        json={"review_date": "2026-08-24", "title": "Private"},
    ).json()["data"]["record"]

    assert client.delete(f"/api/reviews/daily-events/{event['id']}").status_code == 200
    assert client.delete(f"/api/reviews/daily-events/{event['id']}").status_code == 404


def test_review_navigation_and_frontend_contracts():
    navigation = json.loads(
        reviews.get_static_dir().parent.joinpath("product-navigation.json").read_text(encoding="utf-8")
    )
    assert "review" in navigation["groups"][0]["items"]
    assert navigation["items"]["review"]["href"] == "/review"
    review_children = navigation["items"]["review"]["children"]
    assert [item["section"] for item in review_children] == [
        "daily", "weekly", "monthly", "annual", "insights",
    ]

    static_dir = reviews.get_static_dir()
    html = (static_dir / "review.html").read_text(encoding="utf-8")
    css = (static_dir / "css" / "review.css").read_text(encoding="utf-8")
    javascript = (static_dir / "js" / "review.js").read_text(encoding="utf-8")

    for label in ("今日复盘", "周度复盘", "月度复盘", "年度复盘", "内在洞察"):
        assert label in html
    for section in ("daily", "weekly", "monthly", "annual", "insights"):
        assert f'href="/review/{section}"' in html
    assert html.count("data-review-section=") == 5
    assert 'class="nav-branch-toggle"' in html
    assert 'aria-controls="nav-review-children"' in html
    assert (
        '<nav class="nav-subitems" id="nav-review-children" '
        'aria-label="复盘二级导航">'
    ) in html
    assert "review-subnav" not in html
    assert "data-review-tab=" not in html
    assert "REFLECT · CONNECT · EXPERIMENT" not in html
    assert 'id="review-guide-open"' in html
    assert 'id="review-guide-dialog"' in html
    assert "复盘指南" in html

    assert "review-daily-template" in css
    assert "review-week-sheet" in css
    assert "review-month-sheet" in css
    assert "review-annual-table" in css
    assert "review-insight-map" in css
    assert "prefers-reduced-motion" in css
    assert "--review-page: var(--product-page)" in css
    assert "#265f50" not in css
    assert "#913149" not in css
    assert "review-result-followup" not in css
    assert "review_daily" not in javascript
    assert "/api/reviews/ai/analyze" in javascript
    assert "data-ai-statement" in javascript
    assert "event.metaKey || event.ctrlKey" in javascript
    assert "⌘ / Ctrl + Enter" not in javascript
    assert "行动后回来记录实际结果" not in javascript
    assert "已经行动？补充实际结果" in javascript
    assert "history.pushState" in javascript
    assert "window.addEventListener('popstate'" in javascript
    assert "window.addEventListener('hashchange'" not in javascript
    assert "const TABS = ['daily', 'weekly', 'monthly', 'annual', 'insights'];" in javascript
    assert "EVIDENCE, NOT A TEST" not in javascript
    for emotion in ("快乐", "信任", "恐惧", "惊讶", "悲伤", "厌恶", "愤怒", "期待"):
        assert emotion in javascript

    history = (static_dir / "history.html").read_text(encoding="utf-8")
    assert 'id="filterRecordType"' in history
    assert "/api/reviews/search" in history
    assert "复盘历史不依赖任务审计" in history
    assert "catch (e) { return encoded; }" in history


def test_review_secondary_routes_render_the_same_workspace(tmp_path):
    client = _client(tmp_path)

    for section in ("daily", "weekly", "monthly", "annual", "insights"):
        response = client.get(f"/review/{section}")
        assert response.status_code == 200
        assert 'data-review-section="daily"' in response.text
        assert 'id="review-view"' in response.text
