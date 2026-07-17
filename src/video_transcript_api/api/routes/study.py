import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

from ..context import get_audit_logger, get_cache_manager, get_config, get_logger, get_user_manager
from ..services.transcription import TranscribeResponse, process_local_upload, verify_token
from ...study.repository import StudyRepository
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

router = APIRouter(prefix="/api/study", tags=["study"])

config = get_config()
logger = get_logger()
cache_manager = get_cache_manager()
audit_logger = get_audit_logger()
user_manager = get_user_manager()

_UPLOAD_MAX_MB = int((config.get("upload") or {}).get("max_mb", 20480))
_UPLOAD_MAX_BYTES = _UPLOAD_MAX_MB * 1024 * 1024


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


class StudyTextRequest(BaseModel):
    title: str = Field(default="", max_length=160)
    content: str = Field(..., min_length=1, max_length=200000)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_text_fields(cls, value):
        return str(value or "").strip()


def get_source_root() -> Path:
    storage_cfg = config.get("storage", {}) or {}
    return Path(storage_cfg.get("source_files_dir") or "./data/source_files")


def get_study_service() -> StudyService:
    return StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(db_path=str(cache_manager.db_path)),
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
    title = request.title or _title_from_content(request.content)
    content_hash = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
    media_id = f"text_{content_hash[:32]}"
    source_dir = get_source_root() / "study_texts"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"{media_id}.md"
    source_path.write_text(request.content, encoding="utf-8")

    display_filename = _display_markdown_filename(title)
    display_url = f"local://study-text/{quote(media_id)}/content.md"
    task_info = cache_manager.create_task(
        url=display_url,
        use_speaker_recognition=False,
        platform="generic",
        media_id=media_id,
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
    return TranscribeResponse(
        code=202,
        message="文字内容已提交，正在解析",
        data={"task_id": task_info["task_id"], "view_token": task_info["view_token"]},
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
