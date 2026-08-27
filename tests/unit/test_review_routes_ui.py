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
    emotion_wheel = static_dir / "images" / "review" / "emotion-wheel.png"

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
    assert 'id="review-example-dialog"' in html
    assert 'id="review-example-title"' in html
    assert 'id="review-example-content"' in html
    search_form = html.split('id="review-search-form"', 1)[1].split("</form>", 1)[0]
    assert 'name="keyword"' in search_form
    assert "autofocus" in search_form
    for field_name in (
        "start_date",
        "end_date",
        "record_type",
        "meaning_type",
        "emotion",
        "insight_tier",
        "status",
    ):
        assert f'name="{field_name}"' not in search_form

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
    assert "review-daily-workspace" in javascript
    assert "review-record-rail" not in javascript
    assert 'data-action="select-daily"' not in javascript
    assert 'data-action="shift-daily"' in javascript
    assert "review-event-actions" in javascript
    assert "openSearch" in javascript
    assert "openSearchResult" in javascript
    assert 'data-action="open-search-result"' in javascript
    assert "event.target === dialog" in javascript
    assert "什么事件让你内心有所触动？" in javascript
    assert "事件发生时，我在想什么、感受什么？" in javascript
    assert "当时我采取了什么行动？" in javascript
    assert "这个行动带来了什么结果？" in javascript
    assert "回顾事件和左侧记录后，我重新注意到了什么？" in javascript
    assert "从现在开始，我可以采取什么具体行动？" in javascript
    assert "这些行动可能会带来怎样的结果？" in javascript
    assert "第一步" in javascript and "如实记录" in javascript
    assert "第二步" in javascript and "意义重塑" in javascript
    assert "第 ${index + 1} 件" not in javascript
    daily_card = javascript.split("function renderDailyCard", 1)[1].split(
        "function collectDailyCard", 1
    )[0]
    weekly_panel = javascript.split("function weeklyPanel", 1)[1].split(
        "function setWeeklyStep", 1
    )[0]
    monthly_view = javascript.split("function renderMonthly()", 1)[1].split(
        "function renderMonthlyConnections", 1
    )[0]
    assert 'data-action="open-example"' in daily_card
    assert 'data-action="open-example"' in weekly_panel
    assert 'data-action="open-example"' in monthly_view
    assert "查看填写案例" in daily_card
    assert "查看填写案例" in weekly_panel
    assert "查看填写案例" in monthly_view
    assert 'data-help="emotion"' in daily_card
    assert "选择情绪词" in daily_card
    assert "整理记录（可选）" in daily_card
    assert "以后按名称、人物或主题查找" in daily_card
    assert 'data-action="delete-daily"' in daily_card
    assert 'data-action="source"' not in daily_card
    assert "复制记录" not in daily_card
    assert "如何区分事实" not in daily_card
    assert "如何理解意义重塑" not in daily_card
    assert "当时真正想要什么" not in daily_card
    assert "现在看见了自己的什么" not in daily_card
    assert "这次意义更接近什么" not in daily_card
    assert "/static/images/review/emotion-wheel.png" in javascript
    assert "每日复盘案例" in javascript
    assert "周度复盘案例" in javascript
    assert "月度复盘案例" in javascript
    assert "团队氛围低迷时，找到自己能做的事" in javascript
    assert "从一本书和一封邮件开始的联结" in javascript
    assert "4 月的想法，在之后几个月形成结果" in javascript
    assert "依据《复盘自己：从记录到蜕变的行动指南》案例整理" in javascript
    assert "function openExample" in javascript
    assert "open-example" in javascript
    example_source = javascript.split("const REVIEW_EXAMPLES", 1)[1].split(
        "const today", 1
    )[0]
    assert "一键套用" not in example_source
    assert "复制案例" not in example_source
    assert "past: {...(item?.past || {})}" in javascript
    assert "present: {...(item?.present || {})}" in javascript
    assert "payload.meaning_types =" not in javascript
    assert emotion_wheel.exists()
    assert emotion_wheel.stat().st_size > 100_000
    assert '.review-workspace[data-review-tab="daily"]' in css
    assert ".review-daily-workspace" in css
    assert ".review-record-rail" not in css
    assert ".review-template-field:not(:last-child)::after" not in css
    assert "review-weekly-workspace" in javascript
    assert "function syncWeeklyDraftFromView" in javascript
    assert "weeklyDrafts: new Map()" in javascript
    assert "syncWeeklyDraftFromView();\n        state.weeklyStep" in javascript
    assert "renderWeekly();\n        elements.view.querySelector(`[data-week-panel" not in javascript
    assert "monthlyDrafts: new Map()" in javascript
    assert "function captureMonthlyDraft" in javascript
    assert "captureMonthlyDraft(true);" in javascript
    assert "if (!markDirty && !state.monthlyDrafts.has(state.month)) return;" in javascript
    assert "captureMonthlyDraft();\n        state.month = month" in javascript
    assert "if (state.tab === 'monthly') return selectMonthlyMonth(button.dataset.monthKey);" in javascript
    assert "annualDrafts: new Map()" in javascript
    assert "function captureAnnualDraft" in javascript
    assert "function selectAnnualYear" in javascript
    assert "captureAnnualDraft(true);" in javascript
    assert "if (state.tab === 'annual') return selectAnnualYear(button.dataset.yearKey);" in javascript
    assert "const savedKey = weeklyDraftKey();" in javascript
    assert "state.weeklyDrafts.delete(savedKey)" in javascript
    assert "const savedMonth = state.month;" in javascript
    assert "state.monthlyDrafts.delete(savedMonth)" in javascript
    assert "const savedYear = state.year;" in javascript
    assert "state.annualDrafts.delete(savedYear)" in javascript
    assert "data.applied_to?.type === 'annual'" in javascript
    assert "state.annualDrafts.set(year" in javascript
    assert "draftVersions: new Map()" in javascript
    assert "savesInFlight: new Set()" in javascript
    assert "function markDraftChanged" in javascript
    assert "const savedVersion = draftVersion('weekly', savedKey);" in javascript
    assert "const savedVersion = draftVersion('monthly', savedMonth);" in javascript
    assert "const savedVersion = draftVersion('annual', savedYear);" in javascript
    assert "保存期间有新更改，请再保存一次" in javascript
    assert 'data-weekly-step="${number}"' in javascript
    assert "选择最重要的事" in javascript
    assert "找联系" in javascript
    assert "看模式" in javascript
    assert "具体化" in javascript
    assert "review-year-overview" in javascript
    assert 'data-action="select-month"' in javascript
    assert "这一年发生了什么变化" in javascript
    assert "review-annual-lead" in javascript
    assert 'data-action="open-annual-month"' in javascript
    assert "有记录的月份会形成轨迹" in javascript
    assert "review-insight-overview" in javascript
    assert "review-insight-depth" in javascript
    assert "先看见重复，再决定它是否属于你" in javascript
    assert ".review-weekly-workspace" in css
    assert ".review-year-overview" in css
    assert ".review-annual-lead" in css
    assert ".review-insight-depth" in css
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
