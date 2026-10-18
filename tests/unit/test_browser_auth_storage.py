"""Browser-token migration and Web Storage regression contracts."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "src/web"
AUTH_JS = WEB_ROOT / "static/js/auth-session.js"

SENSITIVE_STORAGE_KEYS = (
    "vta_bearer_token",
    "vta_settings_token",
    "vta_api_key_persist",
    "vta_api_key",
    "api_key",
)

TOKEN_CONSUMER_PAGES = (
    WEB_ROOT / "static/index.html",
    WEB_ROOT / "static/collections.html",
    WEB_ROOT / "static/focus-studio.html",
    WEB_ROOT / "static/history.html",
    WEB_ROOT / "static/reading.html",
    WEB_ROOT / "static/review.html",
    WEB_ROOT / "static/settings.html",
    WEB_ROOT / "static/study.html",
    WEB_ROOT / "static/visual-learning.html",
    WEB_ROOT / "templates/base.html",
    WEB_ROOT / "templates/flywheel.html",
)


def _run_node(script: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser-auth migration tests")
    return subprocess.run(
        [node, "-e", script, str(AUTH_JS)],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("scenario", [
    "stale_session", "initially_missing", "preflight", "offline", "concurrent",
    "request_body", "explicit_bearer", "remote", "always_401", "http500",
    "disabled", "stream",
])
def test_local_page_reconnects_after_restart_without_reentering_token(scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser-auth tests")
    result = subprocess.run(
        [node, str(PROJECT_ROOT / "tests/frontend/local_auth_reconnect.cjs"), scenario],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_auth_adapter_migrates_legacy_token_once_and_clears_sensitive_storage():
    script = r"""
const assert = require('node:assert/strict');
const path = process.argv[1];
const encryptionKey = 'vta_encrypt_key_2024';
const managementToken = 'legacy-test-token';
const encoded = Buffer.from(managementToken + encryptionKey, 'utf8')
  .toString('base64').split('').reverse().join('');

class Storage {
  constructor(values = {}) { this.values = new Map(Object.entries(values)); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

globalThis.window = globalThis;
globalThis.location = new URL('https://learnflux.test/settings');
globalThis.localStorage = new Storage({vta_bearer_token: encoded});
globalThis.sessionStorage = new Storage({vta_api_key: managementToken});
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.dispatchEvent = () => true;
globalThis.XMLHttpRequest = undefined;
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({url: String(url), init});
  if (String(url) === '/api/auth/session' && (!init.method || init.method === 'GET')) {
    return new Response(JSON.stringify({detail: 'not authenticated'}), {
      status: 401,
      headers: {'Content-Type': 'application/json'},
    });
  }
  const body = JSON.parse(init.body);
  assert.equal(body.management_token, managementToken);
  return new Response(JSON.stringify({
    authenticated: true,
    csrf_token: 'csrf-test-value',
    user: {user_id: 'legacy-user', name: 'Legacy User'},
  }), {status: 200, headers: {'Content-Type': 'application/json'}});
};

require(path);
(async () => {
  const state = await globalThis.LearnFluxAuth.ready;
  assert.equal(state.authenticated, true);
  assert.equal(globalThis.LearnFluxAuth.getTokenPlaceholder(), '__learnflux_browser_session__');
  assert.equal(calls.length, 2);
  for (const key of ['vta_bearer_token', 'vta_settings_token', 'vta_api_key_persist', 'vta_api_key', 'api_key']) {
    assert.equal(localStorage.getItem(key), null);
    assert.equal(sessionStorage.getItem(key), null);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    result = _run_node(script)

    assert result.returncode == 0, result.stderr


def test_auth_adapter_does_not_expose_session_placeholder_before_probe_completes():
    script = r"""
const assert = require('node:assert/strict');
const path = process.argv[1];
globalThis.window = globalThis;
globalThis.location = new URL('https://learnflux.test/reading');
globalThis.localStorage = {getItem: () => null, removeItem: () => {}};
globalThis.sessionStorage = {getItem: () => null, removeItem: () => {}};
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.dispatchEvent = () => true;
globalThis.XMLHttpRequest = undefined;
let finishProbe;
globalThis.fetch = () => new Promise((resolve) => { finishProbe = resolve; });

require(path);
assert.equal(globalThis.LearnFluxAuth.getTokenPlaceholder(), '');
finishProbe(new Response(JSON.stringify({detail: 'not authenticated'}), {
  status: 401,
  headers: {'Content-Type': 'application/json'},
}));
(async () => {
  const state = await globalThis.LearnFluxAuth.ready;
  assert.equal(state.authenticated, false);
  assert.equal(globalThis.LearnFluxAuth.getTokenPlaceholder(), '');
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    result = _run_node(script)

    assert result.returncode == 0, result.stderr


def test_auth_adapter_distinguishes_invalid_credentials_expiry_csrf_and_network_errors():
    script = r"""
const assert = require('node:assert/strict');
const path = process.argv[1];
globalThis.window = globalThis;
globalThis.location = new URL('https://learnflux.test/reading');
globalThis.localStorage = {getItem: () => null, removeItem: () => {}};
globalThis.sessionStorage = {getItem: () => null, removeItem: () => {}};
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.dispatchEvent = () => true;
globalThis.XMLHttpRequest = undefined;
globalThis.fetch = async () => new Response(JSON.stringify({detail: 'not authenticated'}), {
  status: 401,
  headers: {'Content-Type': 'application/json'},
});

require(path);
(async () => {
  await globalThis.LearnFluxAuth.ready;
  const message = globalThis.LearnFluxAuth.authErrorMessage;
  assert.equal(message({status: 401, message: '管理口令无效'}), '管理口令不正确，请重新输入。');
  assert.equal(message({status: 401, message: '浏览器会话已过期'}), '浏览器会话已过期，请重新连接。');
  assert.equal(message({status: 403, message: 'CSRF 校验失败'}), '当前页面的安全校验已失效，请刷新后重试。');
  assert.equal(message(new TypeError('Failed to fetch')), '无法连接 LearnFlux，请检查网络后重试。');
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    result = _run_node(script)

    assert result.returncode == 0, result.stderr


def test_auth_adapter_strips_browser_sentinel_and_adds_csrf_to_same_origin_writes():
    script = r"""
const assert = require('node:assert/strict');
const path = process.argv[1];
globalThis.window = globalThis;
globalThis.location = new URL('https://learnflux.test/settings');
globalThis.localStorage = {getItem: () => null, removeItem: () => {}};
globalThis.sessionStorage = {getItem: () => null, removeItem: () => {}};
globalThis.CustomEvent = class CustomEvent { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
globalThis.dispatchEvent = () => true;
globalThis.XMLHttpRequest = undefined;
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({url: String(url), init});
  if (String(url) === '/api/auth/session') {
    return new Response(JSON.stringify({
      authenticated: true,
      csrf_token: 'csrf-test-value',
      user: {user_id: 'user-1', name: 'User 1'},
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
  }
  return new Response('{}', {status: 200, headers: {'Content-Type': 'application/json'}});
};

require(path);
(async () => {
  // A page script may issue its first write before the session probe resolves.
  await globalThis.fetch('/api/write', {
    method: 'POST',
    headers: {Authorization: 'Bearer __learnflux_browser_session__'},
  });
  await globalThis.LearnFluxAuth.ready;
  const writeCall = calls.find((call) => call.url === '/api/write');
  const headers = new Headers(writeCall.init.headers);
  assert.equal(headers.has('Authorization'), false);
  assert.equal(headers.get('X-CSRF-Token'), 'csrf-test-value');
  assert.equal(writeCall.init.credentials, 'same-origin');

  await globalThis.fetch('/api/cli-compatible', {
    method: 'POST',
    headers: {Authorization: 'Bearer explicit-api-token'},
  });
  const bearerCall = calls.find((call) => call.url === '/api/cli-compatible');
  const bearerHeaders = new Headers(bearerCall.init.headers);
  assert.equal(bearerHeaders.get('Authorization'), 'Bearer explicit-api-token');
  assert.equal(bearerHeaders.has('X-CSRF-Token'), false);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    result = _run_node(script)

    assert result.returncode == 0, result.stderr


def test_frontend_never_writes_management_tokens_to_web_storage():
    source_files = [
        *WEB_ROOT.glob("static/**/*.js"),
        *WEB_ROOT.glob("static/**/*.html"),
        *WEB_ROOT.glob("templates/**/*.html"),
    ]
    assignment = re.compile(
        r"(?:localStorage|sessionStorage)\.setItem\(\s*['\"]"
        + "(?:" + "|".join(re.escape(key) for key in SENSITIVE_STORAGE_KEYS) + ")"
        + r"['\"]"
    )

    offenders = []
    for path in source_files:
        source = path.read_text(encoding="utf-8")
        if assignment.search(source):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_legacy_reversible_token_codec_is_isolated_to_one_time_migration_adapter():
    offenders = []
    for path in [
        *WEB_ROOT.glob("static/**/*.js"),
        *WEB_ROOT.glob("static/**/*.html"),
        *WEB_ROOT.glob("templates/**/*.html"),
    ]:
        if path == AUTH_JS:
            continue
        if "vta_encrypt_key_2024" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_every_browser_token_consumer_loads_shared_auth_adapter_first():
    for path in TOKEN_CONSUMER_PAGES:
        source = path.read_text(encoding="utf-8")
        auth_position = source.find("/static/js/auth-session.js")
        assert auth_position >= 0, f"missing auth adapter: {path.relative_to(PROJECT_ROOT)}"

        token_script_positions = [
            position
            for marker in (
                "/static/js/app.js",
                "/static/js/collections.js",
                "/static/js/focus-journal.js",
                "/static/js/reading.js",
                "/static/js/review.js",
                "/static/js/study.js",
                "/static/js/trend-radar.js",
                "/static/js/visual-learning-workbench.js",
            )
            if (position := source.find(marker)) >= 0
        ]
        if token_script_positions:
            assert auth_position < min(token_script_positions)


def test_settings_uses_session_login_and_does_not_bridge_token_storage():
    settings = (WEB_ROOT / "static/settings.html").read_text(encoding="utf-8")

    assert "LearnFluxAuth.login" in settings
    assert "localStorage.setItem(TOKEN_KEY" not in settings
    assert "localStorage.setItem(WORKBENCH_TOKEN_KEY" not in settings
    assert "encryptToken" not in settings
