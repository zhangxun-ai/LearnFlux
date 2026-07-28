from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ...reading.repository import ReadingDataError
from ...reading.assets import ReadingAssetError
from ...reading.service import ReadingService
from ...reading.source_files import ReadingSourceError
from ..context import get_cache_manager, get_config, get_static_dir
from ..services.transcription import verify_token


router = APIRouter(tags=["reading"])


class ReadingProgressRequest(BaseModel):
    chapter_id: str = Field(min_length=1, max_length=128)
    percent: float = Field(ge=0, le=100)


class ReadingPreferencesRequest(BaseModel):
    theme: str = Field(default="paper", max_length=32)
    font_family: str = Field(default="serif", max_length=64)
    font_size: int = Field(default=20, ge=14, le=36)
    layout: str = Field(default="double", pattern="^(single|double)$")
    sound_track: str = Field(default="rain", pattern="^(rain|stream|snow)$")
    sound_volume: float = Field(default=0.28, ge=0, le=1)


def _owner_id(user_info: dict) -> str:
    owner = str(user_info.get("user_id") or "").strip()
    if not owner:
        raise HTTPException(status_code=401, detail="用户身份无效")
    return owner


def get_reading_service() -> ReadingService:
    config = get_config()
    storage = config.get("storage", {}) or {}
    source_root = Path(storage.get("source_files_dir") or "./data/source_files")
    return ReadingService(
        db_path=str(get_cache_manager().db_path),
        source_root=source_root,
    )


def _serialize(value):
    return value.model_dump(mode="json") if value is not None else None


def _run_local_ocr(owner_user_id: str, document_id: str) -> None:
    service = get_reading_service()
    try:
        service.ocr_document(owner_user_id, document_id)
    finally:
        service.close()


def _run_structured_reprocess(
    owner_user_id: str, document_id: str, run_id: str
) -> None:
    service = get_reading_service()
    try:
        service.complete_reprocess_document(owner_user_id, document_id, run_id)
    finally:
        service.close()


def _start_local_ocr(
    background_tasks: BackgroundTasks, owner_user_id: str, document_id: str
):
    service = get_reading_service()
    try:
        document = service.start_local_ocr(owner_user_id, document_id)
    finally:
        service.close()
    if document is not None and document.status == "processing":
        background_tasks.add_task(_run_local_ocr, owner_user_id, document_id)
    return document


@router.get("/reading", response_class=HTMLResponse, include_in_schema=False)
async def reading_page():
    static_dir = get_static_dir()
    page = static_dir / "reading.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="心流阅读页面不存在")
    version_files = [
        page,
        static_dir / "css" / "reading.css",
        static_dir / "css" / "editorial.css",
        static_dir / "css" / "app-shell.css",
        static_dir / "css" / "product-linear.css",
        static_dir / "css" / "product-linear-core.css",
        static_dir / "js" / "reading.js",
        static_dir / "js" / "reading-flow.js",
        static_dir / "js" / "ui-features.js",
        static_dir / "js" / "app-shell.js",
        static_dir / "js" / "pwa-register.js",
    ]
    version = str(max(
        (path.stat().st_mtime_ns for path in version_files if path.exists()),
        default=0,
    ))
    return HTMLResponse(
        page.read_text(encoding="utf-8").replace("__ASSET_VERSION__", version),
        headers={"Cache-Control": "no-cache"},
    )


@router.get(
    "/reading/{document_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def reading_document_page(document_id: str):
    return await reading_page()


@router.get("/api/reading/documents")
async def list_reading_documents(user_info: dict = Depends(verify_token)):
    service = get_reading_service()
    try:
        items = service.list_documents(_owner_id(user_info))
        return {"code": 200, "message": "success", "data": {
            "items": [_serialize(item) for item in items], "total": len(items)}}
    finally:
        service.close()


@router.post("/api/reading/documents", status_code=201)
async def import_reading_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_info: dict = Depends(verify_token),
):
    owner = _owner_id(user_info)
    filename = file.filename or "document"

    def import_sync():
        service = get_reading_service()
        try:
            return service.import_document(owner, filename=filename, stream=file.file)
        finally:
            service.close()

    try:
        document = await run_in_threadpool(import_sync)
    except ReadingSourceError as exc:
        raise HTTPException(status_code=400, detail=exc.code) from None
    except (ReadingDataError, ValueError, OSError):
        raise HTTPException(status_code=422, detail="文档解析失败") from None
    if document.status == "needs_ocr":
        document = _start_local_ocr(background_tasks, owner, document.id) or document
    return {"code": 201, "message": "success", "data": _serialize(document)}


@router.get("/api/reading/documents/{document_id}")
async def get_reading_document(
    document_id: str,
    user_info: dict = Depends(verify_token),
):
    service = get_reading_service()
    try:
        detail = service.get_document_detail(_owner_id(user_info), document_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return {"code": 200, "message": "success", "data": {
            "document": _serialize(detail["document"]),
            "chapters": [_serialize(item) for item in detail["chapters"]],
            "progress": _serialize(detail["progress"]),
        }}
    finally:
        service.close()


@router.post("/api/reading/documents/{document_id}/ocr")
async def start_reading_document_ocr(
    document_id: str,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    document = _start_local_ocr(
        background_tasks, _owner_id(user_info), document_id
    )
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 200, "message": "success", "data": _serialize(document)}


@router.post("/api/reading/documents/{document_id}/reprocess", status_code=202)
async def reprocess_reading_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    owner = _owner_id(user_info)
    service = get_reading_service()
    try:
        run = service.start_reprocess_document(owner, document_id)
    except ReadingDataError:
        raise HTTPException(status_code=409, detail="已有解析任务正在运行") from None
    finally:
        service.close()
    if run is None:
        raise HTTPException(status_code=404, detail="文档不可重新解析")
    background_tasks.add_task(_run_structured_reprocess, owner, document_id, run.id)
    return {"code": 202, "message": "accepted", "data": _serialize(run)}


@router.get("/api/reading/documents/{document_id}/assets/{asset_name}")
async def get_reading_asset(
    document_id: str,
    asset_name: str,
    user_info: dict = Depends(verify_token),
):
    service = get_reading_service()
    try:
        try:
            resolved = service.get_document_asset(
                _owner_id(user_info), document_id, asset_name
            )
        except ReadingAssetError:
            raise HTTPException(status_code=404, detail="图片不存在") from None
        if resolved is None:
            raise HTTPException(status_code=404, detail="图片不存在")
        path, mime_type = resolved
        return FileResponse(
            path,
            media_type=mime_type,
            filename=path.name,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        service.close()


@router.get("/api/reading/documents/{document_id}/source")
async def get_reading_source(
    document_id: str,
    user_info: dict = Depends(verify_token),
):
    service = get_reading_service()
    try:
        resolved = service.get_document_source(_owner_id(user_info), document_id)
        if resolved is None:
            raise HTTPException(status_code=404, detail="源文件不存在")
        path, mime_type = resolved
        return FileResponse(
            path,
            media_type=mime_type,
            filename=path.name,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        service.close()


@router.put("/api/reading/documents/{document_id}/progress")
async def save_reading_progress(
    document_id: str,
    payload: ReadingProgressRequest,
    user_info: dict = Depends(verify_token),
):
    service = get_reading_service()
    try:
        progress = service.save_progress(
            _owner_id(user_info), document_id,
            chapter_id=payload.chapter_id, percent=payload.percent,
        )
        return {"code": 200, "message": "success", "data": _serialize(progress)}
    except ReadingDataError:
        raise HTTPException(status_code=404, detail="章节不存在") from None
    finally:
        service.close()


@router.get("/api/reading/preferences")
async def get_reading_preferences(user_info: dict = Depends(verify_token)):
    service = get_reading_service()
    try:
        return {"code": 200, "message": "success", "data": _serialize(
            service.get_preferences(_owner_id(user_info)))}
    finally:
        service.close()


@router.put("/api/reading/preferences")
async def save_reading_preferences(
    payload: ReadingPreferencesRequest,
    user_info: dict = Depends(verify_token),
):
    service = get_reading_service()
    try:
        preferences = service.save_preferences(
            _owner_id(user_info), **payload.model_dump())
        return {"code": 200, "message": "success", "data": _serialize(preferences)}
    finally:
        service.close()


@router.delete("/api/reading/documents/{document_id}")
async def delete_reading_document(
    document_id: str,
    user_info: dict = Depends(verify_token),
):
    service = get_reading_service()
    try:
        if not service.delete_document(_owner_id(user_info), document_id):
            raise HTTPException(status_code=404, detail="文档不存在")
        return {"code": 200, "message": "success"}
    finally:
        service.close()
