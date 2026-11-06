import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from ..context import (
    get_audit_logger,
    get_cache_manager,
    get_config,
    get_logger,
    get_repository_database,
    get_user_manager,
)
from ..services.transcription import TranscribeResponse, process_local_upload, verify_token
from ..services.source_preservation import PDFTextLimitExceeded, extract_pdf_text
from ...collections.titles import source_basename
from ...obsidian.service import (
    ObsidianConflict,
    ObsidianSyncError,
    StudySyncContext,
)
from ...study.repository import StudyRepository, StudyRevisionConflict
from ...study.library import StudyLibraryService
from ...study.media_access import StudyMediaAccess
from ...study.service import StudyService
from ...study.source_files import (
    build_study_source_path,
    describe_study_source,
    media_type_for_filename,
    safe_extension,
)
from .collections import get_collection_service
from .obsidian import get_obsidian_sync_service

router = APIRouter(prefix="/api/study", tags=["study"])

config = get_config()
logger = get_logger()
cache_manager = get_cache_manager()
audit_logger = get_audit_logger()
user_manager = get_user_manager()

_UPLOAD_MAX_MB = int((config.get("upload") or {}).get("max_mb", 20480))
_UPLOAD_MAX_BYTES = _UPLOAD_MAX_MB * 1024 * 1024
_STUDY_TEXT_MAX_CHARS = 200_000
_PDF_UPLOAD_MAX_FILES = 20
_PDF_UPLOAD_MAX_BYTES = min(_UPLOAD_MAX_BYTES, 100 * 1024 * 1024)


class StudyNoteRequest(BaseModel):
    time_seconds: float | None = Field(None, ge=0)
    body: str = Field(..., min_length=1, max_length=20000)


class StudyChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=12000)


class StudyChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    time_seconds: float | None = Field(None, ge=0)
    history: list[StudyChatMessage] = Field(default_factory=list, max_length=12)


class StudyCompareRequest(StudyChatRequest):
    view_tokens: list[str] = Field(..., min_length=2, max_length=5)

    @field_validator("view_tokens")
    @classmethod
    def validate_sources(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in values):
            raise ValueError("Invalid source identity")
        if len(set(values)) != len(values):
            raise ValueError("请选择不同的资料")
        return values


class StudyTextRequest(BaseModel):
    title: str = Field(default="", max_length=160)
    content: str = Field(..., min_length=1, max_length=_STUDY_TEXT_MAX_CHARS)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_text_fields(cls, value):
        return str(value or "").strip()


class StudyNoteDocumentRequest(BaseModel):
    body: str = Field(default="", max_length=500000)
    expected_revision: int = Field(..., ge=1)


class ObsidianBindingRequest(BaseModel):
    transcript_directory: str = Field(..., min_length=1, max_length=500)
    note_directory: str = Field(..., min_length=1, max_length=500)
    expected_revision: int | None = Field(None, ge=1)


class ObsidianConflictResolutionRequest(BaseModel):
    choice: Literal[
        "app",
        "obsidian",
        "recreate_from_app",
        "accept_external_deletion",
    ]
    expected_revision: int = Field(..., ge=1)
    expected_obsidian_hash: str = Field(..., min_length=1, max_length=128)
    expected_baseline_hash: str | None = Field(None, max_length=128)


def get_source_root() -> Path:
    storage_cfg = config.get("storage", {}) or {}
    return Path(storage_cfg.get("source_files_dir") or "./data/source_files")


def get_study_service() -> StudyService:
    return StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(
            db_path=get_repository_database(cache_manager)
        ),
        source_root=get_source_root(),
        llm_config=config.get("llm", {}) or {},
    )


def get_study_library_service() -> StudyLibraryService:
    return StudyLibraryService(
        cache_manager=cache_manager,
        audit_logger=audit_logger,
        source_root=get_source_root(),
        collection_service=get_collection_service(),
    )


def get_study_media_access() -> StudyMediaAccess:
    signing_secret = (
        (config.get("study") or {}).get("media_signing_secret")
        or (config.get("api") or {}).get("auth_token")
        or ""
    )
    return StudyMediaAccess(secret=signing_secret)


def _get_owned_collection_context(collection_id: str, source_id: str, user_info: dict):
    service = get_collection_service()
    collection = service.repository.get_collection(collection_id)
    if not collection or (collection.get("owner_user_id") or "") != (user_info.get("user_id") or ""):
        raise HTTPException(status_code=404, detail="学习合集不存在")
    try:
        source = service.get_source_detail(collection_id, source_id)
        detail = service.get_collection_detail(collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return service, detail, source


def _require_owned_single(view_token: str, user_info: dict) -> None:
    if not user_manager.is_multi_user_mode():
        return
    task = cache_manager.get_task_by_view_token(view_token) or {}
    task_id = task.get("task_id")
    owned_task_ids = {
        row.get("task_id")
        for row in audit_logger.get_recent_calls(
            user_id=user_info.get("user_id") or "",
            limit=10000,
        )
    }
    if not task_id or task_id not in owned_task_ids:
        raise HTTPException(status_code=404, detail="学习内容不存在")


def _require_comparison_sources(view_tokens: list[str], user_info: dict) -> None:
    """Authorize every selected source before loading any transcript or cache."""
    from ...document_sources.feishu import FeishuDocumentError, require_feishu_access

    legacy_ids = None
    for token in view_tokens:
        task = cache_manager.get_task_by_view_token(token) or {}
        if not isinstance(task, dict) or not task.get("task_id"):
            raise HTTPException(status_code=404, detail="学习内容不存在")
        owner = task.get("owner_user_id")
        if owner is not None:
            if owner != user_info.get("user_id"):
                raise HTTPException(status_code=404, detail="学习内容不存在")
        elif not (user_info.get("is_legacy") or user_info.get("user_id") == "legacy_user"):
            if legacy_ids is None:
                legacy_ids = {row.get("task_id") for row in audit_logger.get_recent_calls(
                    user_id=user_info.get("user_id") or "", limit=10000,
                )}
            if task["task_id"] not in legacy_ids:
                raise HTTPException(status_code=404, detail="学习内容不存在")
        if str(task.get("platform") or "").lower() == "feishu":
            try:
                require_feishu_access(config.get("feishu_documents") or {}, task)
            except FeishuDocumentError:
                raise HTTPException(status_code=403, detail="当前身份未获准读取这份飞书资料") from None


@router.post("/compare", response_model=TranscribeResponse)
async def compare_study_sources(
    request: StudyCompareRequest, user_info: dict = Depends(verify_token),
):
    await run_in_threadpool(_require_comparison_sources, request.view_tokens, user_info)
    try:
        result = await run_in_threadpool(
            get_study_service().compare_sources, request.view_tokens, request.question,
            [item.model_dump() for item in request.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception:
        logger.exception("Source comparison failed")
        raise HTTPException(status_code=502, detail="对照回答生成失败，请稍后重试") from None
    return TranscribeResponse(code=200, message="对照回答已生成", data=result)


def _single_obsidian_context(view_token: str, user_info: dict) -> StudySyncContext:
    _require_owned_single(view_token, user_info)
    session = get_study_service().get_session(view_token)
    if not session:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    metadata = session.get("metadata") or {}
    return StudySyncContext(
        owner_user_id=user_info.get("user_id") or "",
        view_token=view_token,
        title=metadata.get("title") or "未命名课程",
        course="",
        transcript_lines=((session.get("transcript") or {}).get("lines") or []),
    )


def _collection_obsidian_context(
    collection_id: str,
    source_id: str,
    user_info: dict,
) -> StudySyncContext:
    _, detail, source = _get_owned_collection_context(
        collection_id, source_id, user_info
    )
    view_token = source.get("view_token") or ""
    session = get_study_service().get_collection_session(
        view_token,
        owner_user_id=user_info.get("user_id") or "",
        collection_id=collection_id,
        source_id=source_id,
    )
    if not session:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    metadata = session.get("metadata") or {}
    return StudySyncContext(
        owner_user_id=user_info.get("user_id") or "",
        view_token=view_token,
        title=metadata.get("title") or source.get("title") or "未命名课程",
        course=detail.get("title") or "学习合集",
        transcript_lines=((session.get("transcript") or {}).get("lines") or []),
        collection_id=collection_id,
        source_id=source_id,
    )


def _collection_binding_context(
    collection_id: str,
    user_info: dict,
) -> StudySyncContext:
    collection_service = get_collection_service()
    collection = collection_service.repository.get_collection(collection_id)
    if not collection or (collection.get("owner_user_id") or "") != (
        user_info.get("user_id") or ""
    ):
        raise HTTPException(status_code=404, detail="学习合集不存在")
    try:
        detail = collection_service.get_collection_detail(collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return StudySyncContext(
        owner_user_id=user_info.get("user_id") or "",
        view_token="",
        title=detail.get("title") or "学习合集",
        course=detail.get("title") or "学习合集",
        transcript_lines=[],
        collection_id=collection_id,
    )


def _raise_obsidian_http_error(exc: Exception) -> None:
    if isinstance(exc, StudyRevisionConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "revision_conflict", "current": exc.current},
        )
    if isinstance(exc, ObsidianConflict):
        raise HTTPException(status_code=409, detail=exc.payload)
    if isinstance(exc, ObsidianSyncError):
        status_code = 409 if exc.code in {
            "binding_required",
            "binding_directory_missing",
            "conflict_not_found",
            "invalid_conflict_choice",
        } else 400
        raise HTTPException(status_code=status_code, detail={"code": exc.code})
    raise exc


def _note_document_response(context: StudySyncContext):
    try:
        result = get_obsidian_sync_service().load_note(context)
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    if result.get("conflict"):
        raise HTTPException(status_code=409, detail=result["conflict"])
    return TranscribeResponse(code=200, message="课程笔记", data=result)


def _save_note_document_response(
    context: StudySyncContext,
    request: StudyNoteDocumentRequest,
):
    try:
        document = get_obsidian_sync_service().save_note(
            context,
            body=request.body,
            expected_revision=request.expected_revision,
        )
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    return TranscribeResponse(code=200, message="课程笔记已保存", data=document)


def _sync_response(context: StudySyncContext):
    try:
        result = get_obsidian_sync_service().sync(context)
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    if result.get("overall") == "binding_required":
        raise HTTPException(status_code=409, detail={"code": "binding_required"})
    status_code = {"success": 200, "partial": 207, "failed": 500}.get(
        result.get("overall"), 500
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "code": status_code,
            "message": "Obsidian sync result",
            "data": result,
        },
    )


def _resolve_conflict_response(
    context: StudySyncContext,
    request: ObsidianConflictResolutionRequest,
):
    try:
        result = get_obsidian_sync_service().resolve_conflict(
            context,
            choice=request.choice,
            expected_revision=request.expected_revision,
            expected_obsidian_hash=request.expected_obsidian_hash,
            expected_baseline_hash=request.expected_baseline_hash,
        )
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    return TranscribeResponse(code=200, message="Obsidian conflict resolved", data=result)


def _collection_episode_data(detail: dict, source_id: str) -> dict:
    sources = sorted(
        detail.get("sources") or [],
        key=lambda item: (int(item.get("position") or 0), item.get("title") or ""),
    )
    return {
        "id": detail.get("id"),
        "title": detail.get("title") or "学习合集",
        "current_source_id": source_id,
        "sources": [
            {
                "id": item.get("id"),
                "title": item.get("title") or "未命名内容",
                "position": item.get("position"),
                "state": item.get("task_status") or "queued",
                "study_url": (
                    f"/study/collections/{quote(str(detail.get('id') or ''))}"
                    f"/sources/{quote(str(item.get('id') or ''))}"
                ),
            }
            for item in sources
        ],
    }


@router.get("/library", response_model=TranscribeResponse)
async def get_study_library(
    kind: Literal["single", "collection"] = Query("single"),
    q: str = Query("", max_length=160),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_info: dict = Depends(verify_token),
):
    data = get_study_library_service().list(
        kind=kind,
        user_id=user_info.get("user_id") or "",
        q=q,
        limit=limit,
        offset=offset,
    )
    return TranscribeResponse(code=200, message="可播放学习内容", data=data)


@router.get(
    "/collections/{collection_id}/sources/{source_id}",
    response_model=TranscribeResponse,
)
async def get_collection_study_session(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    collection_service, detail, source = _get_owned_collection_context(
        collection_id, source_id, user_info
    )
    view_token = source.get("view_token") or ""
    session = get_study_service().get_collection_session(
        view_token,
        owner_user_id=user_info.get("user_id") or "",
        collection_id=collection_id,
        source_id=source_id,
    )
    if not session:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    playback = session.get("playback") or {}
    try:
        source_path = collection_service.get_source_file_path(collection_id, source_id)
    except ValueError:
        source_path = None
    collection_source_file = Path(source_path) if source_path else None
    if collection_source_file and collection_source_file.is_file():
        playback["source_available"] = True
        playback["unavailable_reason"] = ""
        if source.get("task_status") == "success":
            session["state"] = "ready"
        session["source"] = {
            **(session.get("source") or {}),
            **describe_study_source(
                url="",
                title=source.get("title") or collection_source_file.name,
                source_file=collection_source_file,
            ),
        }
    if playback.get("source_available"):
        media_token = get_study_media_access().issue_collection(
            user_id=user_info.get("user_id") or "",
            collection_id=collection_id,
            source_id=source_id,
        )
        source_url = (
            f"/api/study/collections/{quote(collection_id)}/sources/{quote(source_id)}"
            f"/source-file?media_token={media_token}"
        )
        playback["source_url"] = source_url
        session["playback"] = playback
        if session.get("source") is not None:
            session["source"]["original_url"] = source_url
    session["collection"] = _collection_episode_data(detail, source_id)
    return TranscribeResponse(code=200, message="合集学习模式数据", data=session)


@router.get("/collections/{collection_id}/sources/{source_id}/source-file")
async def get_collection_study_source_file(
    collection_id: str,
    source_id: str,
    media_token: str = Query(...),
):
    try:
        get_study_media_access().verify_collection(
            media_token,
            collection_id=collection_id,
            source_id=source_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="媒体地址无效或已过期")
    service = get_collection_service()
    try:
        source_path = service.get_source_file_path(collection_id, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    source_file = Path(source_path) if source_path else None
    if not source_file or not source_file.is_file():
        raise HTTPException(status_code=404, detail="源视频未保存或已清理")
    return FileResponse(
        path=str(source_file),
        filename=source_file.name,
        media_type=media_type_for_filename(source_file.name),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/collections/{collection_id}/sources/{source_id}/notes",
    response_model=TranscribeResponse,
)
async def create_collection_study_note(
    collection_id: str,
    source_id: str,
    request: StudyNoteRequest,
    user_info: dict = Depends(verify_token),
):
    _, _, source = _get_owned_collection_context(collection_id, source_id, user_info)
    note = get_study_service().create_collection_note(
        source.get("view_token") or "",
        request.time_seconds,
        request.body,
        owner_user_id=user_info.get("user_id") or "",
        collection_id=collection_id,
        source_id=source_id,
    )
    return TranscribeResponse(code=200, message="笔记已保存", data=note)


@router.put(
    "/collections/{collection_id}/sources/{source_id}/notes/{note_id}",
    response_model=TranscribeResponse,
)
async def update_collection_study_note(
    collection_id: str,
    source_id: str,
    note_id: str,
    request: StudyNoteRequest,
    user_info: dict = Depends(verify_token),
):
    _, _, source = _get_owned_collection_context(collection_id, source_id, user_info)
    note = get_study_service().update_collection_note(
        source.get("view_token") or "",
        note_id,
        request.time_seconds,
        request.body,
        owner_user_id=user_info.get("user_id") or "",
        collection_id=collection_id,
        source_id=source_id,
    )
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return TranscribeResponse(code=200, message="笔记已更新", data=note)


@router.delete(
    "/collections/{collection_id}/sources/{source_id}/notes/{note_id}",
    response_model=TranscribeResponse,
)
async def delete_collection_study_note(
    collection_id: str,
    source_id: str,
    note_id: str,
    user_info: dict = Depends(verify_token),
):
    _, _, source = _get_owned_collection_context(collection_id, source_id, user_info)
    deleted = get_study_service().delete_collection_note(
        source.get("view_token") or "",
        note_id,
        owner_user_id=user_info.get("user_id") or "",
        collection_id=collection_id,
        source_id=source_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return TranscribeResponse(code=200, message="笔记已删除", data={"id": note_id})


@router.post(
    "/collections/{collection_id}/sources/{source_id}/ai-chat",
    response_model=TranscribeResponse,
)
async def ask_collection_study_ai(
    collection_id: str,
    source_id: str,
    request: StudyChatRequest,
    user_info: dict = Depends(verify_token),
):
    _, _, source = _get_owned_collection_context(collection_id, source_id, user_info)
    try:
        answer = await run_in_threadpool(
            get_study_service().ask_ai,
            source.get("view_token") or "",
            request.question,
            request.time_seconds,
            [item.model_dump() for item in request.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("collection study ai chat failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI 回答生成失败，请稍后重试")
    if not answer:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    return TranscribeResponse(code=200, message="AI 回答已生成", data=answer)


@router.get("/collections/{collection_id}/sources/{source_id}/export/markdown")
async def export_collection_study_markdown(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    _, _, source = _get_owned_collection_context(collection_id, source_id, user_info)
    markdown = get_study_service().export_collection_markdown(
        source.get("view_token") or "",
        owner_user_id=user_info.get("user_id") or "",
        collection_id=collection_id,
        source_id=source_id,
    )
    if markdown is None:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={
            "Cache-Control": "no-cache",
            "Content-Disposition": f'attachment; filename="{source_id}.md"',
        },
    )


@router.get("/collections/{collection_id}/sources/{source_id}/note-document")
async def get_collection_note_document(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    return _note_document_response(
        _collection_obsidian_context(collection_id, source_id, user_info)
    )


@router.put("/collections/{collection_id}/sources/{source_id}/note-document")
async def update_collection_note_document(
    collection_id: str,
    source_id: str,
    request: StudyNoteDocumentRequest,
    user_info: dict = Depends(verify_token),
):
    return _save_note_document_response(
        _collection_obsidian_context(collection_id, source_id, user_info), request
    )


@router.get("/collections/{collection_id}/obsidian-binding")
async def get_collection_obsidian_binding(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    context = _collection_binding_context(collection_id, user_info)
    try:
        binding = get_obsidian_sync_service().get_binding(context)
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    return TranscribeResponse(
        code=200,
        message="Obsidian collection binding",
        data={"binding": binding, "required": binding is None},
    )


@router.put("/collections/{collection_id}/obsidian-binding")
async def update_collection_obsidian_binding(
    collection_id: str,
    request: ObsidianBindingRequest,
    user_info: dict = Depends(verify_token),
):
    context = _collection_binding_context(collection_id, user_info)
    try:
        binding = get_obsidian_sync_service().save_binding(
            context,
            transcript_directory=request.transcript_directory,
            note_directory=request.note_directory,
            expected_revision=request.expected_revision,
        )
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    return TranscribeResponse(code=200, message="Obsidian binding saved", data=binding)


@router.post("/collections/{collection_id}/sources/{source_id}/obsidian-sync")
async def sync_collection_source_to_obsidian(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    return _sync_response(
        _collection_obsidian_context(collection_id, source_id, user_info)
    )


@router.post(
    "/collections/{collection_id}/sources/{source_id}/obsidian-conflict/resolve"
)
async def resolve_collection_obsidian_conflict(
    collection_id: str,
    source_id: str,
    request: ObsidianConflictResolutionRequest,
    user_info: dict = Depends(verify_token),
):
    return _resolve_conflict_response(
        _collection_obsidian_context(collection_id, source_id, user_info), request
    )


@router.get("/{view_token}/note-document")
async def get_single_note_document(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    return _note_document_response(_single_obsidian_context(view_token, user_info))


@router.put("/{view_token}/note-document")
async def update_single_note_document(
    view_token: str,
    request: StudyNoteDocumentRequest,
    user_info: dict = Depends(verify_token),
):
    return _save_note_document_response(
        _single_obsidian_context(view_token, user_info), request
    )


@router.get("/{view_token}/obsidian-binding")
async def get_single_obsidian_binding(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    context = _single_obsidian_context(view_token, user_info)
    try:
        binding = get_obsidian_sync_service().get_binding(context)
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    return TranscribeResponse(
        code=200,
        message="Obsidian single binding",
        data={"binding": binding, "required": binding is None},
    )


@router.put("/{view_token}/obsidian-binding")
async def update_single_obsidian_binding(
    view_token: str,
    request: ObsidianBindingRequest,
    user_info: dict = Depends(verify_token),
):
    context = _single_obsidian_context(view_token, user_info)
    try:
        binding = get_obsidian_sync_service().save_binding(
            context,
            transcript_directory=request.transcript_directory,
            note_directory=request.note_directory,
            expected_revision=request.expected_revision,
        )
    except Exception as exc:
        _raise_obsidian_http_error(exc)
    return TranscribeResponse(code=200, message="Obsidian binding saved", data=binding)


@router.post("/{view_token}/obsidian-sync")
async def sync_single_to_obsidian(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    return _sync_response(_single_obsidian_context(view_token, user_info))


@router.post("/{view_token}/obsidian-conflict/resolve")
async def resolve_single_obsidian_conflict(
    view_token: str,
    request: ObsidianConflictResolutionRequest,
    user_info: dict = Depends(verify_token),
):
    return _resolve_conflict_response(
        _single_obsidian_context(view_token, user_info), request
    )


@router.get("/{view_token}", response_model=TranscribeResponse)
async def get_study_session(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    _require_owned_single(view_token, user_info)
    session = get_study_service().get_session(view_token)
    if not session:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    playback = session.get("playback") or {}
    if playback.get("source_available"):
        token = get_study_media_access().issue_single(
            user_id=user_info.get("user_id") or "",
            view_token=view_token,
        )
        source_url = f"/api/study/{view_token}/source-file?media_token={token}"
        playback["source_url"] = source_url
        session["playback"] = playback
        if session.get("source") is not None:
            session["source"]["original_url"] = source_url
    return TranscribeResponse(code=200, message="学习模式数据", data=session)


@router.post("/upload", response_model=TranscribeResponse, status_code=202)
async def upload_study_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_speaker_recognition: bool = Form(False),
    visual_fast_path: bool = Form(False),
    user_info: dict = Depends(verify_token),
):
    filename = (file.filename or "upload").strip() or "upload"
    temp_path, size, file_hash = await _save_temp_upload(file, filename)
    media_id = f"local_{file_hash[:32]}"
    stable_path = build_study_source_path(get_source_root(), media_id, filename)
    stable_path.parent.mkdir(parents=True, exist_ok=True)
    if stable_path.exists():
        stable_path.unlink()
    os.replace(temp_path, stable_path)

    display_url = f"local://study-source/{quote(media_id)}/{quote(filename)}"
    task_info = cache_manager.create_task(
        url=display_url,
        use_speaker_recognition=use_speaker_recognition,
        platform="generic",
        media_id=media_id,
        force_new_view_token=True,
    )
    audit_logger.log_api_call(
        api_key=user_info.get("api_key") or "",
        user_id=user_info.get("user_id"),
        endpoint="/api/study/upload",
        video_url=display_url,
        status_code=202,
        task_id=task_info["task_id"],
    )
    background_tasks.add_task(
        process_local_upload,
        task_info["task_id"],
        str(stable_path),
        filename,
        display_url,
        media_id,
        use_speaker_recognition,
        True,
        True,
        visual_fast_path,
    )
    logger.info("study upload accepted: task=%s, file=%s, size=%s", task_info["task_id"], filename, size)
    return TranscribeResponse(
        code=202,
        message="本地学习视频已上传，正在解析",
        data={"task_id": task_info["task_id"], "view_token": task_info["view_token"]},
    )


@router.post("/{view_token}/retry", response_model=TranscribeResponse, status_code=202)
async def retry_single_study(
    view_token: str,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    old_task = cache_manager.get_task_by_view_token(view_token) or {}
    task_id = old_task.get("task_id") or ""
    if not task_id:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    _require_owned_single(view_token, user_info)
    if old_task.get("status") not in {"failed", "canceled"}:
        raise HTTPException(status_code=400, detail="只有失败或已取消的任务可以重新解析")
    source_file = get_study_service().get_source_file(view_token)
    if not source_file:
        raise HTTPException(status_code=400, detail="源文件未保存或已被清理，请重新选择文件")

    display_url = old_task.get("url") or ""
    media_id = old_task.get("media_id") or f"retry_{uuid.uuid4().hex}"
    use_speaker_recognition = bool(old_task.get("use_speaker_recognition"))
    task_info = cache_manager.create_task(
        url=display_url,
        use_speaker_recognition=use_speaker_recognition,
        platform=old_task.get("platform") or "generic",
        media_id=media_id,
        force_new_view_token=True,
    )
    audit_logger.log_api_call(
        api_key=user_info.get("api_key") or "",
        user_id=user_info.get("user_id"),
        endpoint=f"/api/study/{view_token}/retry",
        video_url=display_url,
        status_code=202,
        task_id=task_info["task_id"],
    )
    background_tasks.add_task(
        process_local_upload,
        task_info["task_id"],
        str(source_file),
        old_task.get("title") or source_file.name,
        display_url,
        media_id,
        use_speaker_recognition,
        True,
        True,
        False,
    )
    return TranscribeResponse(
        code=202,
        message="已重新提交解析",
        data={"task_id": task_info["task_id"], "view_token": task_info["view_token"]},
    )


@router.post("/text", response_model=TranscribeResponse, status_code=202)
async def create_study_text(
    request: StudyTextRequest,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    return _submit_study_text(request, background_tasks)


@router.post("/pdf-bundle", response_model=TranscribeResponse, status_code=202)
async def create_study_pdf_bundle(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    title: str = Form("", max_length=160),
    user_info: dict = Depends(verify_token),
):
    filenames = _pdf_upload_filenames(files, minimum=2)
    content = await run_in_threadpool(_combine_pdf_text, files, filenames)
    default_title = f"{Path(filenames[0]).stem[:100]} 等 {len(files)} 份 PDF"
    request = StudyTextRequest(title=title.strip() or default_title, content=content)
    return _submit_study_text(request, background_tasks, pdf_user=user_info)


@router.post("/pdf-batch", response_model=TranscribeResponse, status_code=202)
async def create_study_pdf_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    keys: list[str] = Form(...),
    user_info: dict = Depends(verify_token),
):
    filenames = _pdf_upload_filenames(files)
    if len(keys) != len(files) or len(set(keys)) != len(keys) or any(
        not re.fullmatch(r"[a-f0-9]{32}", key) for key in keys
    ):
        raise HTTPException(status_code=422, detail="文件清单已失效，请重新选择")

    items = []
    for key, file, filename in zip(keys, files, filenames):
        try:
            content = await run_in_threadpool(
                _read_study_pdf, file, filename, _STUDY_TEXT_MAX_CHARS
            )
            request = StudyTextRequest(title=Path(filename).stem[:160], content=content)
            result = _submit_study_text(
                request, background_tasks, pdf_user=user_info, pdf_item_key=key
            )
        except HTTPException as exc:
            items.append({"key": key, "error": exc.detail})
        except PDFTextLimitExceeded:
            items.append({"key": key, "error": f"正文超过 {_STUDY_TEXT_MAX_CHARS:,} 字"})
        except Exception:
            logger.exception("Individual PDF submission failed")
            items.append({"key": key, "error": "提交失败，请重试此文件"})
        else:
            items.append({"key": key, **result.data})
    return TranscribeResponse(code=202, message="逐篇提交完成", data={"items": items})


def _pdf_upload_filenames(files: list[UploadFile], minimum: int = 1) -> list[str]:
    if not minimum <= len(files) <= _PDF_UPLOAD_MAX_FILES:
        raise HTTPException(
            status_code=422, detail=f"请选择 {minimum} 至 {_PDF_UPLOAD_MAX_FILES} 份 PDF"
        )
    if sum(file.size or 0 for file in files) > _PDF_UPLOAD_MAX_BYTES:
        limit_mb = _PDF_UPLOAD_MAX_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"PDF 总大小不能超过 {limit_mb} MB")
    return [
        re.sub(r"[\x00-\x1f\x7f]+", " ", source_basename(file.filename or ""))
        for file in files
    ]


def _read_study_pdf(file: UploadFile, filename: str, max_chars: int) -> str:
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="此入口仅支持 PDF 文件")
    if not file.size:
        raise HTTPException(status_code=422, detail=f"「{filename}」是空文件")
    try:
        text = extract_pdf_text(file.file, max_chars=max_chars)
    except PDFTextLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("Study PDF extraction failed: {}", type(exc).__name__)
        raise HTTPException(
            status_code=422, detail=f"无法读取「{filename}」，请检查文件是否损坏或加密"
        ) from exc
    if not text:
        raise HTTPException(
            status_code=422,
            detail=f"「{filename}」没有可提取的文字，请先完成 OCR 或移除此文件",
        )
    return text


def _combine_pdf_text(files: list[UploadFile], filenames: list[str]) -> str:
    sections = []
    remaining = _STUDY_TEXT_MAX_CHARS
    for number, (file, filename) in enumerate(zip(files, filenames), start=1):
        heading = f"## 资料 {number} · {filename}\n\n"
        remaining -= len(heading) + (2 if sections else 0)
        try:
            text = _read_study_pdf(file, filename, remaining)
        except PDFTextLimitExceeded as exc:
            raise HTTPException(
                status_code=413,
                detail=f"合并后的正文超过 {_STUDY_TEXT_MAX_CHARS:,} 字，请减少文件后再试",
            ) from exc
        sections.append(heading + text)
        remaining -= len(text)
    return "\n\n".join(sections)


def _submit_study_text(
    request: StudyTextRequest,
    background_tasks: BackgroundTasks,
    *,
    pdf_user: dict | None = None,
    pdf_item_key: str | None = None,
) -> TranscribeResponse:
    title = request.title or _title_from_content(request.content)
    identity = request.content
    if pdf_user is not None:
        identity_parts = [pdf_user.get("user_id"), title, request.content]
        if pdf_item_key:
            identity_parts.append(pdf_item_key)
        identity = json.dumps(identity_parts, ensure_ascii=False)
    content_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    media_id = f"text_{content_hash[:32]}"
    display_filename = _display_markdown_filename(title)
    display_url = f"local://study-text/{quote(media_id)}/content.md"
    if pdf_item_key:
        # The same browser item can be resent after a lost response.
        # This synchronous lookup and submit run without yielding on the API loop.
        existing = cache_manager.get_existing_task_by_url(display_url)
        if existing:
            return TranscribeResponse(
                code=202, message="文件已提交",
                data={"task_id": existing["task_id"], "view_token": existing["view_token"], "title": title},
            )
    source_dir = get_source_root() / "study_texts"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"{media_id}.md"
    if pdf_user is None:
        source_path.write_text(request.content, encoding="utf-8")
    else:
        staged_path = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=source_dir, delete=False) as staged:
                staged_path = Path(staged.name)
                staged.write(request.content)
            os.replace(staged_path, source_path)
        finally:
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)

    task_source = {}
    if pdf_user is not None:
        task_source = {
            "owner_user_id": pdf_user.get("user_id"),
            "source_file_path": str(source_path),
        }
    task_info = cache_manager.create_task(
        url=display_url,
        use_speaker_recognition=False,
        platform="generic",
        media_id=media_id,
        **task_source,
    )
    if pdf_user is not None:
        cache_manager.update_task_status(
            task_info["task_id"], "queued", title=display_filename
        )
        audit_logger.log_api_call(
            api_key=pdf_user.get("api_key") or "",
            user_id=pdf_user.get("user_id"),
            endpoint="/api/study/pdf-batch" if pdf_item_key else "/api/study/pdf-bundle",
            video_url=display_url,
            status_code=202,
            task_id=task_info["task_id"],
        )
    background_tasks.add_task(
        process_local_upload,
        task_info["task_id"],
        str(source_path),
        display_filename,
        display_url,
        media_id,
        False,
        True,
        True,
        False,
    )
    logger.info("study text accepted: task=%s", task_info["task_id"])
    response_data = {"task_id": task_info["task_id"], "view_token": task_info["view_token"]}
    if pdf_user is not None:
        response_data["title"] = title
    return TranscribeResponse(
        code=202,
        message="文字内容已提交，正在解析",
        data=response_data,
    )


@router.get("/{view_token}/source-file")
async def get_study_source_file(view_token: str, media_token: str = Query(...)):
    try:
        get_study_media_access().verify_single(media_token, view_token=view_token)
    except ValueError:
        raise HTTPException(status_code=404, detail="媒体地址无效或已过期")
    source_file = get_study_service().get_source_file(view_token)
    if not source_file:
        raise HTTPException(status_code=404, detail="源视频未保存或已清理")
    return FileResponse(
        path=str(source_file),
        filename=source_file.name,
        media_type=media_type_for_filename(source_file.name),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{view_token}/export/markdown")
async def export_study_markdown(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    _require_owned_single(view_token, user_info)
    markdown = get_study_service().export_markdown(view_token)
    if markdown is None:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    filename = view_token.replace('"', "").replace("\\", "") + ".md"
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={
            "Cache-Control": "no-cache",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{view_token}/notes", response_model=TranscribeResponse)
async def create_study_note(
    view_token: str,
    request: StudyNoteRequest,
    user_info: dict = Depends(verify_token),
):
    _require_owned_single(view_token, user_info)
    note = get_study_service().create_note(
        view_token,
        request.time_seconds,
        request.body,
    )
    return TranscribeResponse(code=200, message="笔记已保存", data=note)


@router.post("/{view_token}/ai-chat", response_model=TranscribeResponse)
async def ask_study_ai(
    view_token: str,
    request: StudyChatRequest,
    user_info: dict = Depends(verify_token),
):
    _require_owned_single(view_token, user_info)
    service = get_study_service()
    try:
        answer = await run_in_threadpool(
            service.ask_ai,
            view_token,
            request.question,
            request.time_seconds,
            [item.model_dump() for item in request.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("study ai chat failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI 回答生成失败，请稍后重试")

    if not answer:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    return TranscribeResponse(code=200, message="AI 回答已生成", data=answer)


async def _save_temp_upload(file: UploadFile, filename: str) -> tuple[str, int, str]:
    upload_dir = get_source_root() / "study_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"upload-{uuid.uuid4().hex}{safe_extension(filename)}"
    size = 0
    digest = hashlib.sha256()

    try:
        with open(temp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _UPLOAD_MAX_BYTES:
                    out.close()
                    temp_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大（上限 {_UPLOAD_MAX_MB // 1024}GB）",
                    )
                digest.update(chunk)
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("save study upload failed: %s", exc)
        raise HTTPException(status_code=500, detail="保存上传文件失败")

    if size == 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件为空")

    return str(temp_path), size, digest.hexdigest()


def _title_from_content(content: str) -> str:
    for line in content.splitlines():
        clean_line = line.strip()
        if not clean_line:
            continue
        clean_line = re.sub(r"^#{1,6}\s*", "", clean_line).strip()
        if clean_line:
            return clean_line[:80]
    return "粘贴文字"


def _display_markdown_filename(title: str) -> str:
    safe_title = re.sub(r"[\\/\x00-\x1f]+", " ", title)
    safe_title = re.sub(r"\s+", " ", safe_title).strip(" .")
    return f"{(safe_title or '粘贴文字')[:120]}.md"
