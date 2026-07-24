"""Authenticated global APIs for the configured local Obsidian Vault."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...obsidian.paths import (
    VaultPathError,
    create_vault_directory,
    list_vault_directories,
)
from ...obsidian.service import ObsidianSyncError, ObsidianSyncService
from ...study.repository import StudyRepository
from ..context import get_cache_manager, get_config
from ..services.transcription import TranscribeResponse, verify_token

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


class CreateDirectoryRequest(BaseModel):
    parent_relative_path: str = Field(default="", max_length=500)
    name: str = Field(..., min_length=1, max_length=120)


def get_obsidian_settings() -> dict:
    return dict((get_config().get("obsidian") or {}))


def _configured_settings() -> dict:
    settings = get_obsidian_settings()
    if not settings.get("enabled") or not settings.get("vault_id") or not settings.get("vault_path"):
        raise HTTPException(
            status_code=503,
            detail={"code": "obsidian_not_configured"},
        )
    return settings


@lru_cache(maxsize=1)
def get_obsidian_sync_service() -> ObsidianSyncService:
    settings = _configured_settings()
    cache_manager = get_cache_manager()
    return ObsidianSyncService(
        vault_id=str(settings["vault_id"]),
        vault_path=str(settings["vault_path"]),
        repository=StudyRepository(db_path=str(cache_manager.db_path)),
        now_provider=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


@router.get("/status", response_model=TranscribeResponse)
async def get_obsidian_status(_user_info: dict = Depends(verify_token)):
    settings = get_obsidian_settings()
    configured = bool(
        settings.get("enabled") and settings.get("vault_id") and settings.get("vault_path")
    )
    vault_path = Path(str(settings.get("vault_path") or "")).expanduser()
    available = bool(
        configured
        and vault_path.is_dir()
        and os.access(vault_path, os.R_OK | os.W_OK)
    )
    display_path = f"…/{vault_path.name}" if configured and vault_path.name else ""
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
    except (OSError, VaultPathError):
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable"})
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
            settings["vault_path"], request.parent_relative_path, request.name
        )
    except (OSError, VaultPathError):
        raise HTTPException(status_code=400, detail={"code": "invalid_vault_path"})
    return TranscribeResponse(
        code=200,
        message="Obsidian directory created",
        data={"relative_path": relative_path},
    )


__all__ = ["get_obsidian_settings", "get_obsidian_sync_service", "router"]
