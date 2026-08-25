"""Authenticated global APIs for the configured local Obsidian Vault."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator

from ...llm import call_llm_api
from ...obsidian.knowledge_categories import (
    CategoryRecommendation,
    ObsidianCategoryRecommender,
)
from ...obsidian.knowledge_repository import (
    KnowledgeRevisionConflict,
    ObsidianKnowledgeRepository,
)
from ...obsidian.knowledge_service import (
    KnowledgeStalePreview,
    ObsidianKnowledgeService,
)
from ...obsidian.knowledge_sources import (
    KnowledgeContentNotReady,
    ObsidianKnowledgeSourceResolver,
)
from ...obsidian.paths import (
    ManagedFileConflict,
    VaultPathError,
    create_vault_directory,
    list_raw_categories,
    list_vault_directories,
)
from ...obsidian.service import ObsidianSyncService
from ...study.repository import StudyRepository
from ..context import get_cache_manager, get_config, get_repository_database
from ..services.transcription import TranscribeResponse, verify_token

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


class CreateDirectoryRequest(BaseModel):
    parent_relative_path: str = Field(default="", max_length=500)
    name: str = Field(..., min_length=1, max_length=120)


class KnowledgeBindingRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=120)
    collection_directory: str = Field(default="", max_length=160)
    expected_revision: int | None = Field(None, ge=1)


class KnowledgePreviewRequest(BaseModel):
    force: bool = False


class KnowledgeCollectionSelectionRequest(BaseModel):
    source_ids: list[str] | None = None
    sync_all: bool = False
    force: bool = False

    @model_validator(mode="after")
    def validate_selection(self):
        if self.force and not self.sync_all:
            raise ValueError("force_requires_sync_all")
        if not self.sync_all and not self.source_ids:
            raise ValueError("source_ids_required")
        if self.source_ids is not None:
            self.source_ids = list(dict.fromkeys(self.source_ids))
        return self


class KnowledgeApplyPreconditionModel(BaseModel):
    context_key: str = Field(..., min_length=1, max_length=500)
    document_type: str = Field(..., pattern="^(raw|analysis)$")
    relative_path: str = Field(..., min_length=1, max_length=1000)
    desired_hash: str = Field(..., min_length=1, max_length=128)
    existing_hash: str = Field(..., min_length=1, max_length=128)


class KnowledgeApplyRequest(KnowledgePreviewRequest):
    expected_binding_revision: int = Field(..., ge=1)
    preconditions: list[KnowledgeApplyPreconditionModel] = Field(
        ..., min_length=1
    )


class KnowledgeCollectionApplyRequest(KnowledgeCollectionSelectionRequest):
    expected_binding_revision: int = Field(..., ge=1)
    preconditions: list[KnowledgeApplyPreconditionModel] = Field(
        ..., min_length=1
    )


def get_obsidian_settings() -> dict:
    return dict((get_config().get("obsidian") or {}))


def _configured_settings() -> dict:
    settings = get_obsidian_settings()
    if (
        not settings.get("enabled")
        or not settings.get("vault_id")
        or not settings.get("vault_path")
    ):
        raise HTTPException(
            status_code=503,
            detail={"code": "obsidian_not_configured"},
        )
    return settings


@lru_cache(maxsize=1)
def get_obsidian_sync_service() -> ObsidianSyncService:
    """Return the existing Study note synchronization service unchanged."""
    settings = _configured_settings()
    cache_manager = get_cache_manager()
    return ObsidianSyncService(
        vault_id=str(settings["vault_id"]),
        vault_path=str(settings["vault_path"]),
        repository=StudyRepository(
            db_path=get_repository_database(cache_manager)
        ),
        now_provider=lambda: datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    )


def get_obsidian_knowledge_repository() -> ObsidianKnowledgeRepository:
    cache_manager = get_cache_manager()
    return ObsidianKnowledgeRepository(
        get_repository_database(cache_manager)
    )


def get_obsidian_knowledge_service() -> ObsidianKnowledgeService:
    settings = _configured_settings()
    return ObsidianKnowledgeService(
        vault_path=settings["vault_path"],
        repository=get_obsidian_knowledge_repository(),
        raw_root=str(settings.get("knowledge_raw_root") or "raw"),
        processed_root=str(
            settings.get("knowledge_processed_root") or "processed"
        ),
        now_provider=lambda: datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    )


def get_obsidian_source_resolver() -> ObsidianKnowledgeSourceResolver:
    from .collections import get_collection_service

    return ObsidianKnowledgeSourceResolver(
        cache_manager=get_cache_manager(),
        collection_service=get_collection_service(),
    )


def get_obsidian_category_recommender() -> ObsidianCategoryRecommender:
    config = get_config()
    llm = config.get("llm") or {}
    model = str(llm.get("summary_model") or "deepseek-v4-flash")
    reasoning_effort = llm.get("summary_reasoning_effort")

    def invoke(*, prompt: str, response_schema: dict[str, Any]):
        return call_llm_api(
            model=model,
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            task_type="obsidian_category",
            response_schema=response_schema,
            config=config,
            system_prompt=(
                "你是 LearnFlux 知识分类助手。只能返回给定候选分类中的一个。"
            ),
        )

    return ObsidianCategoryRecommender(invoke)


def _require_owned_single_content(view_token: str, user_info: dict) -> None:
    from .study import _require_owned_single

    _require_owned_single(view_token, user_info)
    if not get_cache_manager().get_task_by_view_token(view_token):
        raise HTTPException(
            status_code=404, detail={"code": "content_not_found"}
        )


def _require_owned_collection(collection_id: str, user_info: dict) -> None:
    from .collections import (
        _backfill_testable_single_user_owner,
        _require_collection_owner,
        get_collection_service,
    )

    service = get_collection_service()
    _backfill_testable_single_user_owner(service, user_info)
    _require_collection_owner(service, collection_id, user_info)
    try:
        service.get_collection_detail(collection_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "collection_not_found"}
        ) from exc


def _categories(settings: dict) -> list[str]:
    try:
        return list_raw_categories(
            settings["vault_path"],
            raw_root=str(settings.get("knowledge_raw_root") or "raw"),
        )
    except (OSError, VaultPathError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "vault_unavailable"}
        ) from exc


def _recommendation_data(
    recommendation: CategoryRecommendation | Any,
) -> dict[str, Any]:
    return {
        "category": str(recommendation.category),
        "confidence": float(recommendation.confidence),
        "reason": str(recommendation.reason),
        "recommended_by": str(recommendation.recommended_by),
    }


def _resolve_single(user_info: dict, view_token: str):
    _require_owned_single_content(view_token, user_info)
    try:
        return get_obsidian_source_resolver().resolve_single(
            user_info.get("user_id") or "", view_token
        )
    except KnowledgeContentNotReady as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code}
        ) from exc


def _resolve_collection(
    user_info: dict,
    collection_id: str,
    source_ids: list[str] | None,
):
    _require_owned_collection(collection_id, user_info)
    try:
        return get_obsidian_source_resolver().resolve_collection(
            user_info.get("user_id") or "",
            collection_id,
            source_ids,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "collection_not_found"}
        ) from exc


def _get_binding(
    *,
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    settings: dict,
) -> dict[str, Any] | None:
    return get_obsidian_knowledge_repository().get_binding(
        owner_user_id,
        scope_type,
        scope_id,
        str(settings["vault_id"]),
    )


def _required_binding(
    *,
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    settings: dict,
) -> dict[str, Any]:
    binding = _get_binding(
        owner_user_id=owner_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        settings=settings,
    )
    if binding is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "binding_not_configured"},
        )
    return binding


def _save_binding(
    *,
    user_info: dict,
    scope_type: str,
    scope_id: str,
    request: KnowledgeBindingRequest,
    settings: dict,
) -> dict[str, Any]:
    if request.category not in _categories(settings):
        raise HTTPException(
            status_code=409, detail={"code": "invalid_category"}
        )
    collection_directory = request.collection_directory.strip()
    if scope_type == "collection" and not collection_directory:
        raise HTTPException(
            status_code=422,
            detail={"code": "collection_directory_required"},
        )
    if scope_type == "single":
        collection_directory = ""
    try:
        return get_obsidian_knowledge_repository().save_binding(
            user_info.get("user_id") or "",
            scope_type,
            scope_id,
            str(settings["vault_id"]),
            request.category,
            collection_directory,
            request.expected_revision,
        )
    except KnowledgeRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "binding_revision_conflict"},
        ) from exc
    except VaultPathError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_vault_path"}
        ) from exc


def _preview_counts(data: MappingLike) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in data.get("items", []):
        for document in item.get("documents", []):
            state = str(document.get("state") or "")
            counts[state] = counts.get(state, 0) + 1
    return counts


class MappingLike(dict):
    """Typing helper for JSON-shaped route data."""


def _preview_response(data: dict[str, Any], unavailable: list[dict]) -> dict:
    return {
        **data,
        "unavailable": unavailable,
        "counts": _preview_counts(MappingLike(data)),
    }


def _map_sync_conflict(exc: Exception) -> HTTPException:
    if isinstance(exc, KnowledgeStalePreview):
        detail: dict[str, Any] = {"code": "stale_preview"}
        if exc.latest_preview is not None:
            detail["latest_preview"] = exc.latest_preview
        return HTTPException(status_code=409, detail=detail)
    if isinstance(exc, ManagedFileConflict):
        return HTTPException(
            status_code=409, detail={"code": "managed_identity_conflict"}
        )
    if isinstance(exc, (VaultPathError, OSError)):
        return HTTPException(
            status_code=409, detail={"code": "vault_unavailable"}
        )
    raise exc


@router.get("/knowledge/categories", response_model=TranscribeResponse)
async def knowledge_categories(
    _user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    return TranscribeResponse(
        code=200,
        message="Knowledge categories",
        data={"items": _categories(settings)},
    )


@router.post(
    "/knowledge/single/{view_token}/recommend-category",
    response_model=TranscribeResponse,
)
async def recommend_knowledge_single(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    item = _resolve_single(user_info, view_token)
    recommendation = await run_in_threadpool(
        get_obsidian_category_recommender().recommend,
        candidates=_categories(settings),
        title=item.title,
        analysis_excerpt=item.analysis_content,
        raw_excerpt=item.raw_content,
    )
    return TranscribeResponse(
        code=200,
        message="Knowledge category recommendation",
        data=_recommendation_data(recommendation),
    )


@router.post(
    "/knowledge/collections/{collection_id}/recommend-category",
    response_model=TranscribeResponse,
)
async def recommend_knowledge_collection(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    collection, items, unavailable = _resolve_collection(
        user_info, collection_id, None
    )
    recommendation = await run_in_threadpool(
        get_obsidian_category_recommender().recommend_collection,
        candidates=_categories(settings),
        collection=collection,
        items=items,
    )
    return TranscribeResponse(
        code=200,
        message="Knowledge category recommendation",
        data={
            **_recommendation_data(recommendation),
            "unavailable": unavailable,
        },
    )


@router.get(
    "/knowledge/single/{view_token}/binding",
    response_model=TranscribeResponse,
)
async def knowledge_single_binding(
    view_token: str,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    _require_owned_single_content(view_token, user_info)
    binding = _get_binding(
        owner_user_id=user_info.get("user_id") or "",
        scope_type="single",
        scope_id=view_token,
        settings=settings,
    )
    return TranscribeResponse(
        code=200, message="Knowledge binding", data={"binding": binding}
    )


@router.put(
    "/knowledge/single/{view_token}/binding",
    response_model=TranscribeResponse,
)
async def save_knowledge_single_binding(
    view_token: str,
    request: KnowledgeBindingRequest,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    _require_owned_single_content(view_token, user_info)
    binding = _save_binding(
        user_info=user_info,
        scope_type="single",
        scope_id=view_token,
        request=request,
        settings=settings,
    )
    return TranscribeResponse(
        code=200,
        message="Knowledge binding saved",
        data={"binding": binding},
    )


@router.get(
    "/knowledge/collections/{collection_id}/binding",
    response_model=TranscribeResponse,
)
async def knowledge_collection_binding(
    collection_id: str,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    _require_owned_collection(collection_id, user_info)
    binding = _get_binding(
        owner_user_id=user_info.get("user_id") or "",
        scope_type="collection",
        scope_id=collection_id,
        settings=settings,
    )
    collection, _items, _unavailable = _resolve_collection(
        user_info, collection_id, []
    )
    creator = (
        collection.get("creator_name")
        or collection.get("creator")
        or ""
    )
    default_directory = "-".join(
        part
        for part in (str(creator).strip(), str(collection.get("title") or "").strip())
        if part
    )
    return TranscribeResponse(
        code=200,
        message="Knowledge binding",
        data={
            "binding": binding,
            "default_collection_directory": default_directory,
        },
    )


@router.put(
    "/knowledge/collections/{collection_id}/binding",
    response_model=TranscribeResponse,
)
async def save_knowledge_collection_binding(
    collection_id: str,
    request: KnowledgeBindingRequest,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    _require_owned_collection(collection_id, user_info)
    binding = _save_binding(
        user_info=user_info,
        scope_type="collection",
        scope_id=collection_id,
        request=request,
        settings=settings,
    )
    return TranscribeResponse(
        code=200,
        message="Knowledge binding saved",
        data={"binding": binding},
    )


@router.post(
    "/knowledge/single/{view_token}/preview",
    response_model=TranscribeResponse,
)
async def preview_knowledge_single(
    view_token: str,
    request: KnowledgePreviewRequest,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    item = _resolve_single(user_info, view_token)
    binding = _required_binding(
        owner_user_id=user_info.get("user_id") or "",
        scope_type="single",
        scope_id=view_token,
        settings=settings,
    )
    try:
        data = get_obsidian_knowledge_service().preview(
            items=[item], binding=binding, force=request.force
        )
    except Exception as exc:
        raise _map_sync_conflict(exc)
    return TranscribeResponse(
        code=200, message="Knowledge preview", data=data
    )


@router.post(
    "/knowledge/single/{view_token}/apply",
    response_model=TranscribeResponse,
)
async def apply_knowledge_single(
    view_token: str,
    request: KnowledgeApplyRequest,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    item = _resolve_single(user_info, view_token)
    binding = _required_binding(
        owner_user_id=user_info.get("user_id") or "",
        scope_type="single",
        scope_id=view_token,
        settings=settings,
    )
    try:
        data = get_obsidian_knowledge_service().apply(
            items=[item],
            binding=binding,
            expected_binding_revision=request.expected_binding_revision,
            preconditions=[
                condition.model_dump()
                for condition in request.preconditions
            ],
            force=request.force,
        )
    except Exception as exc:
        raise _map_sync_conflict(exc)
    return TranscribeResponse(
        code=200, message="Knowledge applied", data=data
    )


@router.post(
    "/knowledge/collections/{collection_id}/preview",
    response_model=TranscribeResponse,
)
async def preview_knowledge_collection(
    collection_id: str,
    request: KnowledgeCollectionSelectionRequest,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    collection, items, unavailable = _resolve_collection(
        user_info,
        collection_id,
        None if request.sync_all else request.source_ids,
    )
    del collection
    binding = _required_binding(
        owner_user_id=user_info.get("user_id") or "",
        scope_type="collection",
        scope_id=collection_id,
        settings=settings,
    )
    try:
        data = get_obsidian_knowledge_service().preview(
            items=items, binding=binding, force=request.force
        )
    except Exception as exc:
        raise _map_sync_conflict(exc)
    return TranscribeResponse(
        code=200,
        message="Knowledge preview",
        data=_preview_response(data, unavailable),
    )


@router.post(
    "/knowledge/collections/{collection_id}/apply",
    response_model=TranscribeResponse,
)
async def apply_knowledge_collection(
    collection_id: str,
    request: KnowledgeCollectionApplyRequest,
    user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    _collection, items, unavailable = _resolve_collection(
        user_info,
        collection_id,
        None if request.sync_all else request.source_ids,
    )
    binding = _required_binding(
        owner_user_id=user_info.get("user_id") or "",
        scope_type="collection",
        scope_id=collection_id,
        settings=settings,
    )
    try:
        data = get_obsidian_knowledge_service().apply(
            items=items,
            binding=binding,
            expected_binding_revision=request.expected_binding_revision,
            preconditions=[
                condition.model_dump()
                for condition in request.preconditions
            ],
            force=request.force,
        )
    except Exception as exc:
        raise _map_sync_conflict(exc)
    return TranscribeResponse(
        code=200,
        message="Knowledge applied",
        data={**data, "unavailable": unavailable},
    )


@router.get("/status", response_model=TranscribeResponse)
async def get_obsidian_status(
    _user_info: dict = Depends(verify_token),
):
    settings = get_obsidian_settings()
    configured = bool(
        settings.get("enabled")
        and settings.get("vault_id")
        and settings.get("vault_path")
    )
    vault_path = Path(str(settings.get("vault_path") or "")).expanduser()
    available = bool(
        configured
        and vault_path.is_dir()
        and os.access(vault_path, os.R_OK | os.W_OK)
    )
    display_path = (
        f"…/{vault_path.name}" if configured and vault_path.name else ""
    )
    return TranscribeResponse(
        code=200,
        message="Obsidian Vault status",
        data={
            "enabled": bool(settings.get("enabled")),
            "configured": configured,
            "vault_id": str(settings.get("vault_id") or ""),
            "available": available,
            "display_path": display_path,
        },
    )


@router.get("/directories", response_model=TranscribeResponse)
async def get_obsidian_directories(
    root: str = Query("vault", pattern="^(raw|vault)$"),
    q: str = Query("", max_length=160),
    _user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    try:
        directories = list_vault_directories(
            settings["vault_path"], root=root, query=q
        )
    except (OSError, VaultPathError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "vault_unavailable"}
        ) from exc
    return TranscribeResponse(
        code=200,
        message="Obsidian directories",
        data={"items": directories},
    )


@router.post("/directories", response_model=TranscribeResponse)
async def create_obsidian_directory(
    request: CreateDirectoryRequest,
    _user_info: dict = Depends(verify_token),
):
    settings = _configured_settings()
    try:
        relative_path = create_vault_directory(
            settings["vault_path"],
            request.parent_relative_path,
            request.name,
        )
    except (OSError, VaultPathError) as exc:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_vault_path"}
        ) from exc
    return TranscribeResponse(
        code=200,
        message="Obsidian directory created",
        data={"relative_path": relative_path},
    )


__all__ = [
    "get_obsidian_settings",
    "get_obsidian_sync_service",
    "router",
]
