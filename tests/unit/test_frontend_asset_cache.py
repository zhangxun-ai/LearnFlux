"""Regression coverage for coherent frontend updates and offline shell caching."""

import importlib
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from video_transcript_api.api.assets import get_static_asset_version
from video_transcript_api.api.static_files import RevalidatingStaticFiles


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = ROOT / "src/web/static"


def test_asset_version_uses_content_and_includes_shared_and_nested_code(tmp_path):
    theme = tmp_path / "css/workbench-wildwood.css"
    runtime = tmp_path / "js/player/runtime.js"
    theme.parent.mkdir(parents=True)
    runtime.parent.mkdir(parents=True)
    theme.write_text("body { color: green; }")
    runtime.write_text("export const enabled = true;")
    initial = get_static_asset_version(tmp_path)
    stat = theme.stat()
    os.utime(theme, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert get_static_asset_version(tmp_path) == initial
    theme.write_text("body { color: brown; }")
    os.utime(theme, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed_theme = get_static_asset_version(tmp_path)
    assert changed_theme != initial
    runtime.write_text("export const enabled = false;")
    assert get_static_asset_version(tmp_path) != changed_theme


def test_navigation_generator_uses_the_runtime_digest():
    generator = runpy.run_path(str(ROOT / "scripts/sync_product_navigation.py"))
    assert generator["_static_asset_digest"]() == get_static_asset_version(STATIC_ROOT)


@pytest.mark.parametrize("filename", ["history.html", "css/app-shell.css", "js/app-shell.js"])
def test_static_documents_and_code_revalidate_including_304(tmp_path, filename):
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("current frontend")
    app = FastAPI()
    app.mount("/static", RevalidatingStaticFiles(directory=tmp_path))
    client = TestClient(app)
    first = client.get(f"/static/{filename}")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"
    conditional = client.get(
        f"/static/{filename}", headers={"If-None-Match": first.headers["etag"]}
    )
    assert conditional.status_code == 304
    assert conditional.headers["cache-control"] == first.headers["cache-control"]
    assert client.head(f"/static/{filename}").headers["cache-control"] == first.headers["cache-control"]


def test_every_rendered_workbench_uses_one_live_content_version(tmp_path, monkeypatch):
    from video_transcript_api.api import context

    for name in (
        "index.html", "collections.html", "settings.html", "reading.html",
        "review.html", "study.html", "visual-learning.html",
    ):
        (tmp_path / name).write_bytes((STATIC_ROOT / name).read_bytes())
    theme = tmp_path / "css/workbench-wildwood.css"
    theme.parent.mkdir()
    theme.write_text("body { color: green; }")
    monkeypatch.setattr(context, "get_static_dir", lambda: tmp_path)
    monkeypatch.setattr(context, "_templates", None)
    app = FastAPI()
    for name in ("views", "collections", "settings", "reading", "reviews", "visual_learning", "briefings"):
        module = importlib.import_module(f"video_transcript_api.api.routes.{name}")
        if hasattr(module, "static_dir"):
            monkeypatch.setattr(module, "static_dir", tmp_path)
        if hasattr(module, "get_static_dir"):
            monkeypatch.setattr(module, "get_static_dir", lambda: tmp_path)
        app.include_router(module.router)
    client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 1234))
    routes = (
        "/add_task_by_web", "/collections", "/settings", "/reading",
        "/review", "/study", "/visual-learning", "/briefings",
    )
    for content in ("body { color: green; }", "body { color: brown; }"):
        theme.write_text(content)
        expected = get_static_asset_version(tmp_path)
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200, route
            for asset in ("css/app-shell.css", "js/app-shell.js", "css/workbench-wildwood.css"):
                match = re.search(rf'/static/{re.escape(asset)}\?v=([^"\s]+)', response.text)
                assert match is not None, (route, asset)
                assert match.group(1) == expected, (route, asset)


def test_template_version_updates_without_recreating_environment(tmp_path, monkeypatch):
    from video_transcript_api.api import context

    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "version.html").write_text("{{ asset_ver }}")
    (tmp_path / "shell.css").write_text("green")
    monkeypatch.setattr(context, "get_template_dir", lambda: template_dir)
    monkeypatch.setattr(context, "get_static_dir", lambda: tmp_path)
    monkeypatch.setattr(context, "_templates", None)
    templates = context.get_templates()
    app = FastAPI()

    @app.get("/")
    async def render(request: Request):
        return templates.TemplateResponse(request=request, name="version.html")

    client = TestClient(app)
    before = client.get("/").text
    (tmp_path / "shell.css").write_text("brown")
    assert client.get("/").text != before
    assert client.get("/").text == get_static_asset_version(tmp_path)


def test_service_worker_cache_behaviors():
    node = shutil.which("node")
    assert node, "Node.js is required for service worker cache regression checks"
    result = subprocess.run(
        [node, "tests/frontend/service_worker_cache_behavior.cjs"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
