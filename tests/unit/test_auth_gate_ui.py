"""Shared first-use authentication UX contracts."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "src/web"
AUTH_SCRIPT = WEB_ROOT / "static/js/auth-session.js"
AUTH_STYLES = WEB_ROOT / "static/css/auth-gate.css"


def test_shared_auth_adapter_exposes_an_accessible_management_token_gate():
    source = AUTH_SCRIPT.read_text(encoding="utf-8")

    assert "async function requireSession(options)" in source
    assert "function renderAuthGate(container, options)" in source
    assert "function guard(action, options)" in source
    assert "createGateElement('dialog', 'lf-auth-gate')" in source
    assert "管理口令" in source
    assert "短期 HttpOnly 会话" in source
    assert "aria-live" in source
    assert "return_to=" in source
    assert "requireSession: requireSession" in source
    assert "renderAuthGate: renderAuthGate" in source
    assert "guard: guard" in source


def test_auth_gate_has_shared_responsive_focus_and_dark_theme_styles():
    assert AUTH_STYLES.exists()
    source = AUTH_STYLES.read_text(encoding="utf-8")

    for selector in (
        ".lf-auth-gate",
        ".lf-auth-gate-card",
        ".lf-auth-gate-input",
        ".lf-auth-gate-primary",
        ".lf-auth-required",
    ):
        assert selector in source
    assert ":focus-visible" in source
    assert "min-height: 44px" in source
    assert "@media (max-width: 560px)" in source
    assert '[data-theme="dark"]' in source


def test_auth_gate_asset_is_loaded_and_available_offline():
    auth_source = AUTH_SCRIPT.read_text(encoding="utf-8")
    service_worker = (WEB_ROOT / "static/service-worker.js").read_text(encoding="utf-8")

    assert "/static/css/auth-gate.css" in auth_source
    assert "/static/css/auth-gate.css" in service_worker


def test_core_workspaces_use_the_shared_auth_gate_instead_of_legacy_token_copy():
    consumers = (
        WEB_ROOT / "static/js/app.js",
        WEB_ROOT / "static/js/collections.js",
        WEB_ROOT / "static/js/reading.js",
        WEB_ROOT / "static/js/review.js",
        WEB_ROOT / "static/js/study.js",
        WEB_ROOT / "static/js/visual-learning-workbench.js",
        WEB_ROOT / "templates/flywheel.html",
        WEB_ROOT / "static/history.html",
    )

    for path in consumers:
        source = path.read_text(encoding="utf-8")
        assert "LearnFluxAuth.requireSession" in source, path.relative_to(PROJECT_ROOT)

    home = (WEB_ROOT / "static/js/app.js").read_text(encoding="utf-8")
    transcript = (WEB_ROOT / "templates/transcript.html").read_text(encoding="utf-8")
    assert "请在高级设置中填写" not in home
    assert "回首页高级设置" not in transcript
