"""Authenticated, manual image-diagram endpoints and private image delivery."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..context import get_audit_logger, get_cache_manager, get_config, get_repository_database, get_user_manager
from ..services.transcription import verify_token
from ...document_sources.feishu import FeishuDocumentError, parse_feishu_url, require_feishu_access
from ...image_diagrams.client import OpenAIImageDiagramClient
from ...image_diagrams.config import ImageDiagramSettings
from ...image_diagrams.repository import ImageDiagramRepository
from ...image_diagrams.service import ERROR_MESSAGES, ImageDiagramService
from ...image_diagrams.source import snapshot_session
from ...study.repository import StudyRepository
from ...study.service import StudyService
from ...study.transcript import normalize_transcript


router = APIRouter(prefix="/api/image-diagrams", tags=["image-diagrams"])


class ImageDiagramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scope: Literal["overview", "section"] = "overview"
    section_id: str | None = Field(None, pattern=r"^section-[1-9][0-9]{0,5}$")
    style: Literal["warm-guide", "handdrawn"] = "warm-guide"
    instructions: str = Field("", max_length=2000)
    revision_of: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")
    request_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    regenerate: bool = False


def require_source_access(view_token: str, owner_user_id: str) -> dict:
    """Authorize metadata before loading even a cached private source."""
    manager = get_cache_manager()
    task = manager.get_task_by_view_token(view_token)
    if not isinstance(task, dict) or not task.get("task_id"):
        raise HTTPException(status_code=404, detail="学习内容不存在")
    user = get_user_manager().get_user_by_id(owner_user_id)
    if not user or not user.get("enabled", True):
        raise HTTPException(status_code=403, detail="当前账号不可使用这份内容")
    owner = task.get("owner_user_id")
    if owner:
        if owner != owner_user_id:
            raise HTTPException(status_code=404, detail="学习内容不存在")
    elif not (user.get("is_legacy") or owner_user_id == "legacy_user"):
        owned = {row.get("task_id") for row in get_audit_logger().get_recent_calls(
            user_id=owner_user_id, limit=10000,
        )}
        if task["task_id"] not in owned:
            raise HTTPException(status_code=404, detail="学习内容不存在")
    if task.get("status") in {"canceled", "cancelled"}:
        raise HTTPException(status_code=409, detail="任务已取消，未开始图解生成")
    if str(task.get("platform") or "").lower() == "feishu" or parse_feishu_url(task.get("url") or ""):
        try:
            require_feishu_access(get_config().get("feishu_documents") or {}, task)
        except FeishuDocumentError:
            raise HTTPException(status_code=403, detail="当前身份未获准读取这份飞书资料") from None
    return task


@lru_cache
def get_image_diagram_service() -> ImageDiagramService:
    config, manager = get_config(), get_cache_manager()
    settings = ImageDiagramSettings.from_config(config)
    database = get_repository_database(manager)
    study = StudyService(
        cache_manager=manager, repository=StudyRepository(database),
        source_root=(config.get("storage") or {}).get("source_files_dir") or "./data/source_files",
        llm_config=config.get("llm") or {},
    )

    def load_source(view_token: str) -> dict:
        session = study.get_session(view_token)
        if session is None:
            raise ValueError("source_not_ready")
        view = manager.get_view_data_by_token(view_token) or {}
        calibrated = view.get("llm_calibrated")
        if isinstance(calibrated, str) and calibrated.strip():
            session = {**session, "transcript": {"lines": normalize_transcript(calibrated)}}
        source = snapshot_session(session)
        source["source_type"] = "calibrated" if calibrated else "original"
        return source

    return ImageDiagramService(
        repository=ImageDiagramRepository(database), settings=settings,
        client=OpenAIImageDiagramClient(settings) if settings.enabled else None, source_loader=load_source,
        authorize=require_source_access,
    )


def response(data: dict, status: int = 200):
    return JSONResponse({"code": status, "message": "success", "data": data},
                        status_code=status, headers={"Cache-Control": "no-store"})


def source_token(view_token: str) -> str:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", view_token):
        raise HTTPException(status_code=404, detail="学习内容不存在")
    return view_token


@router.get("/study/{view_token}")
async def get_image_state(view_token: str, user: dict = Depends(verify_token)):
    service = get_image_diagram_service()
    return response(await run_in_threadpool(service.state, source_token(view_token), user["user_id"]))


@router.post("/study/{view_token}/generate")
async def generate_image(view_token: str, request: ImageDiagramRequest, user: dict = Depends(verify_token)):
    if request.scope == "section" and not request.section_id:
        raise HTTPException(status_code=422, detail="请选择需要生成的章节")
    if request.scope == "overview" and request.section_id is not None:
        raise HTTPException(status_code=422, detail="总览图无需选择章节")
    service = get_image_diagram_service()
    try:
        record = await run_in_threadpool(service.prepare, source_token(view_token), user["user_id"], request.model_dump())
    except ValueError as exc:
        code = str(exc)
        status = 429 if code == "image_diagram_daily_limit" else 409 if "conflict" in code else 400
        raise HTTPException(status_code=status, detail=ERROR_MESSAGES.get(code, "无法生成，请刷新后检查所选内容和图解配置")) from None
    service.start()
    return response(service.public(record), 202 if record["status"] in {"queued", "planning", "generating", "reviewing"} else 200)


async def owned_job(job_id: str, user: dict) -> tuple:
    service = get_image_diagram_service()
    try:
        record = await run_in_threadpool(service.get_owned, job_id, user["user_id"])
    except LookupError:
        raise HTTPException(status_code=404, detail="图解不存在") from None
    return service, record


@router.get("/jobs/{job_id}")
async def get_image_job(job_id: str, user: dict = Depends(verify_token)):
    service, record = await owned_job(job_id, user)
    return response(service.public(record))


@router.get("/jobs/{job_id}/image")
async def get_image_file(job_id: str, download: bool = False, user: dict = Depends(verify_token)):
    service, record = await owned_job(job_id, user)
    if not record.get("image_key"):
        raise HTTPException(status_code=404, detail="图片尚未就绪")
    try:
        path = service.artifacts.image_path(record["image_key"])
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="图片暂不可用，请保留现有任务并检查存储") from None
    return FileResponse(path, media_type="image/png",
                        filename=f"learnflux-diagram-{job_id[:8]}.png" if download else None,
                        content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
