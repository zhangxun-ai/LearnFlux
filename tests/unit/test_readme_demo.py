"""Keep documentation captures isolated from user data and real processing."""

import importlib.util
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("readme_demo", ROOT / "scripts/readme_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture
def demo_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo.DemoHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/transcribe"), ("POST", "/api/settings"),
    ("POST", "/api/image-diagrams/generate"), ("DELETE", "/api/reading/documents/demo-book-0"),
])
def test_demo_cannot_process_or_delete(demo_server, method, path):
    with pytest.raises(HTTPError) as error:
        urlopen(Request(demo_server + path, data=b"{}", method=method), timeout=3)
    assert error.value.code == 403


@pytest.mark.parametrize("path", [
    "/static/%2e%2e/%2e%2e/%2e%2e/config/config.jsonc", "/api/settings",
    "/api/task/private-user-task", "/view/private-token",
])
def test_demo_does_not_fall_back_to_private_files_or_backend(demo_server, path):
    with pytest.raises(HTTPError) as error:
        urlopen(demo_server + path, timeout=3)
    assert error.value.code == 404


def test_demo_renders_current_pages_and_authored_history(demo_server):
    with urlopen(demo_server + "/view/demo-note-0", timeout=3) as response:
        html = response.read().decode()
    assert demo.TITLE in html
    assert "/static/js/app-shell.js?v=" in html
    with urlopen(demo_server + "/api/audit/history", timeout=3) as response:
        rows = json.load(response)["data"]["items"]
    assert len(rows) == 6
    assert all(row["view_token"].startswith("demo-") and row["request_time"].endswith("+00:00") for row in rows)
    filters = demo.api_payload("/api/audit/history/filter-options", {})["data"]
    assert sum(item["count"] for item in filters["platform_counts"]) == len(rows)


def test_demo_media_range_supports_real_seeking(demo_server, tmp_path, monkeypatch):
    media = tmp_path / "output/playwright/readme-20261103-cases/demo-video.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"0123456789")
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    request = Request(demo_server + "/demo-video.mp4", headers={"Range": "bytes=3-5"})
    with urlopen(request, timeout=3) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 3-5/10"
        assert response.read() == b"345"
