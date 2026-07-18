import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_settings_load_syncs_management_token_to_workbench_bearer_storage():
    app_js = (PROJECT_ROOT / "src/web/static/js/app.js").read_text(encoding="utf-8")
    settings_html = (PROJECT_ROOT / "src/web/static/settings.html").read_text(encoding="utf-8")

    token_key_match = re.search(r"BEARER_TOKEN:\s*'([^']+)'", app_js)
    encryption_key_match = re.search(r"ENCRYPTION_KEY:\s*'([^']+)'", app_js)

    assert token_key_match
    assert encryption_key_match

    token_key = token_key_match.group(1)
    encryption_key = encryption_key_match.group(1)

    assert f"var WORKBENCH_TOKEN_KEY = '{token_key}';" in settings_html
    assert f"var ENCRYPTION_KEY = '{encryption_key}';" in settings_html
    assert "localStorage.setItem(WORKBENCH_TOKEN_KEY, encryptToken(getToken()));" in settings_html
