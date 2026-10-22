"""Short-lived server-side browser sessions and CSRF enforcement.

Bearer tokens remain the authentication mechanism for non-browser API clients.
The browser exchanges a management token once for an opaque HttpOnly cookie;
the management token is never encoded into that cookie or returned to JavaScript.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


SESSION_COOKIE_NAME = "learnflux_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60
MIN_SESSION_TTL_SECONDS = 5 * 60
MAX_SESSION_TTL_SECONDS = 24 * 60 * 60
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class BrowserSession:
    """One opaque browser session held only in server memory."""

    session_id: str
    user_id: str
    csrf_token: str
    created_at: float
    expires_at: float
    management_identity: bool = False


@dataclass(frozen=True, slots=True)
class SessionLookup:
    """Result of looking up an opaque session identifier."""

    status: Literal["valid", "missing", "expired"]
    session: BrowserSession | None = None


class BrowserSessionStore:
    """Thread-safe, bounded, process-local browser session store.

    Sessions intentionally expire on process restart. This keeps management
    credentials out of cookies and persistent browser storage while matching
    LearnFlux's current single-process task runtime.
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        *,
        max_sessions: int = 10_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not MIN_SESSION_TTL_SECONDS <= int(ttl_seconds) <= MAX_SESSION_TTL_SECONDS:
            raise ValueError(
                f"browser session TTL must be between {MIN_SESSION_TTL_SECONDS} "
                f"and {MAX_SESSION_TTL_SECONDS} seconds"
            )
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.ttl_seconds = int(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._clock = clock
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = threading.Lock()

    def create(self, user_id: str, *, management_identity: bool = False) -> BrowserSession:
        """Create a fresh session and evict expired/oldest entries if needed."""
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")

        now = self._clock()
        session = BrowserSession(
            session_id=secrets.token_urlsafe(32),
            user_id=normalized_user_id,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + self.ttl_seconds,
            management_identity=management_identity,
        )
        with self._lock:
            self._remove_expired_locked(now)
            while len(self._sessions) >= self.max_sessions:
                oldest_id = min(
                    self._sessions,
                    key=lambda item: self._sessions[item].created_at,
                )
                self._sessions.pop(oldest_id, None)
            self._sessions[session.session_id] = session
        return session

    def resolve(self, session_id: str | None) -> SessionLookup:
        """Resolve one session while distinguishing expiry from absence."""
        if not session_id:
            return SessionLookup("missing")
        now = self._clock()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return SessionLookup("missing")
            if session.expires_at <= now:
                self._sessions.pop(session_id, None)
                return SessionLookup("expired")
            return SessionLookup("valid", session)

    def revoke(self, session_id: str | None) -> None:
        """Revoke one session if it exists."""
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def _remove_expired_locked(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


def browser_session_ttl_seconds(config: dict) -> int:
    """Return a bounded browser-session TTL from API configuration."""
    raw_value = (config.get("api") or {}).get(
        "browser_session_ttl_seconds",
        DEFAULT_SESSION_TTL_SECONDS,
    )
    if isinstance(raw_value, bool):
        return DEFAULT_SESSION_TTL_SECONDS
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_SESSION_TTL_SECONDS
    return min(max(value, MIN_SESSION_TTL_SECONDS), MAX_SESSION_TTL_SECONDS)


def get_browser_session_store(request: Request, config: dict | None = None) -> BrowserSessionStore:
    """Return the app-scoped store, lazily creating it for small test apps."""
    store = getattr(request.app.state, "browser_sessions", None)
    if isinstance(store, BrowserSessionStore):
        return store
    store = BrowserSessionStore(browser_session_ttl_seconds(config or {}))
    request.app.state.browser_sessions = store
    return store


def get_request_user_manager(request: Request, default_manager):
    """Allow an app-scoped manager while preserving the existing singleton."""
    return getattr(request.app.state, "user_manager", default_manager)


def _canonical_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if parsed.path not in {"", "/"}:
        return None
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return None
    default_port = 80 if parsed.scheme == "http" else 443
    port_suffix = f":{port}" if port and port != default_port else ""
    return f"{parsed.scheme}://{host}{port_suffix}"


def request_origin(request: Request) -> str:
    """Build the canonical origin represented by the ASGI request URL."""
    origin = _canonical_origin(f"{request.url.scheme}://{request.url.netloc}")
    if origin is None:  # pragma: no cover - Starlette always supplies a valid URL
        raise HTTPException(status_code=400, detail="请求来源无效")
    return origin


def require_same_origin(request: Request) -> None:
    """Reject missing, opaque, same-site-only, or cross-site write origins."""
    supplied_origin = _canonical_origin(request.headers.get("origin", ""))
    if supplied_origin is None or supplied_origin != request_origin(request):
        raise HTTPException(status_code=403, detail="跨站请求已拒绝")
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site and fetch_site != "same-origin":
        raise HTTPException(status_code=403, detail="跨站请求已拒绝")


def require_session_csrf(request: Request, session: BrowserSession) -> None:
    """Require exact same-origin and a per-session CSRF token for writes."""
    if request.method.upper() in _SAFE_METHODS:
        return
    require_same_origin(request)
    supplied = request.headers.get(CSRF_HEADER_NAME, "")
    if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


def resolve_session_user(request: Request, user_manager, config: dict | None = None) -> tuple[dict, BrowserSession]:
    """Resolve the opaque cookie to a currently enabled user."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    lookup = get_browser_session_store(request, config).resolve(session_id)
    if lookup.status == "expired":
        raise HTTPException(status_code=401, detail="浏览器会话已过期")
    if lookup.status != "valid" or lookup.session is None:
        raise HTTPException(status_code=401, detail="未提供授权令牌")

    if lookup.session.management_identity:
        # A mobile API key may share the owner's user_id but have fewer permissions.
        # Resolve management sessions through their original credential class.
        effective_config = getattr(request.app.state, "app_config", None) or config or {}
        token = (effective_config.get("api") or {}).get("auth_token")
        user_info = user_manager.validate_token(token) if token else None
        if user_info and user_info.get("user_id") != lookup.session.user_id:
            user_info = None
    else:
        user_info = user_manager.get_user_by_id(lookup.session.user_id)
    if not user_info or not user_info.get("enabled", True):
        get_browser_session_store(request, config).revoke(session_id)
        raise HTTPException(status_code=401, detail="浏览器会话无效")
    return user_info, lookup.session


def authenticate_request(
    request: Request | None,
    authorization: str | None,
    user_manager,
    *,
    config: dict | None = None,
) -> dict:
    """Authenticate a Bearer API client or an HttpOnly browser session."""
    if authorization:
        token_parts = authorization.split()
        if len(token_parts) != 2 or token_parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="授权令牌格式错误")
        user_info = user_manager.validate_token(token_parts[1])
        if not user_info:
            raise HTTPException(status_code=401, detail="授权令牌无效")
        if request is not None:
            request.state.auth_method = "bearer"
            request.state.user_info = user_info
        return user_info

    if request is None:
        raise HTTPException(status_code=401, detail="未提供授权令牌")

    user_info, session = resolve_session_user(request, user_manager, config)
    require_session_csrf(request, session)
    request.state.auth_method = "browser_session"
    request.state.browser_session = session
    request.state.user_info = user_info
    return user_info


def public_user_info(user_info: dict) -> dict[str, str]:
    """Return the minimal non-secret identity exposed to browser JavaScript."""
    return {
        "user_id": str(user_info.get("user_id") or ""),
        "name": str(user_info.get("name") or user_info.get("user_id") or ""),
    }
