import hashlib
import os
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..context import get_cache_manager, get_config, get_logger
from ..services.transcription import TranscribeResponse, process_local_upload, verify_token
from ...study.repository import StudyRepository
from ...study.service import StudyService
from ...study.source_files import (
    build_study_source_path,
    media_type_for_filename,
    safe_extension,
)

router = APIRouter(prefix="/api/study", tags=["study"])

config = get_config()
logger = get_logger()
cache_manager = get_cache_manager()

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


@router.get("/{view_token}", response_model=TranscribeResponse)
async def get_study_session(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    session = get_study_service().get_session(view_token)
    if not session:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    return TranscribeResponse(code=200, message="学习模式数据", data=session)


@router.post("/upload", response_model=TranscribeResponse, status_code=202)
async def upload_study_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_speaker_recognition: bool = Form(False),
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
    )
    logger.info("study upload accepted: task=%s, file=%s, size=%s", task_info["task_id"], filename, size)
    return TranscribeResponse(
        code=202,
        message="本地学习视频已上传，正在解析",
        data={"task_id": task_info["task_id"], "view_token": task_info["view_token"]},
    )


@router.get("/{view_token}/source-file")
async def get_study_source_file(view_token: str):
    source_file = get_study_service().get_source_file(view_token)
    if not source_file:
        raise HTTPException(status_code=404, detail="源视频未保存或已清理")
    return FileResponse(
        path=str(source_file),
        filename=source_file.name,
        media_type=media_type_for_filename(source_file.name),
    )


@router.get("/{view_token}/export/markdown")
async def export_study_markdown(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
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
