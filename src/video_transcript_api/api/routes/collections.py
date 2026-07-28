import hashlib
import os
import re
import subprocess
import sys
import uuid
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, StrictInt

from ..context import (
    get_cache_manager,
    get_cloud_asr_dispatcher,
    get_cloud_quote_repository,
    get_config,
    get_logger,
    get_static_dir,
    get_transcription_concurrency_controller,
    get_transcription_control_database,
    get_user_manager,
)
from ..services.transcription import (
    TranscribeResponse,
    process_local_upload,
    refresh_cloud_quote,
    verify_token,
)
from ...collections.repository import LearningCollectionRepository
from ...collections.service import LearningCollectionService
from ...collections.titles import source_basename
from ...collections.transcription import (
    CollectionTranscriptionService,
    CollectionQuoteSnapshot,
    validate_transcription_selection,
)
from ...transcriber.cloud_quote_repository import (
    CloudQuoteConfirmation,
    CloudQuoteConflict,
)
from ...utils.local_fs_browser import (
    LocalFolderPickCancelled,
    LocalFolderPickUnavailable,
    browse_local_directory,
    pick_local_directory_native,
)

logger = get_logger()
config = get_config()
cache_manager = get_cache_manager()
static_dir = get_static_dir()
user_manager = get_user_manager()

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
    transcription_strategy: str = "local"
    transcription_concurrency: StrictInt = 1


class GenerateKnowledgeMapRequest(BaseModel):
    scope: str = "collection"
    source_id: Optional[str] = None
    force: bool = False


class CollectionCloudQuoteItemConfirmationRequest(BaseModel):
    task_id: str
    quote_token: str
    accepted_max_cost_cny: str


class CollectionCloudQuoteConfirmRequest(BaseModel):
    transcription_revision: StrictInt
    accepted_total_cny: str
    confirmations: list[CollectionCloudQuoteItemConfirmationRequest]


class ContinueCollectionTranscriptionRequest(BaseModel):
    transcription_strategy: str
    transcription_concurrency: StrictInt


class LocalPathImportRequest(BaseModel):
    """Import sources by referencing existing local files (no copy into managed storage)."""

    directory: str = ""
    paths: List[str] = []
    transcription_strategy: Optional[str] = None
    transcription_concurrency: Optional[int] = None


@lru_cache
def get_collection_service() -> LearningCollectionService:
    control_database = get_transcription_control_database(cache_manager)
    repository = LearningCollectionRepository(db_path=control_database)
    if getattr(repository.database, "dialect", "sqlite") == "postgres":
        import_result = repository.import_legacy_sqlite_if_target_empty(
            cache_manager.db_path
        )
        if import_result["status"] == "imported":
            logger.info(
                "Imported legacy learning collections into control database: {}",
                import_result,
            )
        elif import_result["status"] == "refused_target_not_empty":
            logger.warning(
                "Skipped legacy learning collection import because target is not empty"
            )
    llm_cfg = (config.get("llm") or {}).copy()
    service = LearningCollectionService(
        repository=repository,
        cache_manager=cache_manager,
        llm_config=llm_cfg,
        source_file_dir=str(_source_files_dir()),
    )
    if not user_manager.is_multi_user_mode():
        repository.assign_unowned_collections("legacy_user")
    return service


def get_collection_transcription_service() -> CollectionTranscriptionService:
    """Build a coordinator around the current collection service dependencies."""
    collection_service = get_collection_service()
    return CollectionTranscriptionService(
        collection_service.repository,
        collection_service.cache_manager,
        quote_repository=get_cloud_quote_repository(),
        quote_refresher=refresh_cloud_quote,
        concurrency_controller=get_transcription_concurrency_controller(),
    )


def _require_collection_owner(service, collection_id: str, user_info: dict) -> None:
    repository = getattr(service, "repository", None)
    if repository is None:
        return
    collection = repository.get_collection(collection_id)
    if not isinstance(collection, dict):
        return
    owner_user_id = (collection.get("owner_user_id") or "").strip()
    if not owner_user_id and not user_manager.is_multi_user_mode():
        return
    if not owner_user_id or owner_user_id != (user_info.get("user_id") or ""):
        raise HTTPException(status_code=404, detail="collection not found")


def _backfill_testable_single_user_owner(service, user_info: dict) -> None:
    """Claim ownerless rows when a caller supplies an uncached service in single-user mode."""
    repository = getattr(service, "repository", None)
    if repository is None or user_manager.is_multi_user_mode():
        return
    repository.assign_unowned_collections(user_info.get("user_id") or "legacy_user")


@router.get("/collections", response_class=HTMLResponse, include_in_schema=False)
async def collections_page():
    page = static_dir / "collections.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="collections page not found")
    version_files = [
        page,
        static_dir / "css" / "collections.css",
        static_dir / "css" / "product-linear.css",
        static_dir / "css" / "product-linear-core.css",
        static_dir / "js" / "collections.js",
        static_dir / "css" / "app-shell.css",
        static_dir / "js" / "app-shell.js",
        static_dir / "js" / "ui-features.js",
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
    _backfill_testable_single_user_owner(service, user_info)
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
                owner_user_id=user_info.get("user_id") or "",
            )
        },
    )


@router.get("/api/collections/filter-options", response_model=TranscribeResponse)
async def get_collection_filter_options(user_info: dict = Depends(verify_token)):
    service = get_collection_service()
    _backfill_testable_single_user_owner(service, user_info)
    return TranscribeResponse(
        code=200,
        message="学习集合筛选选项",
        data=service.get_filter_options(owner_user_id=user_info.get("user_id") or ""),
    )


@router.post("/api/collections", response_model=TranscribeResponse)
async def create_collection(
    body: CreateCollectionRequest,
    user_info: dict = Depends(verify_token),
):
    transcription_strategy = body.transcription_strategy
    transcription_concurrency = body.transcription_concurrency
    if body.collection_type == "document_topic":
        transcription_strategy = "local"
        transcription_concurrency = 1
    elif body.collection_type == "video_course":
        try:
            validate_transcription_selection(
                transcription_strategy, transcription_concurrency
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            owner_user_id=user_info.get("user_id") or "",
            transcription_strategy=transcription_strategy,
            transcription_concurrency=transcription_concurrency,
        )
        return TranscribeResponse(code=200, message="学习集合已创建", data=collection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/collections/{collection_id}", response_model=TranscribeResponse)
async def get_collection(collection_id: str, user_info: dict = Depends(verify_token)):
    try:
        service = get_collection_service()
        _require_collection_owner(service, collection_id, user_info)
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
        _require_collection_owner(service, collection_id, user_info)
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
        _require_collection_owner(service, collection_id, user_info)
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
            True,
            transcription_strategy=result["transcription_strategy"],
            cloud_confirmation_required=(
                result["transcription_strategy"] == "cloud"
            ),
            skip_cache=True,
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


@router.get("/api/local-fs/browse", response_model=TranscribeResponse)
async def browse_local_fs(
    path: str = Query(""),
    user_info: dict = Depends(verify_token),
):
    """Browse directories on the host machine for zero-copy path import UX."""
    try:
        data = await run_in_threadpool(browse_local_directory, path or "")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法浏览目录：{exc}") from exc
    return TranscribeResponse(code=200, message="本机目录", data=data)


@router.post("/api/local-fs/pick-folder", response_model=TranscribeResponse)
async def pick_local_fs_folder(
    user_info: dict = Depends(verify_token),
):
    """Open the OS-native folder chooser on the API host (Finder on macOS)."""
    try:
        path = await run_in_threadpool(
            pick_local_directory_native,
            "选择要导入的本机课程文件夹",
        )
        preview = await run_in_threadpool(browse_local_directory, path)
    except LocalFolderPickCancelled as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LocalFolderPickUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"打开系统文件夹选择器失败：{exc}"
        ) from exc
    return TranscribeResponse(
        code=200,
        message="已选择本机文件夹",
        data={
            "path": path,
            "media_count": preview.get("media_count", 0),
            "video_count": preview.get("video_count", 0),
            "document_count": preview.get("document_count", 0),
        },
    )


@router.post(
    "/api/collections/{collection_id}/sources/from-local-paths",
    response_model=TranscribeResponse,
    status_code=202,
)
async def import_collection_sources_from_local_paths(
    collection_id: str,
    body: LocalPathImportRequest,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    """Register local media by absolute path. Does not copy video/document files."""
    if not (body.directory or "").strip() and not (body.paths or []):
        raise HTTPException(status_code=400, detail="请提供本机目录路径或文件路径列表")

    service = get_collection_service()
    _require_collection_owner(service, collection_id, user_info)
    try:
        detail = service.get_collection_detail(collection_id)
        selected_strategy = (
            body.transcription_strategy
            if body.transcription_strategy is not None
            else detail.get("transcription_strategy") or "local"
        )
        selected_concurrency = (
            body.transcription_concurrency
            if body.transcription_concurrency is not None
            else int(detail.get("transcription_concurrency") or 1)
        )
        try:
            validate_transcription_selection(selected_strategy, selected_concurrency)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if (
            body.transcription_strategy is not None
            or body.transcription_concurrency is not None
        ):
            service.repository.update_transcription_preferences(
                collection_id,
                strategy=selected_strategy,
                requested_concurrency=selected_concurrency,
            )

        directory = body.directory or ""
        path_list = list(body.paths or [])
        candidates = await run_in_threadpool(
            lambda: service.resolve_local_import_paths(
                collection_id,
                directory=directory,
                paths=path_list,
            )
        )
        result = CollectionTranscriptionService(
            service.repository, cache_manager
        ).start_sources(
            collection_id=collection_id,
            candidates=candidates,
            owner_user_id=user_info.get("user_id") or "",
            strategy=selected_strategy,
            requested_concurrency=selected_concurrency,
            use_speaker_recognition=False,
        )
        if selected_strategy == "local" and result.effective_concurrency is not None:
            get_transcription_concurrency_controller().update_soft_limits(
                local=result.effective_concurrency
            )
        for launch in result.launches:
            background_tasks.add_task(
                process_local_upload,
                launch.task_id,
                launch.file_path,
                launch.original_name,
                launch.display_url,
                launch.media_id,
                False,
                True,  # preserve_source_file: keep original path, do not delete user media
                True,
                transcription_strategy=launch.strategy,
                cloud_confirmation_required=launch.strategy == "cloud",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "collection local-path import accepted: collection={}, count={}, pending={}",
        collection_id,
        len(result.sources),
        len(result.launches),
    )
    return TranscribeResponse(
        code=202,
        message="已按本机路径登记文件（未复制），正在逐个解析",
        data={
            "sources": list(result.sources),
            "cache_hit_count": result.cache_hit_count,
            "pending_count": len(result.launches),
            "requested_concurrency": result.requested_concurrency,
            "effective_concurrency": result.effective_concurrency,
            "path_referenced": True,
            "candidate_count": len(candidates),
        },
    )


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
    transcription_strategy: Optional[str] = Form(None),
    transcription_concurrency: Optional[int] = Form(None),
    user_info: dict = Depends(verify_token),
):
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一个文件")

    service = get_collection_service()
    _require_collection_owner(service, collection_id, user_info)
    try:
        detail = service.get_collection_detail(collection_id)
        selected_strategy = (
            transcription_strategy
            if transcription_strategy is not None
            else detail.get("transcription_strategy") or "local"
        )
        selected_concurrency = (
            transcription_concurrency
            if transcription_concurrency is not None
            else int(detail.get("transcription_concurrency") or 1)
        )
        try:
            validate_transcription_selection(selected_strategy, selected_concurrency)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        existing_positions = [
            int(source.get("position") or 0) for source in detail.get("sources", [])
        ]
        next_position = (max(existing_positions) if existing_positions else 0) + 1
        append_position = next_position
        validated_files = []
        for file in files:
            filename = source_basename(file.filename or "upload") or "upload"
            position = _source_position_from_filename(filename) or append_position
            append_position = max(append_position, position + 1)
            validated_files.append(
                {
                    "file": file,
                    "filename": filename,
                    "position": position,
                    "source_type": service.validate_source_type_for_collection(
                        collection_id, filename
                    ),
                }
            )
        if (
            transcription_strategy is not None
            or transcription_concurrency is not None
        ):
            service.repository.update_transcription_preferences(
                collection_id,
                strategy=selected_strategy,
                requested_concurrency=selected_concurrency,
            )

        candidates = []
        created_source_files: set[str] = set()
        try:
            for validated in validated_files:
                filename = validated["filename"]
                temp_path, size, file_hash = await _save_upload_file(
                    validated["file"], filename
                )
                media_id = _media_id_for_upload_hash(file_hash)
                display_url = f"local://collection-source/{media_id}/{filename}"
                try:
                    stable_path = _stable_upload_path(
                        temp_path,
                        media_id,
                        filename,
                        created_paths=created_source_files,
                    )
                except Exception:
                    if os.path.isfile(temp_path):
                        os.remove(temp_path)
                    raise
                candidates.append(
                    {
                        "file_path": stable_path,
                        "original_name": filename,
                        "display_url": display_url,
                        "media_id": media_id,
                        "content_sha256": file_hash,
                        "source_type": validated["source_type"],
                        "position": validated["position"],
                        "size": size,
                    }
                )
        except Exception:
            _remove_created_source_files(created_source_files)
            raise

        try:
            result = CollectionTranscriptionService(
                service.repository, cache_manager
            ).start_sources(
                collection_id=collection_id,
                candidates=candidates,
                owner_user_id=user_info.get("user_id") or "",
                strategy=selected_strategy,
                requested_concurrency=selected_concurrency,
                use_speaker_recognition=use_speaker_recognition,
            )
        except Exception:
            try:
                current_sources = service.repository.get_sources(collection_id)
                _cleanup_unreferenced_candidate_files(
                    candidates=candidates,
                    sources=current_sources,
                    launches=(),
                    created_paths=created_source_files,
                )
            except Exception as cleanup_exc:
                logger.warning(
                    "Failed to inspect collection source references after upload "
                    "rollback: {}",
                    cleanup_exc,
                )
            raise
        if selected_strategy == "local" and result.effective_concurrency is not None:
            get_transcription_concurrency_controller().update_soft_limits(
                local=result.effective_concurrency
            )
        _cleanup_unreferenced_candidate_files(
            candidates=candidates,
            sources=result.sources,
            launches=result.launches,
            created_paths=created_source_files,
        )
        for launch in result.launches:
            # Keep durable source media for open/re-parse UX; only intermediate
            # audio is cleaned after ASR. Prefer path import to avoid a second
            # permanent copy of on-disk course libraries.
            background_tasks.add_task(
                process_local_upload,
                launch.task_id,
                launch.file_path,
                launch.original_name,
                launch.display_url,
                launch.media_id,
                use_speaker_recognition,
                True,
                True,
                transcription_strategy=launch.strategy,
                cloud_confirmation_required=launch.strategy == "cloud",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "collection upload accepted: collection={}, count={}, pending={}",
        collection_id,
        len(result.sources),
        len(result.launches),
    )
    return TranscribeResponse(
        code=202,
        message="专题文件已上传，正在逐个解析",
        data={
            "sources": list(result.sources),
            "cache_hit_count": result.cache_hit_count,
            "pending_count": len(result.launches),
            "requested_concurrency": result.requested_concurrency,
            "effective_concurrency": result.effective_concurrency,
        },
    )


def _cloud_quote_snapshot_data(snapshot: CollectionQuoteSnapshot) -> dict:
    return {
        "state": snapshot.state,
        "video_count": snapshot.video_count,
        "cache_hit_count": snapshot.cache_hit_count,
        "pending_count": snapshot.pending_count,
        "duration_seconds": str(snapshot.duration_seconds),
        "billable_seconds": snapshot.billable_seconds,
        "max_cost_cny": str(snapshot.max_cost_cny),
        "transcription_revision": snapshot.transcription_revision,
        "items": [
            {
                "task_id": item.task_id,
                "source_id": item.source_id,
                "title": item.title,
                "quote_token": item.quote_token,
                "duration_seconds": str(item.duration_seconds),
                "billable_seconds": item.billable_seconds,
                "max_cost_cny": str(item.max_cost_cny),
            }
            for item in snapshot.items
        ],
        "failures": list(snapshot.failures),
    }


def _parse_quote_amount(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="invalid_cloud_quote_amount") from None
    if not amount.is_finite() or amount < 0:
        raise HTTPException(status_code=422, detail="invalid_cloud_quote_amount")
    return amount


def _raise_collection_transcription_value_error(exc: ValueError) -> None:
    detail = str(exc)
    if detail == "collection_not_found":
        raise HTTPException(status_code=404, detail=detail) from exc
    if detail.startswith("invalid_collection_transcription_") or detail in {
        "invalid_transcription_strategy",
        "invalid_local_transcription_concurrency",
        "invalid_cloud_transcription_concurrency",
        "invalid_transcription_concurrency",
        "invalid_collection_cloud_quote_total",
        "invalid_collection_cloud_quote_confirmation",
        "invalid_cloud_quote_amount",
    }:
        raise HTTPException(status_code=422, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


@router.get(
    "/api/collections/{collection_id}/cloud-quote",
    response_model=TranscribeResponse,
)
async def get_collection_cloud_quote(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    _backfill_testable_single_user_owner(get_collection_service(), user_info)
    service = get_collection_transcription_service()
    _require_collection_owner(service, collection_id, user_info)
    try:
        snapshot = service.get_cloud_quote_snapshot(
            collection_id, owner_user_id=user_info.get("user_id") or ""
        )
    except ValueError as exc:
        _raise_collection_transcription_value_error(exc)
    return TranscribeResponse(
        code=200,
        message="系列云端报价",
        data=_cloud_quote_snapshot_data(snapshot),
    )


@router.post(
    "/api/collections/{collection_id}/cloud-quote/refresh",
    response_model=TranscribeResponse,
)
async def refresh_collection_cloud_quote(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    _backfill_testable_single_user_owner(get_collection_service(), user_info)
    service = get_collection_transcription_service()
    _require_collection_owner(service, collection_id, user_info)
    try:
        result = service.refresh_collection_cloud_quotes(
            collection_id, owner_user_id=user_info.get("user_id") or ""
        )
    except CloudQuoteConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        _raise_collection_transcription_value_error(exc)
    return TranscribeResponse(
        code=200,
        message="系列云端报价已刷新",
        data={
            "snapshot": (
                _cloud_quote_snapshot_data(result.snapshot)
                if result.snapshot is not None
                else None
            ),
            "failures": list(result.failures),
        },
    )


@router.post(
    "/api/collections/{collection_id}/cloud-confirm",
    response_model=TranscribeResponse,
    status_code=202,
)
async def confirm_collection_cloud_quote(
    collection_id: str,
    body: CollectionCloudQuoteConfirmRequest,
    user_info: dict = Depends(verify_token),
):
    _backfill_testable_single_user_owner(get_collection_service(), user_info)
    service = get_collection_transcription_service()
    _require_collection_owner(service, collection_id, user_info)
    try:
        dispatcher = get_cloud_asr_dispatcher()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    accepted_total = _parse_quote_amount(body.accepted_total_cny)
    confirmations = tuple(
        CloudQuoteConfirmation(
            task_id=item.task_id,
            token=item.quote_token,
            accepted_max_cost=_parse_quote_amount(item.accepted_max_cost_cny),
        )
        for item in body.confirmations
    )
    try:
        result = service.confirm_collection_cloud_quotes(
            collection_id,
            owner_user_id=user_info.get("user_id") or "",
            transcription_revision=body.transcription_revision,
            confirmations=confirmations,
            accepted_total=accepted_total,
            cloud_dispatcher=dispatcher,
        )
    except CloudQuoteConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        _raise_collection_transcription_value_error(exc)
    return TranscribeResponse(
        code=202,
        message=(
            "系列云端转录确认已受理"
            if result.status == "confirmed"
            else "系列云端转录确认已受理（重复请求）"
        ),
        data={"status": result.status, "task_ids": list(result.task_ids)},
    )


@router.post(
    "/api/collections/{collection_id}/continue",
    response_model=TranscribeResponse,
    status_code=202,
)
async def continue_collection_processing(
    collection_id: str,
    body: ContinueCollectionTranscriptionRequest,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    try:
        validate_transcription_selection(
            body.transcription_strategy, body.transcription_concurrency
        )
    except ValueError as exc:
        _raise_collection_transcription_value_error(exc)

    _backfill_testable_single_user_owner(get_collection_service(), user_info)
    service = get_collection_transcription_service()
    _require_collection_owner(service, collection_id, user_info)
    try:
        result = service.continue_collection(
            collection_id,
            owner_user_id=user_info.get("user_id") or "",
            strategy=body.transcription_strategy,
            requested_concurrency=body.transcription_concurrency,
        )
    except ValueError as exc:
        _raise_collection_transcription_value_error(exc)

    for launch in result.launches:
        task = cache_manager.get_task_by_id(launch.task_id) or {}
        background_tasks.add_task(
            process_local_upload,
            launch.task_id,
            launch.file_path,
            launch.original_name,
            launch.display_url,
            launch.media_id,
            bool(task.get("use_speaker_recognition")),
            True,
            True,
            transcription_strategy=launch.strategy,
            cloud_confirmation_required=launch.strategy == "cloud",
        )
    return TranscribeResponse(
        code=202,
        message="已继续未完成的专题解析任务",
        data={
            "sources": list(result.sources),
            "pending_count": len(result.launches),
            "requested_concurrency": result.requested_concurrency,
            "effective_concurrency": result.effective_concurrency,
        },
    )


@router.post("/api/collections/{collection_id}/cancel", response_model=TranscribeResponse)
async def cancel_collection_processing(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    try:
        _backfill_testable_single_user_owner(get_collection_service(), user_info)
        service = get_collection_transcription_service()
        _require_collection_owner(service, collection_id, user_info)
        result = service.stop_collection(
            collection_id, owner_user_id=user_info.get("user_id") or ""
        )
        return TranscribeResponse(
            code=200,
            message="已停止未完成的专题解析任务",
            data={
                "collection": result.collection,
                "stopped_count": result.stopped_count,
                "canceled_count": result.stopped_count,
                "in_flight_count": result.in_flight_count,
            },
        )
    except ValueError as exc:
        _raise_collection_transcription_value_error(exc)


@router.post("/api/collections/{collection_id}/summary", response_model=TranscribeResponse)
async def generate_collection_summary(
    collection_id: str,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    """Start full-series interpretation generation.

    Generation runs in a background task so leaving the page does not cancel work.
    Clients should poll GET /api/collections/{id} until summary_status is success/failed.
    """
    try:
        service = get_collection_service()
        _require_collection_owner(service, collection_id, user_info)
        detail = await run_in_threadpool(service.begin_summary_generation, collection_id)
        should_enqueue = bool(detail.pop("summary_enqueue", False))
        if should_enqueue:
            background_tasks.add_task(service.generate_summary_job, collection_id)
        message = (
            "全系列解读生成中"
            if (detail.get("summary_status") or "").strip() == "processing"
            else "全系列解读状态已更新"
        )
        return TranscribeResponse(code=200, message=message, data=detail)
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
        _require_collection_owner(service, collection_id, user_info)
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
        _require_collection_owner(service, collection_id, user_info)
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
        _require_collection_owner(service, collection_id, user_info)
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
        _require_collection_owner(service, collection_id, user_info)
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
        _require_collection_owner(service, collection_id, user_info)
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
    except OSError as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        # errno 28: ENOSPC — disk full while writing large video batches.
        if getattr(exc, "errno", None) == 28 or "No space left on device" in str(exc):
            logger.error("save collection upload failed: disk full ({})", exc)
            raise HTTPException(
                status_code=507,
                detail=(
                    "磁盘空间不足，无法保存上传文件。"
                    "请清理 data/source_files 或系统磁盘后，"
                    "在该专题上使用「追加文件夹」重新导入。"
                ),
            ) from exc
        logger.exception(f"save collection upload failed: {exc}")
        raise HTTPException(status_code=500, detail=f"保存上传文件失败：{exc}") from exc
    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        logger.exception(f"save collection upload failed: {exc}")
        raise HTTPException(status_code=500, detail="保存上传文件失败") from exc

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


def _stable_upload_path(
    temp_path: str,
    media_id: str,
    filename: str,
    *,
    created_paths: Optional[set[str]] = None,
) -> str:
    """Persist multipart upload so open-source / re-parse keep working.

    Path-based import never uses this helper — it references the user's original
    file and avoids a second library copy. Multipart browser uploads have no
    absolute path, so a durable managed copy is required for product UX.
    """
    ext = os.path.splitext(filename)[1][:10] or ".bin"
    upload_dir = _source_files_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    stable_path = str(upload_dir / f"{media_id}-{uuid.uuid4().hex}{ext}")
    if os.path.abspath(temp_path) == os.path.abspath(stable_path):
        return stable_path
    os.replace(temp_path, stable_path)
    if created_paths is not None:
        created_paths.add(os.path.abspath(stable_path))
    return stable_path


def _remove_created_source_files(created_paths: set[str]) -> None:
    for file_path in sorted(created_paths):
        if not os.path.isfile(file_path):
            continue
        try:
            os.remove(file_path)
        except OSError as exc:
            logger.warning(
                "Failed to remove request-owned collection source file: {} ({})",
                file_path,
                exc,
            )


def _cleanup_unreferenced_candidate_files(
    *,
    candidates,
    sources,
    launches,
    created_paths: set[str],
) -> None:
    referenced_paths = {
        os.path.abspath(launch.file_path) for launch in launches
    }
    for source in sources:
        task = cache_manager.get_task_by_id(source["task_id"]) or {}
        saved_path = task.get("source_file_path")
        if saved_path:
            referenced_paths.add(os.path.abspath(str(saved_path)))
            continue
        media_id = task.get("media_id")
        if not media_id:
            continue
        ext = os.path.splitext(source.get("title") or "")[1][:10] or ".bin"
        referenced_paths.add(
            os.path.abspath(str(_source_files_dir() / f"{media_id}{ext}"))
        )

    candidate_paths = {
        os.path.abspath(str(candidate["file_path"])) for candidate in candidates
    }
    unreferenced_paths = (created_paths & candidate_paths) - referenced_paths
    for file_path in sorted(unreferenced_paths):
        if not os.path.isfile(file_path):
            continue
        try:
            os.remove(file_path)
        except OSError as exc:
            logger.warning(
                "Failed to remove unreferenced collection source file: {} ({})",
                file_path,
                exc,
            )


def _source_files_dir() -> Path:
    storage_cfg = config.get("storage", {}) or {}
    source_dir = storage_cfg.get("source_files_dir") or "./data/source_files/collection_uploads"
    return Path(source_dir)


def _ephemeral_collection_staging_dir() -> Path:
    """Temp staging for multipart uploads (deleted after each task finishes)."""
    storage_cfg = config.get("storage", {}) or {}
    temp_dir = Path(storage_cfg.get("temp_dir") or "./data/temp")
    return temp_dir / "collection_staging"
