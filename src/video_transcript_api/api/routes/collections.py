import hashlib
import os
import re
import subprocess
import sys
import uuid
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from ..context import get_cache_manager, get_config, get_logger, get_static_dir
from ..services.transcription import TranscribeResponse, process_local_upload, verify_token
from ...collections.repository import LearningCollectionRepository
from ...collections.service import LearningCollectionService
from ...collections.titles import source_basename

logger = get_logger()
config = get_config()
cache_manager = get_cache_manager()
static_dir = get_static_dir()

router = APIRouter(tags=["collections"])

_UPLOAD_MAX_MB = int((config.get("upload") or {}).get("max_mb", 20480))
_UPLOAD_MAX_BYTES = _UPLOAD_MAX_MB * 1024 * 1024


class CreateCollectionRequest(BaseModel):
    title: str
    creator_name: str
    collection_type: str
    goal: str = ""
    description: str = ""
    import_method: str = ""
    tags: str = ""


class GenerateKnowledgeMapRequest(BaseModel):
    scope: str = "collection"
    source_id: Optional[str] = None
    force: bool = False


@lru_cache
def get_collection_service() -> LearningCollectionService:
    cache_db_path = str(cache_manager.db_path)
    repository = LearningCollectionRepository(db_path=cache_db_path)
    llm_cfg = (config.get("llm") or {}).copy()
    return LearningCollectionService(
        repository=repository,
        cache_manager=cache_manager,
        llm_config=llm_cfg,
        source_file_dir=str(_source_files_dir()),
    )


@router.get("/collections", response_class=HTMLResponse, include_in_schema=False)
async def collections_page():
    page = static_dir / "collections.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="collections page not found")
    version_files = [
        page,
        static_dir / "css" / "collections.css",
        static_dir / "js" / "collections.js",
        static_dir / "css" / "app-shell.css",
        static_dir / "js" / "app-shell.js",
        static_dir / "js" / "pwa-register.js",
        static_dir / "css" / "editorial.css",
    ]
    version = str(int(max((f.stat().st_mtime for f in version_files if f.exists()), default=0)))
    content = page.read_text(encoding="utf-8").replace("__ASSET_VERSION__", version)
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache"})


@router.get("/api/collections", response_model=TranscribeResponse)
async def list_collections(
    creator_name: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    collection_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user_info: dict = Depends(verify_token),
):
    service = get_collection_service()
    return TranscribeResponse(
        code=200,
        message="学习集合列表",
        data={
            "collections": service.list_collections(
                creator_name=creator_name,
                title=title,
                date_from=date_from,
                date_to=date_to,
                collection_type=collection_type,
                status=status,
            )
        },
    )


@router.get("/api/collections/filter-options", response_model=TranscribeResponse)
async def get_collection_filter_options(user_info: dict = Depends(verify_token)):
    service = get_collection_service()
    return TranscribeResponse(
        code=200,
        message="学习集合筛选选项",
        data=service.get_filter_options(),
    )


@router.post("/api/collections", response_model=TranscribeResponse)
async def create_collection(
    body: CreateCollectionRequest,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        collection = service.create_collection(
            title=body.title,
            creator_name=body.creator_name,
            collection_type=body.collection_type,
            goal=body.goal,
            description=body.description,
            import_method=body.import_method,
            tags=body.tags,
        )
        return TranscribeResponse(code=200, message="学习集合已创建", data=collection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/collections/{collection_id}", response_model=TranscribeResponse)
async def get_collection(collection_id: str, user_info: dict = Depends(verify_token)):
    try:
        service = get_collection_service()
        return TranscribeResponse(
            code=200,
            message="学习集合详情",
            data=service.get_collection_detail(collection_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/collections/{collection_id}/sources/{source_id}", response_model=TranscribeResponse)
async def get_collection_source(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        return TranscribeResponse(
            code=200,
            message="学习集合 source 详情",
            data=service.get_source_detail(collection_id, source_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/api/collections/{collection_id}/sources/{source_id}/retry",
    response_model=TranscribeResponse,
    status_code=202,
)
async def retry_collection_source(
    collection_id: str,
    source_id: str,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        result = service.retry_source(collection_id, source_id)
        background_tasks.add_task(
            process_local_upload,
            result["task_id"],
            result["file_path"],
            result["original_name"],
            result["display_url"],
            result["media_id"],
            result["use_speaker_recognition"],
            True,
        )
        return TranscribeResponse(
            code=202,
            message="已重新提交 source 解析",
            data={
                "collection": result["collection"],
                "source": result["source"],
            },
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.post(
    "/api/collections/{collection_id}/sources/upload",
    response_model=TranscribeResponse,
    status_code=202,
)
async def upload_collection_sources(
    collection_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    files: List[UploadFile] = File(...),
    use_speaker_recognition: bool = Form(False),
    user_info: dict = Depends(verify_token),
):
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一个文件")

    service = get_collection_service()
    uploaded = []
    try:
        detail = service.get_collection_detail(collection_id)
        existing_positions = [
            int(source.get("position") or 0) for source in detail.get("sources", [])
        ]
        next_position = (max(existing_positions) if existing_positions else 0) + 1
        append_position = next_position
        for file in files:
            filename = source_basename(file.filename or "upload") or "upload"
            position = _source_position_from_filename(filename) or append_position
            append_position = max(append_position, position + 1)
            source_type = service.validate_source_type_for_collection(collection_id, filename)
            temp_path, size, file_hash = await _save_upload_file(file, filename)
            media_id = _media_id_for_upload_hash(file_hash)
            display_url = f"local://collection-source/{media_id}/{filename}"
            reusable_task = cache_manager.get_existing_task_by_media(
                "generic", media_id, use_speaker_recognition
            )
            if reusable_task and reusable_task.get("status") != "failed":
                _stable_upload_path(temp_path, media_id, filename)
                source = service.add_existing_source(
                    collection_id=collection_id,
                    task_id=reusable_task["task_id"],
                    view_token=reusable_task["view_token"],
                    title=filename,
                    source_type=source_type,
                    position=position,
                )
                uploaded.append({**source, "size": size, "reused": True})
                continue

            stable_path = _stable_upload_path(temp_path, media_id, filename)
            task_info = cache_manager.create_task(
                url=display_url,
                use_speaker_recognition=use_speaker_recognition,
                platform="generic",
                media_id=media_id,
            )
            source = service.add_existing_source(
                collection_id=collection_id,
                task_id=task_info["task_id"],
                view_token=task_info["view_token"],
                title=filename,
                source_type=source_type,
                position=position,
            )
            background_tasks.add_task(
                process_local_upload,
                task_info["task_id"],
                stable_path,
                filename,
                display_url,
                media_id,
                use_speaker_recognition,
                True,
            )
            uploaded.append({**source, "size": size, "reused": False})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(f"collection upload accepted: collection={collection_id}, count={len(uploaded)}")
    return TranscribeResponse(
        code=202,
        message="专题文件已上传，正在逐个解析",
        data={"sources": uploaded},
    )


@router.post("/api/collections/{collection_id}/cancel", response_model=TranscribeResponse)
async def cancel_collection_processing(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        result = service.cancel_collection_processing(collection_id)
        return TranscribeResponse(
            code=200,
            message="已停止未完成的专题解析任务",
            data=result,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.post("/api/collections/{collection_id}/summary", response_model=TranscribeResponse)
async def generate_collection_summary(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        detail = await run_in_threadpool(service.generate_summary, collection_id)
        return TranscribeResponse(code=200, message="全系列解读已生成", data=detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/collections/{collection_id}/knowledge-map", response_model=TranscribeResponse)
async def get_collection_knowledge_map(
    collection_id: str,
    scope: str = Query("collection"),
    source_id: Optional[str] = Query(None),
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        knowledge_map = service.get_knowledge_map(
            collection_id=collection_id,
            scope=scope,
            source_id=source_id,
        )
        if not knowledge_map:
            return TranscribeResponse(
                code=200,
                message="知识地图尚未生成",
                data={"status": "not_started", "map_json": None},
            )
        return TranscribeResponse(code=200, message="知识地图", data=knowledge_map)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.post("/api/collections/{collection_id}/knowledge-map", response_model=TranscribeResponse)
async def generate_collection_knowledge_map(
    collection_id: str,
    body: GenerateKnowledgeMapRequest,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        knowledge_map = await run_in_threadpool(
            service.generate_knowledge_map,
            collection_id=collection_id,
            scope=body.scope,
            source_id=body.source_id,
            force=body.force,
        )
        return TranscribeResponse(code=200, message="知识地图已生成", data=knowledge_map)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.get("/api/collections/{collection_id}/export/markdown")
async def export_collection_markdown(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        markdown = service.get_export_markdown(collection_id)
        service.mark_exported(collection_id)
        return Response(
            content=markdown.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{collection_id}.md"',
                "Cache-Control": "no-cache",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/collections/{collection_id}/sources/{source_id}/file")
async def open_collection_source_file(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        file_path = service.get_source_file_path(collection_id, source_id)
        if not file_path:
            raise HTTPException(status_code=404, detail="源文件未保存或已被清理")
        return FileResponse(path=file_path, filename=os.path.basename(file_path))
    except HTTPException:
        raise
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.post("/api/collections/{collection_id}/sources/{source_id}/reveal", response_model=TranscribeResponse)
async def reveal_collection_source_file(
    collection_id: str,
    source_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        service = get_collection_service()
        file_path = service.get_source_file_path(collection_id, source_id)
        if not file_path:
            raise HTTPException(status_code=404, detail="源文件未保存或已被清理")
        await run_in_threadpool(_reveal_path_in_file_manager, file_path)
        return TranscribeResponse(
            code=200,
            message="已打开源文件所在目录",
            data={"filename": os.path.basename(file_path)},
        )
    except HTTPException:
        raise
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))
    except OSError as exc:
        logger.warning(f"reveal collection source failed: {exc}")
        raise HTTPException(status_code=500, detail="打开本地目录失败")


def _reveal_path_in_file_manager(file_path: str) -> None:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
        return
    if os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{path}"])
        return
    target = path.parent if path.is_file() else path
    subprocess.Popen(["xdg-open", str(target)])


async def _save_upload_file(file: UploadFile, filename: str) -> tuple[str, int, str]:
    upload_dir = os.path.join(
        config.get("storage", {}).get("temp_dir", "./data/temp"), "collection_uploads"
    )
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(filename)[1][:10] or ".bin"
    temp_path = os.path.join(upload_dir, f"upload-{uuid.uuid4().hex}{ext}")

    size = 0
    digest = hashlib.sha256()
    try:
        with open(temp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
                if size > _UPLOAD_MAX_BYTES:
                    out.close()
                    os.remove(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大（上限 {_UPLOAD_MAX_MB // 1024}GB）",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"save collection upload failed: {exc}")
        raise HTTPException(status_code=500, detail="保存上传文件失败")

    if size == 0:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=400, detail="上传文件为空")
    return temp_path, size, digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _media_id_for_upload_hash(file_hash: str) -> str:
    return f"local_{file_hash[:32]}"


def _source_position_from_filename(filename: str) -> Optional[int]:
    basename = os.path.basename(filename or "")
    match = re.match(r"^\s*(\d{1,4})(?=[\s._\-－—、])", basename)
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _stable_upload_path(temp_path: str, media_id: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1][:10] or ".bin"
    upload_dir = _source_files_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    stable_path = str(upload_dir / f"{media_id}{ext}")
    if os.path.abspath(temp_path) == os.path.abspath(stable_path):
        return stable_path
    if os.path.exists(stable_path):
        os.remove(stable_path)
    os.replace(temp_path, stable_path)
    return stable_path


def _source_files_dir() -> Path:
    storage_cfg = config.get("storage", {}) or {}
    source_dir = storage_cfg.get("source_files_dir") or "./data/source_files/collection_uploads"
    return Path(source_dir)
