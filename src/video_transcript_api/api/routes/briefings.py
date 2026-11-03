"""Authenticated local workbench access to already published daily reports."""
from __future__ import annotations

import mimetypes
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ...briefings.service import BriefingError, BriefingService, load_settings, reading_html
from ...briefings.bridge_runner import edition_date
from ...exports.delivery import load_archive_config
from ..assets import get_static_asset_version
from ..context import get_config, get_static_dir, get_templates, get_user_manager
from ..services.transcription import verify_token

router = APIRouter(tags=["briefings"])
NO_STORE = {"Cache-Control": "no-store, private", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}
READING_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; script-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; sandbox allow-same-origin allow-popups allow-popups-to-escape-sandbox"


def local_request(request: Request) -> None:
    peer = request.client.host if request.client else ""
    if peer not in {"127.0.0.1", "::1"} or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "日报仅在这台电脑的本地工作台中开放。")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "请从本地工作台打开日报。")
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "日报请求来源不匹配。")


def authorized_service(request: Request, user: dict = Depends(verify_token)) -> BriefingService:
    local_request(request)
    settings = load_settings()
    if settings.get("enabled") is not True or not settings.get("source_root") or not settings.get("owner_user_id"):
        raise HTTPException(503, "尚未连接本机日报来源。")
    if user.get("user_id") != settings["owner_user_id"]:
        raise HTTPException(403, "当前账户没有读取这份个人日报的权限。")
    try:
        feishu = load_archive_config()
    except (OSError, ValueError, TypeError):
        # Optional delivery configuration must not disable local reading.
        feishu = None
    if feishu:
        matched = [u for u in get_user_manager().list_all_users() if u.get("enabled", True) and u.get("name") == feishu.get("api_user_name") and u.get("user_id") == user["user_id"]]
        if not matched: feishu = None
    return BriefingService(settings, obsidian=get_config().get("obsidian"), feishu=feishu)


async def invoke(call, *args, **kwargs):
    try:
        return await run_in_threadpool(call, *args, **kwargs)
    except BriefingError as exc:
        raise HTTPException(409, str(exc), headers=NO_STORE) from None
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, "日报暂不可读取或同步，请稍后重试。", headers=NO_STORE) from None


@router.get("/briefings", response_class=HTMLResponse, include_in_schema=False)
async def briefings_page(request: Request):
    # Empty shell only. Content, images and exports all require owner auth.
    version = get_static_asset_version(get_static_dir())
    return get_templates().TemplateResponse(request=request, name="briefings.html", context={"title": "日报", "asset_ver": version}, headers=NO_STORE)


@router.get("/api/briefings")
async def list_briefings(service: BriefingService = Depends(authorized_service)):
    return JSONResponse(await invoke(service.catalog), headers=NO_STORE)


@router.get("/api/briefings/{kind}/{bundle}/files/{name:path}")
async def report_file(kind: Literal["ai", "wechat"], bundle: str, name: str, service: BriefingService = Depends(authorized_service)):
    body = await invoke(service.read, kind, bundle, name)
    headers = dict(NO_STORE)
    if name.endswith(".html"):
        body = await invoke(reading_html, body, kind)
        headers.update({"Content-Security-Policy": READING_CSP, "X-Frame-Options": "SAMEORIGIN"})
        media_type = "text/html"
    elif name == "report.md":
        headers["Content-Disposition"] = f'attachment; filename="{kind}-{edition_date(kind, bundle)}.md"'
        media_type = "text/markdown"
    else:
        media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(body, media_type=media_type, headers=headers)


@router.get("/api/briefings/{kind}/{bundle}/preview/{destination}")
async def preview_briefing(kind: Literal["ai", "wechat"], bundle: str, destination: Literal["obsidian", "feishu"], service: BriefingService = Depends(authorized_service)):
    return JSONResponse(await invoke(service.preview, kind, bundle, destination), headers=NO_STORE)


class SyncRequest(BaseModel):
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: bool = False
    confirm_private: bool = False


@router.post("/api/briefings/{kind}/{bundle}/sync/{destination}")
async def sync_briefing(kind: Literal["ai", "wechat"], bundle: str, destination: Literal["obsidian", "feishu"], payload: SyncRequest, service: BriefingService = Depends(authorized_service)):
    result = await invoke(service.sync, kind, bundle, destination, payload.content_sha256, confirm=payload.confirm, confirm_private=payload.confirm_private)
    return JSONResponse(result, headers=NO_STORE)
