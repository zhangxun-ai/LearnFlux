"""Browser session, CSRF, CORS, and HTTP security-header contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.api.browser_auth import BrowserSessionStore
from video_transcript_api.api.routes import auth as auth_routes
from video_transcript_api.api.security import configure_web_security, resolve_cors_origins
from video_transcript_api.api.services.transcription import verify_token


VALID_TOKEN = "test-management-token"
SAME_ORIGIN = "http://testserver"


class FakeUserManager:
    """Small deterministic user manager used only by these unit tests."""

    def is_multi_user_mode(self):
        return False

    def validate_token(self, token: str):
        if token != VALID_TOKEN:
            return None
        return {
            "user_id": "test-user",
            "name": "Test User",
            "api_key": VALID_TOKEN,
            "enabled": True,
            "permissions": ["recalibrate"],
        }

    def get_user_by_id(self, user_id: str):
        if user_id != "test-user":
            return None
        return self.validate_token(VALID_TOKEN)


@dataclass
class MutableClock:
    value: float = 1_000.0

    def __call__(self) -> float:
        return self.value


def _session_app(*, clock: MutableClock | None = None) -> FastAPI:
    app = FastAPI()
    app.state.user_manager = FakeUserManager()
    app.state.browser_sessions = BrowserSessionStore(
        ttl_seconds=300,
        clock=clock or MutableClock(),
    )
    app.include_router(auth_routes.router)

    @app.get("/protected")
    async def protected_get(user_info: dict = Depends(verify_token)):
        return {"user_id": user_info["user_id"]}

    @app.post("/protected")
    async def protected_post(user_info: dict = Depends(verify_token)):
        return {"user_id": user_info["user_id"]}

    return app


def _login(client: TestClient, origin: str = SAME_ORIGIN):
    return client.post(
        "/api/auth/session",
        json={"management_token": VALID_TOKEN},
        headers={"Origin": origin},
    )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_local_browser_connects_without_token_after_reopen_expiry_and_restart(host):
    clock = MutableClock()
    app = _session_app(clock=clock)
    app.state.app_config = {"api": {"auth_token": VALID_TOKEN}}
    # This Starlette TestClient version cannot parse IPv6 URL netlocs.
    # Supplying Host still exercises the actual ASGI request URL and origin checks.
    client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000),
                        headers={"Host": host})
    headers = {"Sec-Fetch-Site": "same-origin"}

    for transition in ("first_open", "reopen", "expiry", "restart"):
        if transition == "reopen":
            client.cookies.clear()
        elif transition == "expiry":
            clock.value += 301
        elif transition == "restart":
            app.state.browser_sessions = BrowserSessionStore(ttl_seconds=300, clock=clock)
        response = client.get("/api/auth/session", headers=headers)
        assert response.status_code == 200, transition
        assert response.json()["authenticated"] is True
        assert VALID_TOKEN not in response.text
        assert VALID_TOKEN not in response.headers.get("set-cookie", "")
        assert client.get("/protected").status_code == 200
        assert client.post("/protected").status_code == 403
        assert client.post("/protected", headers={
            "Origin": f"http://{host}",
            "X-CSRF-Token": response.json()["csrf_token"],
        }).status_code == 200


@pytest.mark.parametrize("case", [
    "remote_peer", "remote_host", "forwarded", "x_forwarded_for",
    "x_real_ip", "cross_site", "missing_fetch_site", "cross_origin",
    "disabled", "multi_user", "missing_token",
])
def test_automatic_browser_login_rejects_untrusted_or_disabled_requests(case):
    app = _session_app()
    app.state.app_config = {"api": {"auth_token": VALID_TOKEN}}
    headers = {"Sec-Fetch-Site": "same-origin"}
    host, peer = "localhost", "127.0.0.1"
    if case == "remote_peer":
        peer = "192.0.2.1"
    elif case == "remote_host":
        host = "learnflux.example"
    elif case in {"forwarded", "x_forwarded_for", "x_real_ip"}:
        headers[case.replace("_", "-")] = "127.0.0.1"
    elif case == "cross_site":
        headers["Sec-Fetch-Site"] = "cross-site"
    elif case == "missing_fetch_site":
        headers.clear()
    elif case == "cross_origin":
        headers["Origin"] = "https://other.example"
    elif case == "disabled":
        app.state.app_config["api"]["browser_local_auto_login"] = False
    elif case == "multi_user":
        app.state.user_manager.is_multi_user_mode = lambda: True
    elif case == "missing_token":
        app.state.app_config["api"].pop("auth_token")
    client = TestClient(app, base_url=f"http://{host}", client=(peer, 50000))
    response = client.get("/api/auth/session", headers=headers)
    assert response.status_code == (403 if case == "cross_origin" else 401)
    assert "set-cookie" not in response.headers


def test_security_headers_are_applied_without_enabling_cross_origin_access():
    app = FastAPI()
    configure_web_security(app, {})

    @app.get("/page")
    async def page():
        return {"ok": True}

    response = TestClient(app).get(
        "/page",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"
    assert "camera=()" in response.headers["permissions-policy"]
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "access-control-allow-origin" not in response.headers


def test_cors_requires_explicit_valid_http_origins():
    assert resolve_cors_origins({}) == []
    assert resolve_cors_origins(
        {"api": {"cors_allowed_origins": ["https://app.example", " http://localhost:3000 "]}}
    ) == ["https://app.example", "http://localhost:3000"]

    for invalid in ("*", "null", "https://app.example/path", "file:///tmp/app"):
        with pytest.raises(ValueError):
            resolve_cors_origins({"api": {"cors_allowed_origins": [invalid]}})


def test_explicit_cors_origin_never_returns_wildcard_with_credentials():
    app = FastAPI()
    configure_web_security(
        app,
        {"api": {"cors_allowed_origins": ["https://client.example"]}},
    )

    @app.post("/resource")
    async def resource():
        return {"ok": True}

    response = TestClient(app).options(
        "/resource",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://client.example"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-origin"] != "*"


def test_browser_login_sets_short_lived_httponly_session_without_echoing_secret():
    client = TestClient(_session_app())

    response = _login(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["user"] == {"user_id": "test-user", "name": "Test User"}
    assert payload["csrf_token"]
    assert VALID_TOKEN not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "learnflux_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "max-age=300" in cookie
    assert VALID_TOKEN not in cookie
    assert response.headers["cache-control"] == "no-store"

    protected = client.get("/protected")
    assert protected.status_code == 200
    assert protected.json() == {"user_id": "test-user"}


def test_https_browser_login_marks_cookie_secure():
    client = TestClient(_session_app(), base_url="https://testserver")
    response = _login(client, origin="https://testserver")

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_cookie_authenticated_writes_require_csrf_and_exact_same_origin():
    client = TestClient(_session_app())
    login = _login(client)
    csrf_token = login.json()["csrf_token"]

    missing_csrf = client.post(
        "/protected",
        headers={"Origin": SAME_ORIGIN},
    )
    assert missing_csrf.status_code == 403

    missing_origin = client.post(
        "/protected",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert missing_origin.status_code == 403

    cross_site = client.post(
        "/protected",
        headers={
            "Origin": "https://attacker.example",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert cross_site.status_code == 403

    accepted = client.post(
        "/protected",
        headers={"Origin": SAME_ORIGIN, "X-CSRF-Token": csrf_token},
    )
    assert accepted.status_code == 200


def test_standard_bearer_clients_remain_compatible_without_browser_csrf_headers():
    client = TestClient(_session_app())

    response = client.post(
        "/protected",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": "test-user"}


def test_expired_browser_session_has_deterministic_401_and_is_removed():
    clock = MutableClock()
    client = TestClient(_session_app(clock=clock))
    assert _login(client).status_code == 200

    clock.value += 301
    expired = client.get("/protected")
    missing_after_cleanup = client.get("/protected")

    assert expired.status_code == 401
    assert expired.json()["detail"] == "浏览器会话已过期"
    assert missing_after_cleanup.status_code == 401


def test_login_rejects_cross_site_origin_and_invalid_management_token():
    client = TestClient(_session_app())

    cross_site = _login(client, origin="https://attacker.example")
    invalid = client.post(
        "/api/auth/session",
        json={"management_token": "wrong-token"},
        headers={"Origin": SAME_ORIGIN},
    )

    assert cross_site.status_code == 403
    assert invalid.status_code == 401
    assert "set-cookie" not in invalid.headers
