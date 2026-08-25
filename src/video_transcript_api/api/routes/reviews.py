"""FastAPI page and JSON contracts for the LearnFlux review module."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ...reviews import ReviewRepository, ReviewService
from ...reviews.repository import ReviewDataError
from ..context import get_cache_manager, get_config, get_repository_database, get_static_dir
from ..services.transcription import verify_token


router = APIRouter(tags=["reviews"])

MeaningType = Literal["", "discovery", "learning", "decision", "joy", "hunch", "custom"]
ConnectionType = Literal["direct", "indirect", "unexpected"]
InsightTier = Literal["branch", "trunk", "root"]


class DailyEventRequest(BaseModel):
    review_date: str | None = Field(default=None, min_length=10, max_length=10)
    position: int | None = Field(default=None, ge=0, le=1000)
    title: str | None = Field(default=None, max_length=300)
    fact: str | None = Field(default=None, max_length=20000)
    quick_meaning: str | None = Field(default=None, max_length=20000)
    meaning_type: MeaningType | None = None
    meaning_types: list[MeaningType] | None = Field(default=None, max_length=7)
    meaning_custom: str | None = Field(default=None, max_length=2000)
    people: list[str] | None = Field(default=None, max_length=100)
    keywords: list[str] | None = Field(default=None, max_length=100)
    past: dict[str, Any] | None = None
    present: dict[str, Any] | None = None
    emotions: list[dict[str, Any] | str] | None = Field(default=None, max_length=24)
    source_refs: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=32)


class DailyCreateRequest(DailyEventRequest):
    review_date: str = Field(min_length=10, max_length=10)


class DailyOrderRequest(BaseModel):
    review_date: str = Field(min_length=10, max_length=10)
    ids: list[str] = Field(min_length=1, max_length=500)


class WeeklyRequest(BaseModel):
    focus_ids: list[str] = Field(default_factory=list, max_length=3)
    abstraction: dict[str, str] = Field(default_factory=dict)
    summary: str = Field(default="", max_length=50000)
    source_ids: list[str] | None = Field(default=None, max_length=500)
    status: str = Field(default="draft", max_length=32)


class MonthlyRequest(BaseModel):
    inner: list[str] = Field(default_factory=list, max_length=40)
    actions: list[str] = Field(default_factory=list, max_length=40)
    results: list[str] = Field(default_factory=list, max_length=40)
    notes: list[str] = Field(default_factory=list, max_length=40)
    cross_month: list[dict[str, Any] | str] = Field(default_factory=list, max_length=40)
    affirmation: str = Field(default="", max_length=10000)
    source_ids: list[str] | None = Field(default=None, max_length=500)
    status: str = Field(default="draft", max_length=32)


class AnnualRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=100)
    summary: str = Field(default="", max_length=50000)
    cross_month: list[dict[str, Any] | str] = Field(default_factory=list, max_length=100)
    source_ids: list[str] | None = Field(default=None, max_length=100)
    status: str = Field(default="draft", max_length=32)


class ConnectionRequest(BaseModel):
    period_type: str = Field(default="weekly", max_length=24)
    period_key: str = Field(min_length=4, max_length=20)
    connection_type: ConnectionType = "direct"
    source_type: str = Field(default="daily", min_length=1, max_length=24)
    source_id: str = Field(default="", max_length=128)
    target_type: str = Field(default="daily", min_length=1, max_length=24)
    target_id: str = Field(default="", max_length=128)
    direction: Literal["forward", "reverse", "bidirectional"] = "forward"
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=20000)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    status: str = Field(default="active", max_length=32)


class ConnectionPatchRequest(BaseModel):
    connection_type: ConnectionType | None = None
    source_type: str | None = Field(default=None, min_length=1, max_length=24)
    source_id: str | None = Field(default=None, max_length=128)
    target_type: str | None = Field(default=None, min_length=1, max_length=24)
    target_id: str | None = Field(default=None, max_length=128)
    direction: Literal["forward", "reverse", "bidirectional"] | None = None
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    source_ids: list[str] | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=32)


class ExperimentRequest(BaseModel):
    period_key: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=300)
    why: str = Field(default="", max_length=10000)
    what: str = Field(default="", max_length=10000)
    who: str = Field(default="", max_length=2000)
    when: str = Field(default="", max_length=2000)
    where: str = Field(default="", max_length=2000)
    how: str = Field(default="", max_length=10000)
    resources: str = Field(default="", max_length=5000)
    budget: str = Field(default="", max_length=2000)
    success_signal: str = Field(default="", max_length=5000)
    desire_check: Literal["", "yes", "no", "unsure"] = ""
    control_check: Literal["", "yes", "no", "partial", "unsure"] = ""
    first_step: str = Field(default="", max_length=5000)
    review_date: str | None = Field(default=None, max_length=10)
    result: str = Field(default="", max_length=20000)
    executed: Literal["", "yes", "no", "partial"] = ""
    insight_result: str = Field(default="", max_length=10000)
    next_decision: Literal["", "continue", "adjust", "stop"] = ""
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    status: str = Field(default="planned", max_length=32)


class InsightRequest(BaseModel):
    tier: InsightTier = "branch"
    level: int = Field(default=1, ge=1, le=8)
    category: str = Field(default="", max_length=80)
    statement: str = Field(min_length=1, max_length=20000)
    evidence: list[dict[str, Any] | str] = Field(default_factory=list, max_length=100)
    counter_evidence: list[dict[str, Any] | str] = Field(default_factory=list, max_length=100)
    uncertainty: float = Field(default=0.5, ge=0, le=1)
    uncertainty_note: str = Field(default="", max_length=5000)
    evidence_span: dict[str, Any] = Field(default_factory=dict)
    evidence_strength: dict[str, Any] = Field(default_factory=dict)
    verification_experiment: str = Field(default="", max_length=10000)
    verification_experiment_id: str | None = Field(default=None, max_length=128)
    source_ids: list[dict[str, Any] | str] = Field(default_factory=list, max_length=100)
    status: str = Field(default="pending", max_length=32)


class InsightPatchRequest(BaseModel):
    tier: InsightTier | None = None
    level: int | None = Field(default=None, ge=1, le=8)
    category: str | None = Field(default=None, max_length=80)
    statement: str | None = Field(default=None, min_length=1, max_length=20000)
    evidence: list[dict[str, Any] | str] | None = Field(default=None, max_length=100)
    counter_evidence: list[dict[str, Any] | str] | None = Field(default=None, max_length=100)
    uncertainty: float | None = Field(default=None, ge=0, le=1)
    uncertainty_note: str | None = Field(default=None, max_length=5000)
    evidence_span: dict[str, Any] | None = None
    evidence_strength: dict[str, Any] | None = None
    verification_experiment: str | None = Field(default=None, max_length=10000)
    verification_experiment_id: str | None = Field(default=None, max_length=128)
    source_ids: list[dict[str, Any] | str] | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=32)


class AIReference(BaseModel):
    type: str = Field(min_length=1, max_length=24)
    id: str = Field(min_length=1, max_length=128)


class AIAnalyzeRequest(BaseModel):
    analysis_type: str = Field(min_length=1, max_length=40)
    purpose: str = Field(default="", max_length=2000)
    scope: list[AIReference] = Field(min_length=1, max_length=60)


class AIConfirmRequest(BaseModel):
    content: dict[str, Any] | None = None
    create_insight: bool = False


class PreferencesRequest(BaseModel):
    newbie_mode: bool | None = None
    week_start_day: int | None = Field(default=None, ge=0, le=6)
    obsidian_root: str | None = Field(default=None, min_length=1, max_length=120)


class SyncRequest(BaseModel):
    record_type: Literal["daily", "weekly", "monthly", "annual", "insight", "experiment"]
    record_id: str = Field(min_length=1, max_length=128)


def _owner_id(user_info: dict) -> str:
    owner = str(user_info.get("user_id") or user_info.get("api_key") or "default").strip()
    if not owner:
        raise HTTPException(status_code=401, detail="用户身份无效")
    return owner


def get_review_service() -> ReviewService:
    return ReviewService(
        repository=ReviewRepository(get_repository_database(get_cache_manager())),
        config=get_config(),
    )


def review_service_dependency() -> Generator[ReviewService, None, None]:
    service = get_review_service()
    try:
        yield service
    finally:
        service.close()


def _ok(data: Any, message: str = "success", code: int = 200) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True)


@router.get("/review", response_class=HTMLResponse, include_in_schema=False)
@router.get("/review/{section}", response_class=HTMLResponse, include_in_schema=False)
async def review_page(section: str | None = None):
    static_dir = get_static_dir()
    page = static_dir / "review.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="复盘页面不存在")
    version_files = [
        page,
        static_dir / "css" / "review.css",
        static_dir / "css" / "app-shell.css",
        static_dir / "css" / "product-linear.css",
        static_dir / "css" / "product-linear-core.css",
        static_dir / "js" / "review.js",
        static_dir / "js" / "app-shell.js",
        static_dir / "js" / "ui-features.js",
    ]
    version = str(max((path.stat().st_mtime_ns for path in version_files if path.exists()), default=0))
    return HTMLResponse(
        page.read_text(encoding="utf-8").replace("__ASSET_VERSION__", version),
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/reviews/daily-events")
async def list_daily_events(
    date: str | None = Query(default=None, min_length=10, max_length=10),
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.daily(_owner_id(user_info), date))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/api/reviews/daily-events", status_code=201)
async def create_daily_event(
    request: DailyCreateRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        data = service.create_daily(_owner_id(user_info), request.review_date, _payload(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _ok(data, "复盘事件已创建", 201)


@router.patch("/api/reviews/daily-events/{event_id}")
async def update_daily_event(
    event_id: str,
    request: DailyEventRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        data = service.update_daily(_owner_id(user_info), event_id, _payload(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if data is None:
        raise HTTPException(status_code=404, detail="复盘事件不存在")
    return _ok(data, "复盘事件已保存")


@router.delete("/api/reviews/daily-events/{event_id}")
async def delete_daily_event(
    event_id: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    deleted = service.repository.delete_daily_event(_owner_id(user_info), event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="复盘事件不存在")
    return _ok({"deleted": True}, "复盘事件已删除")


@router.post("/api/reviews/daily-events/{event_id}/duplicate", status_code=201)
async def duplicate_daily_event(
    event_id: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    data = service.duplicate_daily(_owner_id(user_info), event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="复盘事件不存在")
    return _ok(data, "复盘事件已复制", 201)


@router.put("/api/reviews/daily-events-order")
async def reorder_daily_events(
    request: DailyOrderRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        items = service.repository.reorder_daily_events(
            _owner_id(user_info), request.review_date, request.ids
        )
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _ok({"items": items})


@router.get("/api/reviews/weekly/{anchor}")
async def get_weekly_review(
    anchor: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.weekly(_owner_id(user_info), anchor))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/api/reviews/weekly/{anchor}")
async def save_weekly_review(
    anchor: str,
    request: WeeklyRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.save_weekly(_owner_id(user_info), anchor, _payload(request)), "周度复盘已保存")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/api/reviews/monthly/{month}")
async def get_monthly_review(
    month: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.monthly(_owner_id(user_info), month))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/api/reviews/monthly/{month}")
async def save_monthly_review(
    month: str,
    request: MonthlyRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.save_monthly(_owner_id(user_info), month, _payload(request)), "月度复盘已保存")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/api/reviews/annual/{year}")
async def get_annual_review(
    year: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.annual(_owner_id(user_info), year))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/api/reviews/annual/{year}")
async def save_annual_review(
    year: str,
    request: AnnualRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        return _ok(service.save_annual(_owner_id(user_info), year, _payload(request)), "年度复盘已保存")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/api/reviews/connections")
async def list_connections(
    period_type: str | None = None,
    period_key: str | None = None,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    items = service.repository.list_connections(
        _owner_id(user_info), period_type=period_type, period_key=period_key
    )
    return _ok({"items": items})


@router.post("/api/reviews/connections", status_code=201)
async def create_connection(
    request: ConnectionRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        item = service.repository.create_connection(_owner_id(user_info), _payload(request))
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _ok(item, "连接已创建", 201)


@router.patch("/api/reviews/connections/{connection_id}")
async def update_connection(
    connection_id: str,
    request: ConnectionPatchRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        item = service.repository.update_connection(
            _owner_id(user_info), connection_id, _payload(request)
        )
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if item is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    return _ok(item, "连接已保存")


@router.delete("/api/reviews/connections/{connection_id}")
async def delete_connection(
    connection_id: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    if not service.repository.delete_connection(_owner_id(user_info), connection_id):
        raise HTTPException(status_code=404, detail="连接不存在")
    return _ok({"deleted": True}, "连接已删除")


@router.get("/api/reviews/action-experiments")
async def list_experiments(
    period_key: str | None = None,
    status: str | None = None,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    return _ok({"items": service.repository.list_experiments(
        _owner_id(user_info), period_key=period_key, status=status
    )})


@router.post("/api/reviews/action-experiments", status_code=201)
async def create_experiment(
    request: ExperimentRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    owner = _owner_id(user_info)
    return _ok(service.create_experiment(owner, _payload(request)), "行动实验已创建", 201)


@router.patch("/api/reviews/action-experiments/{experiment_id}")
async def update_experiment(
    experiment_id: str,
    request: ExperimentRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    owner = _owner_id(user_info)
    result = service.update_experiment(owner, experiment_id, _payload(request))
    if result is None:
        raise HTTPException(status_code=404, detail="行动实验不存在")
    return _ok(result, "行动实验已保存")


@router.delete("/api/reviews/action-experiments/{experiment_id}")
async def delete_experiment(
    experiment_id: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    if not service.delete_experiment(_owner_id(user_info), experiment_id):
        raise HTTPException(status_code=404, detail="行动实验不存在")
    return _ok({"deleted": True}, "行动实验已删除")


@router.get("/api/reviews/insights")
async def list_insights(
    tier: InsightTier | None = None,
    status: str | None = None,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    items = service.repository.list_insights(_owner_id(user_info), tier=tier, status=status)
    return _ok({
        "items": items,
        "overview": service.repository.evidence_overview(_owner_id(user_info)),
        "recent_sources": service.repository.list_daily_events(
            _owner_id(user_info), limit=30
        ),
    })


@router.post("/api/reviews/insights", status_code=201)
async def create_insight(
    request: InsightRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    owner = _owner_id(user_info)
    try:
        item = service.create_insight(owner, _payload(request))
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _ok({"record": item, "sync": service.syncer.sync(owner, "insight", item["id"])}, "洞察已创建", 201)


@router.patch("/api/reviews/insights/{insight_id}")
async def update_insight(
    insight_id: str,
    request: InsightPatchRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    owner = _owner_id(user_info)
    item = service.repository.update_insight(owner, insight_id, _payload(request))
    if item is None:
        raise HTTPException(status_code=404, detail="洞察不存在")
    return _ok({"record": item, "sync": service.syncer.sync(owner, "insight", insight_id)}, "洞察已保存")


@router.post("/api/reviews/ai/scope")
async def describe_ai_scope(
    request: AIAnalyzeRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    del user_info
    try:
        data = service.ai.describe_scope(request.analysis_type, [item.model_dump() for item in request.scope])
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _ok(data)


@router.post("/api/reviews/ai/analyze")
async def analyze_reviews(
    request: AIAnalyzeRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        items = await run_in_threadpool(
            service.ai.analyze,
            _owner_id(user_info),
            request.analysis_type,
            [item.model_dump() for item in request.scope],
            request.purpose,
        )
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 复盘失败：{exc}") from None
    return _ok({"items": items}, "AI 候选已生成")


@router.post("/api/reviews/ai-candidates/{candidate_id}/confirm")
async def confirm_ai_candidate(
    candidate_id: str,
    request: AIConfirmRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    data = service.confirm_ai(
        _owner_id(user_info), candidate_id, request.content, create_insight=request.create_insight
    )
    if data is None:
        raise HTTPException(status_code=404, detail="AI 候选不存在或已处理")
    return _ok(data, "AI 候选已由用户确认")


@router.post("/api/reviews/ai-candidates/{candidate_id}/dismiss")
async def dismiss_ai_candidate(
    candidate_id: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    item = service.repository.dismiss_ai_candidate(_owner_id(user_info), candidate_id)
    if item is None:
        raise HTTPException(status_code=404, detail="AI 候选不存在")
    return _ok(item, "AI 候选已忽略")


@router.get("/api/reviews/search")
async def search_reviews(
    keyword: str = Query(default="", max_length=200),
    start_date: str | None = Query(default=None, max_length=10),
    end_date: str | None = Query(default=None, max_length=10),
    record_type: list[str] = Query(default=[]),
    meaning_type: str | None = Query(default=None, max_length=32),
    emotion: str | None = Query(default=None, max_length=80),
    insight_tier: InsightTier | None = Query(default=None),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=200),
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    items = service.repository.search(
        _owner_id(user_info), keyword=keyword, start_date=start_date, end_date=end_date,
        record_types=record_type, meaning_type=meaning_type, emotion=emotion,
        insight_tier=insight_tier, status=status, limit=limit,
    )
    return _ok({"items": items, "total": len(items)})


@router.get("/api/reviews/source/{source_type}/{source_id}")
async def trace_review_source(
    source_type: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    item = service.source_trace(_owner_id(user_info), source_type, source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="来源记录不存在")
    return _ok(item)


@router.get("/api/reviews/preferences")
async def get_review_preferences(
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    return _ok(service.repository.get_preferences(_owner_id(user_info)))


@router.put("/api/reviews/preferences")
async def save_review_preferences(
    request: PreferencesRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    try:
        item = service.repository.save_preferences(_owner_id(user_info), _payload(request))
    except ReviewDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _ok(item, "复盘偏好已保存")


@router.get("/api/reviews/sync-status")
async def list_review_sync_status(
    status: str | None = None,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    items = service.repository.list_sync_states(_owner_id(user_info), status=status, limit=200)
    return _ok({"configuration": service.syncer.configuration_status(), "items": items})


@router.post("/api/reviews/sync")
async def sync_review_record(
    request: SyncRequest,
    user_info: dict = Depends(verify_token),
    service: ReviewService = Depends(review_service_dependency),
):
    data = service.syncer.sync(_owner_id(user_info), request.record_type, request.record_id)
    if data.get("status") == "failed" and str(data.get("error_message") or "").startswith("record_not_found"):
        raise HTTPException(status_code=404, detail="复盘记录不存在")
    return _ok(data, "同步已执行")


__all__ = ["router", "get_review_service", "review_service_dependency"]
