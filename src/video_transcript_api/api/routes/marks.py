from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from ...marks import ContentMarkRepository
from ..context import (
    get_audit_logger,
    get_cache_manager,
    get_repository_database,
)
from ..services.transcription import TranscribeResponse, verify_token

cache_manager = get_cache_manager()
audit_logger = get_audit_logger()

router = APIRouter(prefix="/api/marks", tags=["marks"])


@lru_cache
def get_marks_repository() -> ContentMarkRepository:
    return ContentMarkRepository(
        db_path=get_repository_database(cache_manager)
    )


def _user_key(user_info: dict) -> str:
    return audit_logger._mask_api_key(user_info.get("api_key", ""))


def _ensure_transcript_exists(view_token: str):
    if not cache_manager.get_task_by_view_token(view_token):
        raise HTTPException(status_code=404, detail="解读不存在")


@router.get("/transcripts/{view_token}", response_model=TranscribeResponse)
async def get_transcript_mark(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    _ensure_transcript_exists(view_token)
    mark = get_marks_repository().get_mark(
        owner_type="transcript",
        owner_id=view_token,
        user_key=_user_key(user_info),
    )
    return TranscribeResponse(
        code=200,
        message="ok",
        data={"marked": mark is not None, "mark": mark},
    )


@router.post("/transcripts/{view_token}", response_model=TranscribeResponse)
async def mark_transcript(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    _ensure_transcript_exists(view_token)
    mark = get_marks_repository().mark(
        owner_type="transcript",
        owner_id=view_token,
        user_key=_user_key(user_info),
    )
    return TranscribeResponse(
        code=200,
        message="已标记为精华",
        data={"marked": True, "mark": mark},
    )


@router.delete("/transcripts/{view_token}", response_model=TranscribeResponse)
async def unmark_transcript(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    _ensure_transcript_exists(view_token)
    get_marks_repository().unmark(
        owner_type="transcript",
        owner_id=view_token,
        user_key=_user_key(user_info),
    )
    return TranscribeResponse(
        code=200,
        message="已取消精华标记",
        data={"marked": False, "mark": None},
    )
