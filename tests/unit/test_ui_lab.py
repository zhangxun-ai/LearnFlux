import importlib.util
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTE_FILE = REPO_ROOT / "src" / "video_transcript_api" / "api" / "routes" / "ui_lab.py"
TEMPLATE = REPO_ROOT / "src" / "web" / "templates" / "ui_lab.html"
STYLESHEET = REPO_ROOT / "src" / "web" / "static" / "css" / "ui-lab.css"
SCRIPT = REPO_ROOT / "src" / "web" / "static" / "js" / "ui-lab.js"
REVIEW_TEMPLATE = REPO_ROOT / "src" / "web" / "templates" / "review_ui_lab.html"
REVIEW_STYLESHEET = (
    REPO_ROOT / "src" / "web" / "static" / "css" / "review-ui-lab.css"
)
REVIEW_SCRIPT = REPO_ROOT / "src" / "web" / "static" / "js" / "review-ui-lab.js"
STATIC_ROOT = REPO_ROOT / "src" / "web" / "static"

_ROUTE_SPEC = importlib.util.spec_from_file_location("learnflux_ui_lab_route", ROUTE_FILE)
assert _ROUTE_SPEC and _ROUTE_SPEC.loader
ui_lab = importlib.util.module_from_spec(_ROUTE_SPEC)
_ROUTE_SPEC.loader.exec_module(ui_lab)


def _client(base_url: str) -> TestClient:
    app = FastAPI()
    app.include_router(ui_lab.router)
    return TestClient(app, base_url=base_url)


def test_ui_lab_is_available_only_for_loopback_hosts():
    with _client("http://localhost") as client:
        response = client.get("/ui-lab")
        assert response.status_code == 200
        assert "LearnFlux UI Lab" in response.text

    with _client("http://127.0.0.1") as client:
        assert client.get("/ui-lab").status_code == 200

    with _client("https://learnflux.example") as client:
        response = client.get("/ui-lab")
        assert response.status_code == 404


def test_ui_lab_requires_explicit_application_enablement():
    assert ui_lab.ui_lab_enabled({"api": {"ui_lab_enabled": True}})
    assert not ui_lab.ui_lab_enabled({"api": {}})
    assert not ui_lab.ui_lab_enabled({"api": {"ui_lab_enabled": False}})
    assert not ui_lab.ui_lab_enabled({})


def test_ui_lab_response_blocks_data_writes_and_indexing():
    with _client("http://localhost") as client:
        response = client.get("/ui-lab")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    policy = response.headers["content-security-policy"]
    assert "connect-src 'none'" in policy
    assert "media-src 'none'" in policy
    assert "form-action 'none'" in policy
    assert "object-src 'none'" in policy


def test_ui_lab_assets_are_isolated_and_mock_only():
    assert TEMPLATE.exists()
    assert STYLESHEET.exists()
    assert SCRIPT.exists()
    assert not (STATIC_ROOT / "ui-lab.html").exists()

    html = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    css = STYLESHEET.read_text(encoding="utf-8")

    assert html.count('id="lab-workspace"') == 1
    assert html.count("data-variant-choice=") == 3
    assert "/static/css/ui-lab.css" in html
    assert "/static/js/ui-lab.js" in html
    assert "<form" not in html
    assert 'href="/study' not in html
    assert 'href="/view' not in html
    assert 'href="/api/' not in html

    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "localStorage",
        "sessionStorage",
        "WebSocket",
        "EventSource",
        "sendBeacon",
    ):
        assert forbidden not in script

    assert "const LAB_DATA = Object.freeze" in script
    assert "workspace.cloneNode(true)" in script
    assert '.lab-variant-surface[data-variant="a"]' in css
    assert '.lab-variant-surface[data-variant="b"]' in css
    assert '.lab-variant-surface[data-variant="c"]' in css
    assert "app-shell.css" not in html
    assert "app-shell.js" not in html


def test_ui_lab_uses_one_shared_content_model_for_all_variants():
    assertions = r"""
require('./src/web/static/js/ui-lab.js');
const api = globalThis.LearnFluxUiLab;
if (!Object.isFrozen(api.LAB_DATA)) process.exit(1);
if (!Object.isFrozen(api.LAB_DATA.transcript)) process.exit(1);
if (Object.keys(api.VARIANTS).join(',') !== 'a,b,c') process.exit(1);
if (api.LAB_DATA.transcript.length !== 8) process.exit(1);
if (api.normalizeVariant('B') !== 'b') process.exit(1);
if (api.normalizeVariant('unknown') !== 'a') process.exit(1);
const options = api.readInitialOptions('?variant=c&preview=mobile&state=error&embed=1');
if (JSON.stringify(options) !== JSON.stringify({
  variant: 'c', preview: 'mobile', contentState: 'error', embed: true,
})) process.exit(1);
for (const variant of Object.values(api.VARIANTS)) {
  if ('title' in variant || 'transcript' in variant || 'question' in variant) process.exit(1);
}
"""
    completed = subprocess.run(
        ["node", "-e", assertions],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_ui_lab_is_not_linked_from_production_entry_pages():
    production_entries = (
        STATIC_ROOT / "index.html",
        STATIC_ROOT / "study.html",
        STATIC_ROOT / "collections.html",
        STATIC_ROOT / "js" / "app-shell.js",
        REPO_ROOT / "src" / "web" / "product-navigation.json",
    )
    for entry in production_entries:
        assert "/ui-lab" not in entry.read_text(encoding="utf-8")


def test_ui_lab_route_is_not_exposed_in_openapi():
    app = FastAPI()
    app.include_router(ui_lab.router)
    assert "/ui-lab" not in app.openapi()["paths"]


def test_review_ui_lab_is_available_only_for_loopback_hosts():
    with _client("http://localhost") as client:
        response = client.get("/ui-lab/review")
        assert response.status_code == 200
        assert "LearnFlux UI Lab · 复盘模块" in response.text

    with _client("http://127.0.0.1") as client:
        assert client.get("/ui-lab/review").status_code == 200

    with _client("https://learnflux.example") as client:
        response = client.get("/ui-lab/review")
        assert response.status_code == 404


def test_review_ui_lab_response_blocks_data_writes_and_indexing():
    with _client("http://localhost") as client:
        response = client.get("/ui-lab/review")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    policy = response.headers["content-security-policy"]
    assert "connect-src 'none'" in policy
    assert "media-src 'none'" in policy
    assert "form-action 'none'" in policy
    assert "object-src 'none'" in policy


def test_review_ui_lab_assets_are_isolated_and_mock_only():
    assert REVIEW_TEMPLATE.exists()
    assert REVIEW_STYLESHEET.exists()
    assert REVIEW_SCRIPT.exists()

    html = REVIEW_TEMPLATE.read_text(encoding="utf-8")
    script = REVIEW_SCRIPT.read_text(encoding="utf-8")
    css = REVIEW_STYLESHEET.read_text(encoding="utf-8")

    assert html.count('id="review-lab-workspace"') == 1
    assert html.count("data-variant-choice=") == 3
    assert html.count('option value="') == 5
    assert "/static/css/review-ui-lab.css" in html
    assert "/static/js/review-ui-lab.js" in html
    assert "app-shell.css" not in html
    assert "app-shell.js" not in html
    assert "review.css" not in html
    assert "review.js" not in html
    assert "<form" not in html
    assert 'href="/review' not in html
    assert 'href="/api/' not in html

    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "localStorage",
        "sessionStorage",
        "WebSocket",
        "EventSource",
        "sendBeacon",
    ):
        assert forbidden not in script

    assert "const LAB_DATA = deepFreeze" in script
    assert "workspace.cloneNode(true)" in script
    assert '.review-lab-workspace[data-variant="a"]' in css
    assert '.review-lab-workspace[data-variant="b"]' in css
    assert '.review-lab-workspace[data-variant="c"]' in css
    assert "/static/icon/learnflux-icon-256.png" in html
    assert 'data-inspect="false"' in html
    assert '.review-ui-lab[data-inspect="true"] .review-lab-toolbar' in css
    assert "--mock-bg: #f6f8fb" in css
    assert "--mock-accent: #2868d8" in css

    for removed_review_copy in (
        "方案 A · 推荐起点",
        "用户感受",
        "关键取舍",
        "任务顺序",
        "页面密度",
        "主辅比例",
        "所有输入、保存、AI 和同步均为本页内存模拟",
    ):
        assert removed_review_copy not in html


def test_review_ui_lab_uses_one_frozen_content_model_for_all_variants():
    assertions = r"""
require('./src/web/static/js/review-ui-lab.js');
const api = globalThis.LearnFluxReviewUiLab;
if (!Object.isFrozen(api.LAB_DATA)) process.exit(1);
if (!Object.isFrozen(api.LAB_DATA.daily.events)) process.exit(1);
if (Object.keys(api.VARIANTS).join(',') !== 'a,b,c') process.exit(1);
if (Object.keys(api.VIEWS).join(',') !== 'daily,weekly,monthly,annual,insights') process.exit(1);
if (api.LAB_DATA.daily.events.length !== 2) process.exit(1);
if (api.LAB_DATA.annual.months.length !== 12) process.exit(1);
if (api.LAB_DATA.insights.items.length !== 2) process.exit(1);
if (api.normalizeVariant('B') !== 'b') process.exit(1);
if (api.normalizeVariant('unknown') !== 'a') process.exit(1);
if (api.normalizeView('annual') !== 'annual') process.exit(1);
if (api.normalizeView('unknown') !== 'daily') process.exit(1);
const options = api.readInitialOptions('?variant=c&view=insights&preview=mobile&state=empty&compare=1');
if (JSON.stringify(options) !== JSON.stringify({
  variant: 'c', view: 'insights', preview: 'mobile', contentState: 'empty', compare: true, inspect: true,
})) process.exit(1);
const cleanOptions = api.readInitialOptions('?variant=a&view=daily');
if (cleanOptions.inspect !== false || cleanOptions.compare !== false) process.exit(1);
const inspectOptions = api.readInitialOptions('?variant=b&view=weekly&inspect=1');
if (inspectOptions.inspect !== true || inspectOptions.compare !== false) process.exit(1);
for (const variant of Object.values(api.VARIANTS)) {
  if ('daily' in variant || 'weekly' in variant || 'annual' in variant) process.exit(1);
}
"""
    completed = subprocess.run(
        ["node", "-e", assertions],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_daily_review_lab_matches_the_two_step_source_template():
    script = REVIEW_SCRIPT.read_text(encoding="utf-8")

    assertions = r"""
require('./src/web/static/js/review-ui-lab.js');
const daily = globalThis.LearnFluxReviewUiLab.LAB_DATA.daily.events[0];
const expected = 'id,event,thoughtFeeling,pastAction,pastResult,reframe,nextAction,futureResult';
if (Object.keys(daily).join(',') !== expected) process.exit(1);
"""
    completed = subprocess.run(
        ["node", "-e", assertions],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    for required_copy in (
        "什么事件让你内心有所触动？",
        "事件发生时，我在想什么、感受什么？",
        "当时我采取了什么行动？",
        "这个行动带来了什么结果？",
        "回顾事件和左侧记录后，我重新注意到了什么？",
        "从现在开始，我可以采取什么具体行动？",
        "这些行动可能会带来怎样的结果？",
    ):
        assert required_copy in script

    for removed_copy in (
        "带走行动",
        "共 3 步",
        "data-daily-step",
        "data-daily-title",
    ):
        assert removed_copy not in script


def test_review_ui_lab_is_not_linked_from_production_review_files():
    production_review_files = (
        STATIC_ROOT / "review.html",
        STATIC_ROOT / "css" / "review.css",
        STATIC_ROOT / "js" / "review.js",
    )
    for path in production_review_files:
        assert "/ui-lab/review" not in path.read_text(encoding="utf-8")


def test_review_ui_lab_route_is_not_exposed_in_openapi():
    app = FastAPI()
    app.include_router(ui_lab.router)
    assert "/ui-lab/review" not in app.openapi()["paths"]
