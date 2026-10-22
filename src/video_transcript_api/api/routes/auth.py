"""Browser-session endpoints for the LearnFlux web interface."""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..browser_auth import (
    SESSION_COOKIE_NAME,
    get_browser_session_store,
    public_user_info,
    require_same_origin,
    require_session_csrf,
    resolve_session_user,
)
from ..context import get_config, get_user_manager


router = APIRouter(prefix="/api/auth", tags=["auth"])


class BrowserLoginRequest(BaseModel):
    """One-time management-token exchange payload."""

    management_token: str = Field(min_length=1, max_length=4096)


def _config(request: Request) -> dict:
    configured = getattr(request.app.state, "app_config", None)
    return configured if isinstance(configured, dict) else get_config()


def _user_manager(request: Request):
    configured = getattr(request.app.state, "user_manager", None)
    return configured if configured is not None else get_user_manager()


def _cookie_secure(request: Request) -> bool:
    forced = (_config(request).get("api") or {}).get("browser_session_cookie_secure")
    return request.url.scheme == "https" or forced is True


def _no_store_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Vary": "Cookie",
    }


def _session_payload(session, user_info: dict) -> dict:
    return {
        "authenticated": True,
        "expires_at": datetime.fromtimestamp(session.expires_at, tz=UTC).isoformat(),
        "csrf_token": session.csrf_token,
        "user": public_user_info(user_info),
    }


def _local_auto_login_allowed(request: Request) -> bool:
    """Trust only direct loopback browser requests, never forwarded traffic."""
    api = _config(request).get("api") or {}
    if api.get("browser_local_auto_login", True) is not True:
        return False
    if request.headers.get("sec-fetch-site") != "same-origin":
        return False
    if any(name == "forwarded" or name.startswith("x-forwarded-")
           or name == "x-real-ip" for name in request.headers):
        return False
    try:
        if request.client is None or not ip_address(request.client.host).is_loopback:
            return False
        host = request.url.hostname
        if host != "localhost" and not ip_address(host or "").is_loopback:
            return False
    except ValueError:
        return False
    if request.headers.get("origin"):
        require_same_origin(request)
    return True


def _create_session_response(request: Request, user_info: dict) -> JSONResponse:
    """Issue the same opaque cookie for manual and local automatic login."""
    store = get_browser_session_store(request, _config(request))
    store.revoke(request.cookies.get(SESSION_COOKIE_NAME))
    session = store.create(
        user_info.get("user_id") or "",
        management_identity=user_info.get("is_legacy") is True,
    )
    response = JSONResponse(
        _session_payload(session, user_info),
        headers=_no_store_headers(),
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.session_id,
        max_age=store.ttl_seconds,
        expires=store.ttl_seconds,
        path="/",
        secure=_cookie_secure(request),
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/session")
async def create_browser_session(body: BrowserLoginRequest, request: Request):
    """Exchange a management token for a short-lived opaque browser cookie."""
    require_same_origin(request)
    manager = _user_manager(request)
    user_info = manager.validate_token(body.management_token)
    if not user_info or not user_info.get("enabled", True):
        raise HTTPException(status_code=401, detail="管理口令无效")

    return _create_session_response(request, user_info)


@router.get("/session")
async def get_browser_session(request: Request):
    """Return current browser identity and the in-memory CSRF token."""
    try:
        user_info, session = resolve_session_user(
            request,
            _user_manager(request),
            _config(request),
        )
    except HTTPException as error:
        if error.status_code != 401 or not _local_auto_login_allowed(request):
            raise
        manager = _user_manager(request)
        api = _config(request).get("api") or {}
        if manager.is_multi_user_mode() and api.get("browser_local_management_access") is not True:
            raise error
        token = api.get("auth_token")
        user_info = manager.validate_token(token) if token else None
        if not user_info or not user_info.get("enabled", True):
            raise error
        return _create_session_response(request, user_info)
    return JSONResponse(
        _session_payload(session, user_info),
        headers=_no_store_headers(),
    )


@router.delete("/session", status_code=204)
async def delete_browser_session(request: Request):
    """Revoke the current browser session after same-origin CSRF validation."""
    _user_info, session = resolve_session_user(
        request,
        _user_manager(request),
        _config(request),
    )
    require_session_csrf(request, session)
    get_browser_session_store(request, _config(request)).revoke(session.session_id)
    response = Response(status_code=204, headers=_no_store_headers())
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(request),
        httponly=True,
        samesite="strict",
    )
    return response
