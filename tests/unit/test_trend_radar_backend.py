import json
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.video_transcript_api.trend_radar.budget import BudgetExceeded, BudgetLedger
from src.video_transcript_api.trend_radar import service as trend_service
from src.video_transcript_api.trend_radar.models import RawSignal
from src.video_transcript_api.trend_radar.synthesizer import TrendRadarSynthesizer
from src.video_transcript_api.trend_radar.collector import TikHubTrendCollector


def test_budget_ledger_reserves_llm_budget_and_blocks_api_overrun():
    ledger = BudgetLedger(
        limit_usd=5,
        request_cost_usd=0.01,
        llm_reserved_usd=1,
    )

    for index in range(400):
        ledger.record_api_request("x", f"/api/demo/{index}")

    assert ledger.api_requests_used == 400
    assert ledger.estimated_api_usd == 4
    with pytest.raises(BudgetExceeded):
        ledger.record_api_request("x", "/api/demo/overflow")


def test_llm_reserve_scales_down_for_two_dollar_budget():
    reserved = trend_service._llm_reserved_budget(
        {
            "llm": {
                "api_key": "real-key",
                "base_url": "https://llm.example.com/v1",
            }
        },
        {"llm_reserved_usd": 1.0, "llm_reserved_max_ratio": 0.1},
        2.0,
    )

    assert reserved == 0.2


def test_collector_stops_at_budget_limit_without_failing_report():
    class FakeClient:
        def get(self, endpoint, params=None):
            return {"data": [{"title": endpoint, "desc": "signal", "like_count": 1}]}

        def post(self, endpoint, payload=None):
            return {"data": [{"title": endpoint, "desc": "signal", "like_count": 1}]}

    ledger = BudgetLedger(limit_usd=0.02, request_cost_usd=0.01, llm_reserved_usd=0)
    collector = TikHubTrendCollector(
        FakeClient(),
        ledger,
        {
            "sources": ("x",),
            "topics": [
                {
                    "id": "t1",
                    "label": "测试趋势",
                    "x_keywords": ("a", "b", "c"),
                    "chinese_keywords": (),
                }
            ],
            "max_keywords_per_topic": 3,
        },
    )

    signals = collector.collect()

    assert ledger.api_requests_used == 2
    assert collector.budget_exhausted is True
    assert signals


def test_collector_sends_required_douyin_billboard_params():
    class FakeClient:
        def __init__(self):
            self.get_calls = []

        def get(self, endpoint, params=None):
            self.get_calls.append((endpoint, params or {}))
            return {"data": [{"title": endpoint, "desc": "signal"}]}

        def post(self, endpoint, payload=None):
            return {"data": []}

    client = FakeClient()
    ledger = BudgetLedger(limit_usd=1, request_cost_usd=0.01, llm_reserved_usd=0)
    collector = TikHubTrendCollector(
        client,
        ledger,
        {
            "sources": ("douyin",),
            "topics": [
                {
                    "id": "t1",
                    "label": "测试趋势",
                    "x_keywords": (),
                    "chinese_keywords": ("测试",),
                }
            ],
        },
    )

    collector.collect()

    hot_total = next(params for endpoint, params in client.get_calls if "hot_total" in endpoint)
    hot_rise = next(params for endpoint, params in client.get_calls if "hot_rise" in endpoint)
    assert hot_total["type"] == 0
    assert hot_rise["order"] == 0


def test_collector_uses_string_douyin_search_params_and_builds_x_urls():
    class FakeClient:
        def __init__(self):
            self.post_calls = []

        def get(self, endpoint, params=None):
            if "twitter" in endpoint:
                return {"data": {"timeline": []}}
            return {"data": []}

        def post(self, endpoint, payload=None):
            self.post_calls.append((endpoint, payload or {}))
            return {"data": []}

    client = FakeClient()
    ledger = BudgetLedger(limit_usd=1, request_cost_usd=0.01, llm_reserved_usd=0)
    collector = TikHubTrendCollector(
        client,
        ledger,
        {
            "sources": ("douyin",),
            "topics": [
                {
                    "id": "t1",
                    "label": "测试趋势",
                    "x_keywords": (),
                    "chinese_keywords": ("测试",),
                }
            ],
        },
    )

    collector.collect()

    search_payload = next(payload for endpoint, payload in client.post_calls if "search" in endpoint)
    assert search_payload["sort_type"] == "0"
    assert search_payload["publish_time"] == "7"

    x_signal = collector._normalize_response(
        "x",
        "agentic-workflow",
        "AI 业务流程智能体",
        "/api/v1/twitter/web/fetch_search_timeline",
        {
            "data": {
                "timeline": [
                    {
                        "tweet_id": "123",
                        "screen_name": "builder",
                        "text": "AI agents are taking over procurement workflows.",
                        "favorites": 20,
                    }
                ]
            }
        },
    )[0]
    assert x_signal.url == "https://x.com/builder/status/123"
    assert x_signal.metrics["like_count"] == 20


def test_collector_defaults_x_search_to_latest_for_fresher_runs():
    class FakeClient:
        def __init__(self):
            self.get_calls = []

        def get(self, endpoint, params=None):
            self.get_calls.append((endpoint, params or {}))
            if "fetch_trending" in endpoint:
                return {"data": []}
            return {
                "data": {
                    "timeline": [
                        {
                            "tweet_id": "123",
                            "screen_name": "builder",
                            "text": "AI agents are entering procurement workflows.",
                            "favorites": 20,
                        }
                    ]
                }
            }

        def post(self, endpoint, payload=None):
            return {"data": []}

    client = FakeClient()
    ledger = BudgetLedger(limit_usd=1, request_cost_usd=0.01, llm_reserved_usd=0)
    collector = TikHubTrendCollector(
        client,
        ledger,
        {
            "sources": ("x",),
            "topics": [
                {
                    "id": "agentic-workflow",
                    "label": "AI 业务流程智能体",
                    "x_keywords": ("AI agent workflow",),
                    "chinese_keywords": (),
                }
            ],
        },
    )

    collector.collect()

    search_params = next(params for endpoint, params in client.get_calls if "fetch_search" in endpoint)
    assert search_params["search_type"] == "Latest"


def test_collector_latest_x_prioritizes_recent_records_over_old_viral_posts():
    class FakeClient:
        def get(self, endpoint, params=None):
            return {"data": []}

        def post(self, endpoint, payload=None):
            return {"data": []}

    collector = TikHubTrendCollector(
        FakeClient(),
        BudgetLedger(limit_usd=1, request_cost_usd=0.01, llm_reserved_usd=0),
        {"max_items_per_call": 2},
    )

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    fresh_date = (now - timedelta(hours=2)).strftime("%a %b %d %H:%M:%S +0000 %Y")
    old_date = (now - timedelta(days=30)).strftime("%a %b %d %H:%M:%S +0000 %Y")

    signals = collector._normalize_response(
        "x",
        "agentic-workflow",
        "AI 业务流程智能体",
        "/api/v1/twitter/web/fetch_search_timeline",
        {
            "data": {
                "timeline": [
                    {
                        "tweet_id": "old",
                        "screen_name": "viral",
                        "created_at": old_date,
                        "text": "AI agents viral thread with huge engagement.",
                        "favorites": 100000,
                    },
                    {
                        "tweet_id": "fresh",
                        "screen_name": "operator",
                        "created_at": fresh_date,
                        "text": "Fresh discussion about AI agents entering procurement workflows.",
                        "favorites": 20,
                    },
                ]
            }
        },
        prefer_fresh=True,
    )

    assert signals[0].url == "https://x.com/operator/status/fresh"


def test_synthesizer_localizes_english_evidence_preview_with_llm():
    class FakeLLM:
        def __init__(self):
            self.call_kwargs = {}

        def call(self, **kwargs):
            self.call_kwargs = kwargs
            payload = json.loads(kwargs["user_prompt"])
            assert all(row["platform"] == "英文 X" for row in payload["evidence"])
            return SimpleNamespace(
                structured_output={
                    "items": [
                        {
                            "id": row["id"],
                            "titleZh": "AI 采购代理进入真实流程",
                            "summaryZh": "英文 X 创业者讨论采购代理如何比较报价并接入 ERP。",
                        }
                        for row in payload["evidence"]
                    ]
                }
            )

    fake_llm = FakeLLM()
    signals = [
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI agents are moving into procurement workflows",
            text="Founders discuss agentic procurement, quote comparison, supplier review and ERP workflows.",
            url="https://x.com/founder/status/1",
            author="founder",
            metrics={"like_count": 1200, "comment_count": 90},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="Procurement agents are getting real budget",
            text="Operators debate AI agent permissions, audit logs, procurement ROI and supplier workflows.",
            url="https://x.com/operator/status/2",
            author="operator",
            metrics={"like_count": 900, "comment_count": 80},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="xiaohongshu",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI 智能体采购自动化有人用吗",
            text="评论在问智能体能不能自动比价和整理供应商报价。",
            url="https://www.xiaohongshu.com/explore/xhs1",
            author="采购人",
            metrics={"like_count": 120, "comment_count": 18},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="douyin",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI 办公工具",
            text="大众讨论仍停留在提示词和聊天助手。",
            url="https://www.douyin.com/video/3",
            author="职场号",
            metrics={"like_count": 80, "comment_count": 8},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
    ]

    report = TrendRadarSynthesizer(llm_client=fake_llm, model="deepseek-chat").build_report(
        signals,
        budget={"limit_usd": 2, "estimated_total_usd": 0.54},
        generated_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    english_evidence = next(row for row in report["items"][0]["evidence"] if row["platform"] == "英文 X")
    assert english_evidence["displayTitle"] == "AI 采购代理进入真实流程"
    assert english_evidence["displaySummary"] == "英文 X 创业者讨论采购代理如何比较报价并接入 ERP。"
    assert english_evidence["title"].startswith("AI agents") or english_evidence["title"].startswith("Procurement")
    assert english_evidence["rawText"]
    assert english_evidence["url"].startswith("https://x.com/")
    assert english_evidence["translationStatus"] == "localized"
    assert fake_llm.call_kwargs["task_type"] == "trend_radar_evidence_localization"
    assert "不添加原文没有的信息" in fake_llm.call_kwargs["system_prompt"]


def test_synthesizer_marks_elite_split_and_mass_unknown_as_opportunity():
    signals = [
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI agents are moving into procurement workflows",
            text="Founder discussion about agentic procurement, quote comparison and ERP workflows.",
            url="https://x.com/founder/status/1",
            author="founder",
            metrics={"like_count": 1800, "comment_count": 120},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="Procurement agents are not a toy anymore",
            text="Elite operators disagree on audit, permissions and ROI.",
            url="https://x.com/operator/status/2",
            author="operator",
            metrics={"like_count": 1200, "comment_count": 90},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="https://t.co/noise",
            text="https://t.co/noise",
            url="https://x.com/noise/status/9",
            author="noise",
            metrics={"like_count": 5000, "comment_count": 400},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="Introducing Claude Fable 5",
            text="Introducing Claude Fable 5, a Mythos-class model made safe for general use.",
            url="https://x.com/claudeai/status/2064394146916229443",
            author="claudeai",
            published_at="Tue Jun 09 17:08:13 +0000 2026",
            metrics={"like_count": 104832, "comment_count": 5031, "share_count": 14470},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="xiaohongshu",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI 智能体采购自动化有人用吗",
            text="评论在问智能体能不能自动比价和整理供应商报价。",
            url="https://www.xiaohongshu.com/explore/xhs1",
            author="采购人",
            metrics={"like_count": 120, "comment_count": 18},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="douyin",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI 办公工具",
            text="大众讨论仍停留在提示词和聊天助手。",
            url="https://www.douyin.com/video/3",
            author="职场号",
            metrics={"like_count": 80, "comment_count": 8},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
    ]

    report = TrendRadarSynthesizer().build_report(
        signals,
        budget={
            "limit_usd": 5,
            "estimated_total_usd": 1.25,
            "api_requests_used": 125,
        },
        generated_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    assert report["items"][0]["stage"] == "opportunity"
    assert report["analysis_version"] == "decision-brief-v4"
    assert report["items"][0]["signals"]["x"]["accept"] >= 40
    assert report["items"][0]["signals"]["douyin"]["unknown"] >= 50
    assert report["metrics"]["new_window"] == 1
    assert report["items"][0]["userValue"]
    assert report["items"][0]["evidence"][0]["url"].startswith("https://")
    item = report["items"][0]
    assert item["decision"] == "现在验证"
    assert item["brief"]["nextAction"]
    assert item["brief"]["killCriteria"]
    assert item["evidenceGrade"] in {"A", "B"}
    assert item["business"] == []
    assert item["evidence"][0]["summary"]
    assert item["evidence"][0]["keyFacts"]
    assert all(row["noiseRisk"] != "高" for row in item["evidence"])
    assert all("t.co/noise" not in row["summary"] for row in item["evidence"])
    assert all("Claude Fable" not in row["summary"] for row in item["evidence"])


def test_synthesizer_adds_stack_and_need_reading_fields():
    signals = [
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI agents are moving into procurement workflows",
            text="Founder discussion about agentic procurement, quote comparison and ERP workflows.",
            url="https://x.com/founder/status/1",
            author="founder",
            metrics={"like_count": 1800, "comment_count": 120},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="x",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="Procurement agents are not a toy anymore",
            text="Elite operators disagree on audit, permissions and ROI.",
            url="https://x.com/operator/status/2",
            author="operator",
            metrics={"like_count": 1200, "comment_count": 90},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
        RawSignal(
            platform="xiaohongshu",
            topic_id="agentic-workflow",
            topic_label="AI 业务流程智能体",
            title="AI 智能体采购自动化有人用吗",
            text="评论在问智能体能不能自动比价和整理供应商报价。",
            url="https://www.xiaohongshu.com/explore/xhs1",
            author="采购人",
            metrics={"like_count": 120, "comment_count": 18},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
    ]

    report = TrendRadarSynthesizer().build_report(
        signals,
        budget={"limit_usd": 2, "estimated_total_usd": 0.54},
        generated_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    item = report["items"][0]
    assert item["stackLayer"]["id"] == "infrastructure"
    assert item["stackLayer"]["label"] == "基础设施 / AI 工厂"
    assert item["needLayer"]["id"] == "safety"
    assert item["needLayer"]["label"] == "安全需求"
    assert "社会实际需求" in item["socialNeed"]
    assert "供给侧变化" in item["supplyShift"]
    assert item["counterEvidence"]
    assert item["opportunityType"] == "需求爆发"
    assert report["stack_summary"]["infrastructure"] == 1
    assert report["need_summary"]["safety"] == 1


def test_synthesizer_rejects_unverifiable_trending_noise():
    signals = [
        RawSignal(
            platform="x",
            topic_id="x-trending",
            topic_label="X 热门趋势",
            title="#holoSerendipity",
            text="#holoSerendipity",
            metrics={"like_count": 5000},
            captured_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
    ]

    report = TrendRadarSynthesizer().build_report(
        signals,
        budget={"limit_usd": 2, "estimated_total_usd": 0.1},
        generated_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    assert report["items"] == []
    assert report["summary"]["title"] == "本次没有足够可信的机会信号"
    assert report["diagnostics"]["discarded_signal_count"] == 1


def test_trend_radar_run_route_requires_budget_under_five(monkeypatch):
    from src.video_transcript_api.api.routes import trend_radar
    from src.video_transcript_api.api.services.transcription import verify_token

    app = FastAPI()
    app.include_router(trend_radar.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        "/api/trend-radar/reports/run",
        json={"budget_usd": 5.01},
    )

    assert response.status_code == 400
    assert "5" in response.json()["detail"]


def test_trend_radar_page_route_returns_static_shell():
    from src.video_transcript_api.api.routes import trend_radar

    app = FastAPI()
    app.include_router(trend_radar.router)
    client = TestClient(app)

    response = client.get("/trend-radar")

    assert response.status_code == 200
    assert "趋势机会雷达" in response.text
    assert "重新生成报告" in response.text


def test_trend_radar_run_route_starts_background_job(monkeypatch):
    from src.video_transcript_api.api.routes import trend_radar
    from src.video_transcript_api.api.services.transcription import verify_token

    captured = {}

    def fake_start_report_job(*, budget_usd, mode):
        captured["budget_usd"] = budget_usd
        captured["mode"] = mode
        return {
            "job_id": "trend-job-1",
            "status": "queued",
            "budget_usd": budget_usd,
            "mode": mode,
        }

    monkeypatch.setattr(trend_radar.svc, "start_report_job", fake_start_report_job)

    app = FastAPI()
    app.include_router(trend_radar.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.post(
        "/api/trend-radar/reports/run",
        json={"budget_usd": 4.5, "mode": "standard"},
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == "trend-job-1"
    assert response.json()["status"] == "queued"
    assert captured == {"budget_usd": 4.5, "mode": "standard"}


def test_trend_radar_job_route_returns_status(monkeypatch):
    from src.video_transcript_api.api.routes import trend_radar
    from src.video_transcript_api.api.services.transcription import verify_token

    monkeypatch.setattr(
        trend_radar.svc,
        "get_report_job",
        lambda job_id: {
            "job_id": job_id,
            "status": "completed",
            "report": {"report_id": "trend-1", "items": []},
        },
    )

    app = FastAPI()
    app.include_router(trend_radar.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.get("/api/trend-radar/jobs/trend-job-1")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["report"]["report_id"] == "trend-1"


def test_trend_radar_service_lists_recent_saved_reports(monkeypatch, tmp_path):
    old_report = {
        "report_id": "trend-old",
        "generated_at": "2026-07-04T08:00:00+00:00",
        "summary": {"title": "旧报告"},
        "metrics": {"new_window": 1},
        "budget": {"estimated_total_usd": 1.1},
        "raw_signal_count": 8,
        "items": [{"title": "旧机会"}],
    }
    new_report = {
        "report_id": "trend-new",
        "generated_at": "2026-07-05T08:00:00+00:00",
        "summary": {"title": "新报告"},
        "metrics": {"new_window": 2},
        "budget": {"estimated_total_usd": 1.3},
        "raw_signal_count": 12,
        "items": [{"title": "新机会"}, {"title": "第二机会"}],
    }
    (tmp_path / "trend-old.json").write_text(
        json.dumps(old_report, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "trend-new.json").write_text(
        json.dumps(new_report, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        trend_service,
        "load_config",
        lambda: {"trend_radar": {"report_dir": str(tmp_path)}},
    )

    result = trend_service.list_reports(limit=1)

    assert result["total"] == 2
    assert result["items"][0]["report_id"] == "trend-new"
    assert result["items"][0]["top_titles"] == ["新机会", "第二机会"]
    assert trend_service.read_report("trend-old")["summary"]["title"] == "旧报告"


def test_trend_radar_history_route_returns_recent_reports(monkeypatch):
    from src.video_transcript_api.api.routes import trend_radar
    from src.video_transcript_api.api.services.transcription import verify_token

    monkeypatch.setattr(
        trend_radar.svc,
        "list_reports",
        lambda limit=10: {
            "items": [
                {
                    "report_id": "trend-1",
                    "generated_at": "2026-07-05T08:00:00+00:00",
                    "top_titles": ["AI 采购"],
                }
            ],
            "total": 1,
        },
    )

    app = FastAPI()
    app.include_router(trend_radar.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "u1", "api_key": "test"}
    client = TestClient(app)

    response = client.get("/api/trend-radar/reports?limit=5")

    assert response.status_code == 200
    assert response.json()["items"][0]["report_id"] == "trend-1"
