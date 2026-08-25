"""Visual learning page and authenticated document APIs."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .collections import get_collection_service
from ..context import (
    get_cache_manager,
    get_config,
    get_logger,
    get_repository_database,
    get_static_dir,
)
from ..services.transcription import verify_token
from ...study.repository import StudyRepository
from ...study.service import StudyService
from ...visual_learning.collection_source_resolver import CollectionSourceResolver
from ...visual_learning.repository import VisualLearningRepository
from ...visual_learning.schemas import DOCUMENT_TYPES
from ...visual_learning.service import VisualLearningService
from ...visual_learning.source_resolver import (
    StudySourceResolver,
    VisualLearningSourceNotFound,
    VisualLearningSourceNotReady,
)


router = APIRouter(tags=["visual-learning"])
logger = get_logger()

_BACKGROUND_FAILURE_MESSAGE = "visual generation failed before start"


class VisualGenerationRequest(BaseModel):
    document_type: str = "overview"
    style: str = "study-notes"
    diagram_type: str = "auto"
    force: bool = False


def get_visual_learning_service() -> VisualLearningService:
    config = get_config()
    cache_manager = get_cache_manager()
    storage = config.get("storage", {}) or {}
    source_root = storage.get("source_files_dir") or "./data/source_files"
    database = get_repository_database(cache_manager)
    study_service = StudyService(
        cache_manager=cache_manager,
        repository=StudyRepository(database),
        source_root=source_root,
        llm_config=config.get("llm", {}) or {},
    )
    return VisualLearningService(
        repository=VisualLearningRepository(database),
        source_resolver=StudySourceResolver(study_service),
        llm_config=config.get("llm", {}) or {},
        collection_source_resolver=CollectionSourceResolver(
            get_collection_service()
        ),
    )


def _response(data: dict, status_code: int = 200, message: str = "success"):
    return JSONResponse(
        status_code=status_code,
        content={"code": status_code, "message": message, "data": data},
    )


def _raise_source_error(exc: Exception) -> None:
    if isinstance(exc, VisualLearningSourceNotFound):
        raise HTTPException(status_code=404, detail="学习内容不存在")
    if isinstance(exc, VisualLearningSourceNotReady):
        raise HTTPException(status_code=409, detail="学习内容仍在解析中")
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


def _validate_collection_document_type(document_type: str) -> None:
    if document_type not in {"overview", "full_note"}:
        raise ValueError("invalid document_type")


def _run_prepared_generation_safely(
    service: VisualLearningService,
    generator,
    document_id: str,
    *args: str,
) -> None:
    try:
        generator(document_id, *args)
    except Exception:
        logger.exception("visual learning background generation failed")
        try:
            record = service.repository.get_document(document_id)
            if not record or record.get("status") not in {"pending", "failed"}:
                return
            generation_token = service.repository.claim_generation(
                document_id,
                previous_token=record.get("generation_token") or "",
            )
            if generation_token:
                service.repository.save_failure(
                    document_id,
                    generation_token,
                    _BACKGROUND_FAILURE_MESSAGE,
                )
        except Exception:
            logger.exception("visual learning background failure recovery failed")


@router.get("/visual-learning", response_class=HTMLResponse, include_in_schema=False)
async def visual_learning_page():
    page = get_static_dir() / "visual-learning.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="图解生成页面不存在")
    static_dir = get_static_dir()
    version_files = [
        page,
        static_dir / "css" / "editorial.css",
        static_dir / "css" / "app-shell.css",
        static_dir / "css" / "visual-learning.css",
        static_dir / "css" / "product-linear.css",
        static_dir / "css" / "product-linear-core.css",
        static_dir / "js" / "visual-learning.js",
        static_dir / "js" / "visual-learning-workbench.js",
        static_dir / "js" / "ui-features.js",
        static_dir / "js" / "app-shell.js",
        static_dir / "js" / "pwa-register.js",
    ]
    version = str(max(
        (path.stat().st_mtime_ns for path in version_files if path.exists()),
        default=0,
    ))
    html = page.read_text(encoding="utf-8").replace("__ASSET_VERSION__", version)
    if "<base " not in html:
        html = html.replace("<head>", '<head>\n    <base href="/static/">', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@router.get("/api/visual-learning/study/{view_token}")
async def get_study_visual_state(
    view_token: str,
    document_type: str = Query(default="overview"),
    user_info: dict = Depends(verify_token),
):
    service = get_visual_learning_service()
    service.repository.recover_stale_generations(20)
    try:
        state = service.get_study_state(view_token, document_type)
    except Exception as exc:
        _raise_source_error(exc)
    return _response(state, message="视觉学习状态")


@router.post("/api/visual-learning/study/{view_token}/generate")
async def generate_study_visual(
    view_token: str,
    request: VisualGenerationRequest,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    service = get_visual_learning_service()
    service.repository.recover_stale_generations(20)
    try:
        record = service.prepare_study_generation(
            view_token,
            request.document_type,
            request.style,
            request.diagram_type,
            request.force,
        )
        if record.get("status") != "success":
            background_tasks.add_task(
                _run_prepared_generation_safely,
                service,
                service.generate_prepared_study,
                record["id"],
                view_token,
                request.document_type,
                request.style,
                request.diagram_type,
            )
        state = service.get_study_state(view_token, request.document_type)
    except VisualLearningSourceNotReady as exc:
        if exc.terminal:
            raise HTTPException(
                status_code=422,
                detail="全文分析失败，请重新提交内容",
            )
        state = service.get_study_state(view_token, request.document_type)
        return _response(
            state,
            status_code=202,
            message="全文分析仍在进行中",
        )
    except Exception as exc:
        _raise_source_error(exc)

    if record.get("status") == "success":
        return _response(state, message="已复用视觉学习内容")
    return _response(state, status_code=202, message="视觉学习内容生成中")


@router.get("/api/visual-learning/collections/{collection_id}")
async def get_collection_visual_state(
    collection_id: str,
    document_type: str = Query(default="overview"),
    user_info: dict = Depends(verify_token),
):
    service = get_visual_learning_service()
    service.repository.recover_stale_generations(20)
    try:
        _validate_collection_document_type(document_type)
        state = service.get_collection_state(collection_id, document_type)
    except Exception as exc:
        _raise_source_error(exc)
    return _response(state, message="集合视觉学习状态")


@router.post("/api/visual-learning/collections/{collection_id}/generate")
async def generate_collection_visual(
    collection_id: str,
    request: VisualGenerationRequest,
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(verify_token),
):
    service = get_visual_learning_service()
    service.repository.recover_stale_generations(20)
    try:
        _validate_collection_document_type(request.document_type)
        record = service.prepare_collection_generation(
            collection_id,
            request.document_type,
            request.style,
            request.diagram_type,
            request.force,
        )
        if record.get("status") != "success":
            background_tasks.add_task(
                _run_prepared_generation_safely,
                service,
                service.generate_prepared_collection,
                record["id"],
                collection_id,
                request.document_type,
                request.style,
                request.diagram_type,
            )
        state = service.get_collection_state(collection_id, request.document_type)
    except VisualLearningSourceNotReady as exc:
        if exc.terminal:
            raise HTTPException(
                status_code=422,
                detail="集合摘要不可用，无法生成视觉学习内容",
            )
        state = service.get_collection_state(collection_id, request.document_type)
        return _response(
            state,
            status_code=202,
            message="集合摘要仍在生成中",
        )
    except Exception as exc:
        _raise_source_error(exc)

    if record.get("status") == "success":
        return _response(state, message="已复用集合视觉学习内容")
    return _response(state, status_code=202, message="集合视觉学习内容生成中")


@router.get("/api/visual-learning/documents")
async def list_visual_documents(
    document_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user_info: dict = Depends(verify_token),
):
    if document_type is not None and document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="invalid document_type")
    service = get_visual_learning_service()
    documents = service.repository.list_recent(document_type, limit)
    return _response({"documents": documents}, message="视觉文档历史")


@router.get("/api/visual-learning/documents/{document_id}")
async def get_visual_document(
    document_id: str,
    user_info: dict = Depends(verify_token),
):
    service = get_visual_learning_service()
    try:
        state = service.get_document_state(document_id)
    except Exception as exc:
        _raise_source_error(exc)
    if state is None:
        raise HTTPException(status_code=404, detail="视觉文档不存在")
    return _response(state, message="视觉文档详情")
