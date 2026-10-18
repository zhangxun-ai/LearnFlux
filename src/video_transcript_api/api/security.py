"""Web transport-security policy for the FastAPI application."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        # Inline handlers/styles remain temporarily allowed for legacy templates;
        # object, framing, base, and outbound origins are still fail-closed.
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
        "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net",
        "img-src 'self' data: blob: https:",
        "media-src 'self' blob: https:",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "interest-cohort=()"
    ),
    "X-Frame-Options": "DENY",
}


class SecurityHeadersMiddleware:
    """Attach the shared security policy to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
                if scope.get("scheme") == "https" and "Strict-Transport-Security" not in headers:
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _normalize_cors_origin(raw_origin: str) -> str:
    value = raw_origin.strip()
    if value in {"*", "null"}:
        raise ValueError("CORS wildcard and opaque origins are not allowed")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"invalid CORS origin: {raw_origin!r}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"CORS origin must use HTTP or HTTPS: {raw_origin!r}")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(f"CORS origin must not include credentials or a path: {raw_origin!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid CORS origin port: {raw_origin!r}") from exc
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = 80 if parsed.scheme == "http" else 443
    suffix = f":{port}" if port and port != default_port else ""
    return f"{parsed.scheme}://{hostname}{suffix}"


def resolve_cors_origins(config: dict) -> list[str]:
    """Read and validate explicit credentialed browser API origins."""
    configured = (config.get("api") or {}).get("cors_allowed_origins", [])
    if configured in (None, ""):
        return []
    if isinstance(configured, str) or not isinstance(configured, Sequence):
        raise ValueError("api.cors_allowed_origins must be an array of origins")

    origins: list[str] = []
    seen: set[str] = set()
    for raw_origin in configured:
        if not isinstance(raw_origin, str) or not raw_origin.strip():
            raise ValueError("CORS origins must be non-empty strings")
        origin = _normalize_cors_origin(raw_origin)
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins


def configure_web_security(app: FastAPI, config: dict) -> None:
    """Install fail-closed CORS plus shared response security headers."""
    allowed_origins = resolve_cors_origins(config)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
            max_age=600,
        )
    # Added last so security headers also wrap CORS-generated responses.
    app.add_middleware(SecurityHeadersMiddleware)
