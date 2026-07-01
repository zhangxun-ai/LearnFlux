from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_study_page_renders_static_shell(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import views

    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "study.html").write_text(
        "<html><script>window.STUDY_VIEW_TOKEN='__VIEW_TOKEN__';"
        "window.STUDY_ASSET_VERSION='__ASSET_VERSION__';</script></html>",
        encoding="utf-8",
    )
    (static_dir / "css").mkdir()
    (static_dir / "css" / "study.css").write_text("body{}", encoding="utf-8")
    (static_dir / "js").mkdir()
    (static_dir / "js" / "study.js").write_text("console.log('study')", encoding="utf-8")

    cache_manager = type(
        "FakeCacheManager",
        (),
        {"get_view_data_by_token": lambda self, token: {"view_token": token}},
    )()
    monkeypatch.setattr(views, "static_dir", static_dir)
    monkeypatch.setattr(views, "cache_manager", cache_manager)

    app = FastAPI()
    app.include_router(views.router)
    client = TestClient(app)

    response = client.get("/study/view-123")

    assert response.status_code == 200
    assert "view-123" in response.text
    assert "__VIEW_TOKEN__" not in response.text
    assert "__ASSET_VERSION__" not in response.text


def test_study_page_returns_404_for_unknown_token(monkeypatch, tmp_path):
    from video_transcript_api.api.routes import views

    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "study.html").write_text("<html></html>", encoding="utf-8")

    cache_manager = type(
        "FakeCacheManager",
        (),
        {"get_view_data_by_token": lambda self, token: None},
    )()
    monkeypatch.setattr(views, "static_dir", static_dir)
    monkeypatch.setattr(views, "cache_manager", cache_manager)

    app = FastAPI()
    app.include_router(views.router)
    client = TestClient(app)

    response = client.get("/study/missing")

    assert response.status_code == 404
