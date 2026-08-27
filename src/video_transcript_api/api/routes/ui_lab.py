"""Local-only routes for isolated LearnFlux UI experiments."""

from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
_STATIC_DIR = _WEB_ROOT / "static"
templates = Jinja2Templates(directory=str(_WEB_ROOT / "templates"))

_LOCAL_TEST_CLIENT = "testclient"
_UI_LAB_ASSETS = (
    Path("css/ui-lab.css"),
    Path("js/ui-lab.js"),
)
_REVIEW_UI_LAB_ASSETS = (
    Path("css/review-ui-lab.css"),
    Path("js/review-ui-lab.js"),
)


def ui_lab_enabled(config: dict) -> bool:
    """Return whether the isolated UI lab is explicitly enabled."""
    return config.get("api", {}).get("ui_lab_enabled") is True


def _is_loopback_host(host: str | None) -> bool:
    """Return whether a hostname is explicitly local to this machine."""
    normalized = (host or "").strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_local_ui_lab_request(request: Request) -> bool:
    """Require both the TCP client and requested Host to be local.

    Checking both values keeps the route unavailable behind a public reverse
    proxy even when the proxy itself connects from a loopback address.
    """
    client_host = request.client.host if request.client else ""
    client_is_local = (
        client_host == _LOCAL_TEST_CLIENT or _is_loopback_host(client_host)
    )
    return client_is_local and _is_loopback_host(request.url.hostname)


def _asset_version(
    static_dir: Path,
    assets: tuple[Path, ...] = _UI_LAB_ASSETS,
) -> str:
    mtimes = [
        (static_dir / asset).stat().st_mtime_ns
        for asset in assets
        if (static_dir / asset).exists()
    ]
    return str(max(mtimes, default=0))


def _secure_lab_response(response: HTMLResponse) -> HTMLResponse:
    """Apply the shared no-write and local-preview response policy."""
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'none'; "
                "media-src 'none'; "
                "object-src 'none'; "
                "base-uri 'none'; "
                "form-action 'none'; "
                "frame-ancestors 'self'"
            ),
        }
    )
    return response


@router.get("/ui-lab", response_class=HTMLResponse, include_in_schema=False)
async def ui_lab_page(request: Request):
    """Render the mock-only UI lab for local development requests."""
    if not is_local_ui_lab_request(request):
        raise HTTPException(status_code=404, detail="page not found")

    response = templates.TemplateResponse(
        request=request,
        name="ui_lab.html",
        context={"asset_version": _asset_version(_STATIC_DIR)},
    )
    return _secure_lab_response(response)


@router.get(
    "/ui-lab/review",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def review_ui_lab_page(request: Request):
    """Render the mock-only review redesign lab for local requests."""
    if not is_local_ui_lab_request(request):
        raise HTTPException(status_code=404, detail="page not found")

    response = templates.TemplateResponse(
        request=request,
        name="review_ui_lab.html",
        context={
            "asset_version": _asset_version(
                _STATIC_DIR,
                _REVIEW_UI_LAB_ASSETS,
            )
        },
    )
    return _secure_lab_response(response)
