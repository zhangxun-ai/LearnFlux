from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_settings_exchanges_management_token_for_shared_browser_session():
    app_js = (PROJECT_ROOT / "src/web/static/js/app.js").read_text(encoding="utf-8")
    settings_html = (PROJECT_ROOT / "src/web/static/settings.html").read_text(encoding="utf-8")

    assert '/static/js/auth-session.js' in settings_html
    assert "window.LearnFluxAuth.login(entered)" in settings_html
    assert "window.LearnFluxAuth.getTokenPlaceholder()" in settings_html
    assert "vta_encrypt_key_2024" not in settings_html
    assert "localStorage.setItem" not in settings_html
    assert "ENCRYPTION_KEY" not in app_js


def test_settings_concurrency_selects_follow_authenticated_server_limits():
    settings_html = (PROJECT_ROOT / "src/web/static/settings.html").read_text(
        encoding="utf-8"
    )

    assert "f.control === 'select'" in settings_html
    assert "function setConcurrencyOptions(limits)" in settings_html
    assert "setConcurrencyOptions(json.data.concurrency_limits || {})" in settings_html
    assert "lastServerGroups" in settings_html
    assert "并发设置已立即生效；其它设置重启后生效" in settings_html
