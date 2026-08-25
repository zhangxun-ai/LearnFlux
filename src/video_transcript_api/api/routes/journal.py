from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ...journal import JournalRepository, JournalService
from ..context import (
    get_cache_manager,
    get_config,
    get_logger,
    get_repository_database,
)
from ..services.transcription import TranscribeResponse, verify_token

logger = get_logger()
cache_manager = get_cache_manager()

router = APIRouter(prefix="/api/journal", tags=["journal"])

EntryType = Literal[
    "daily",
    "note",
    "weekly_plan",
    "weekly_review",
    "monthly_plan",
    "monthly_review",
]


class JournalEntryRequest(BaseModel):
    entry_date: str = Field(..., min_length=10, max_length=10)
    entry_type: EntryType = "daily"
    title: str = Field("", max_length=200)
    body: str = Field("", max_length=50000)


class JournalReviewRequest(BaseModel):
    range_start: str = Field(..., min_length=10, max_length=10)
    range_end: str = Field(..., min_length=10, max_length=10)
    question: str = Field("", max_length=4000)


def get_journal_service() -> JournalService:
    return JournalService(
        repository=JournalRepository(
            db_path=get_repository_database(cache_manager)
        ),
        llm_config=get_config().get("llm", {}) or {},
    )


def _user_id(user_info: dict) -> str:
    return str(user_info.get("user_id") or user_info.get("api_key") or "default")


@router.get("/entry", response_model=TranscribeResponse)
async def get_journal_entry(
    entry_date: str = Query(..., min_length=10, max_length=10),
    entry_type: EntryType = Query("daily"),
    user_info: dict = Depends(verify_token),
):
    try:
        entry = get_journal_service().get_entry(_user_id(user_info), entry_date, entry_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TranscribeResponse(code=200, message="ok", data=entry)


@router.get("/entries", response_model=TranscribeResponse)
async def list_journal_entries(
    month: str | None = Query(None, min_length=7, max_length=7),
    start_date: str | None = Query(None, min_length=10, max_length=10),
    end_date: str | None = Query(None, min_length=10, max_length=10),
    entry_type: EntryType | None = Query(None),
    limit: int = Query(60, ge=1, le=200),
    user_info: dict = Depends(verify_token),
):
    try:
        entries = get_journal_service().list_entries(
            user_id=_user_id(user_info),
            month=month,
            start_date=start_date,
            end_date=end_date,
            entry_type=entry_type,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TranscribeResponse(code=200, message="ok", data={"items": entries})


@router.post("/entries", response_model=TranscribeResponse)
async def save_journal_entry(
    request: JournalEntryRequest,
    user_info: dict = Depends(verify_token),
):
    try:
        entry = get_journal_service().save_entry(
            user_id=_user_id(user_info),
            entry_date=request.entry_date,
            entry_type=request.entry_type,
            title=request.title,
            body=request.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TranscribeResponse(code=200, message="记录已保存", data=entry)


@router.get("/reviews", response_model=TranscribeResponse)
async def list_journal_reviews(
    limit: int = Query(20, ge=1, le=100),
    user_info: dict = Depends(verify_token),
):
    reviews = get_journal_service().list_reviews(_user_id(user_info), limit=limit)
    return TranscribeResponse(code=200, message="ok", data={"items": reviews})


@router.post("/reviews", response_model=TranscribeResponse)
async def create_journal_review(
    request: JournalReviewRequest,
    user_info: dict = Depends(verify_token),
):
    service = get_journal_service()
    try:
        review = await run_in_threadpool(
            service.review,
            _user_id(user_info),
            request.range_start,
            request.range_end,
            request.question,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("journal review failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI 复盘生成失败，请稍后重试")
    return TranscribeResponse(code=200, message="AI 复盘已生成", data=review)
