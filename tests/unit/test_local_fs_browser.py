from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from video_transcript_api.api.routes import collections
from video_transcript_api.api.services.transcription import verify_token
from video_transcript_api.utils.local_fs_browser import browse_local_directory


def test_browse_local_directory_lists_subdirs_and_media_counts(tmp_path):
    course = tmp_path / "course"
    nested = course / "chapter-1"
    nested.mkdir(parents=True)
    (course / "001-intro.mp4").write_bytes(b"video")
    (course / "note.md").write_text("hello", encoding="utf-8")
    (nested / "keep.txt").write_text("x", encoding="utf-8")

    data = browse_local_directory(str(course))
    assert data["path"] == str(course.resolve())
    assert data["video_count"] == 1
    assert data["document_count"] == 1
    assert data["media_count"] == 2
    names = {entry["name"] for entry in data["entries"]}
    assert "chapter-1" in names
    assert all(entry["type"] == "dir" for entry in data["entries"])


def test_local_fs_browse_route_requires_auth_and_returns_data(tmp_path, monkeypatch):
    course = tmp_path / "lessons"
    course.mkdir()
    (course / "a.mp4").write_bytes(b"v")

    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "owner", "api_key": "t"}
    client = TestClient(app)

    response = client.get("/api/local-fs/browse", params={"path": str(course)})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["video_count"] == 1
    assert payload["path"].endswith("lessons")


def test_collections_page_uses_path_picker_not_browser_prompt():
    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    js = (project_root / "src/web/static/js/collections.js").read_text(encoding="utf-8")
    routes = (
        project_root / "src/video_transcript_api/api/routes/collections.py"
    ).read_text(encoding="utf-8")
    browser = (
        project_root / "src/video_transcript_api/utils/local_fs_browser.py"
    ).read_text(encoding="utf-8")

    assert 'id="local-path-picker-dialog"' in html
    assert 'id="browse-local-path"' in html
    assert "选择文件夹" in html
    assert "openLocalPathPicker" in js
    assert "pickFolderWithNativeDialog" in js
    assert "window.prompt" not in js
    assert "/api/local-fs/browse" in js
    assert "/api/local-fs/pick-folder" in js
    assert "pick_local_directory_native" in routes
    assert "choose folder" in browser
