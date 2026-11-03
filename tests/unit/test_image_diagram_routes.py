"""Authenticated route contracts for manual generation and private image files."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock
import struct
import zlib

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from video_transcript_api.image_diagrams.artifacts import ImageDiagramArtifacts
from video_transcript_api.image_diagrams.config import ImageDiagramSettings
from video_transcript_api.image_diagrams.repository import ImageDiagramRepository
from video_transcript_api.image_diagrams.service import ImageDiagramService
from video_transcript_api.image_diagrams.source import snapshot_session


def png_bytes():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * 2) * 2)) + chunk(b"IEND", b""))


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import image_diagrams

    async def verify():
        return {"user_id": "owner-1"}

    source = snapshot_session({"metadata": {"title": "Private source"}, "transcript": {
        "lines": [{"id": "line-1", "text": "Readable source body", "start_seconds": 1}]}})
    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    (ref_dir / "warm-guide.png").write_bytes(png_bytes())
    service = ImageDiagramService(
        repository=ImageDiagramRepository(tmp_path / "jobs.db"),
        settings=ImageDiagramSettings(enabled=True, data_dir=tmp_path / "private-images"),
        client=MagicMock(), source_loader=lambda _: source,
        authorize=lambda *_: None, reference_dir=ref_dir,
    )
    service.start = MagicMock()
    monkeypatch.setattr(image_diagrams, "get_image_diagram_service", lambda: service)
    app = FastAPI()
    app.include_router(image_diagrams.router)
    app.dependency_overrides[image_diagrams.verify_token] = verify
    return SimpleNamespace(client=TestClient(app), service=service, app=app, module=image_diagrams)


def manual_request(**overrides):
    return {"request_id": "manual-request-123456", **overrides}


def test_read_state_does_not_start_workers_or_paid_calls(endpoint):
    result = endpoint.client.get("/api/image-diagrams/study/source-1")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["data"]["versions"] == []
    endpoint.service.start.assert_not_called()
    endpoint.service.client.plan.assert_not_called()
    endpoint.service.client.generate.assert_not_called()


def test_generate_valid_manual_request_returns_queued_and_deduplicates(endpoint):
    first = endpoint.client.post("/api/image-diagrams/study/source-1/generate", json=manual_request())
    second = endpoint.client.post("/api/image-diagrams/study/source-1/generate", json=manual_request())
    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert first.json()["data"]["status"] == "queued"
    endpoint.service.client.generate.assert_not_called()
    assert endpoint.service.start.call_count == 2


@pytest.mark.parametrize("payload", [
    {}, {"request_id": "short"}, manual_request(scope="section"),
    manual_request(section_id="section-1"), manual_request(scope="section", section_id="../../../private"),
    manual_request(style="nonexistent"), manual_request(instructions="x" * 2001),
    manual_request(revision_of="not-a-job"), manual_request(unrecognized_option=True),
])
def test_invalid_requests_are_rejected_without_creating_paid_work(endpoint, payload):
    result = endpoint.client.post("/api/image-diagrams/study/source-1/generate", json=payload)
    assert result.status_code == 422
    assert endpoint.service.repository.list_for_source("owner-1", "source-1") == []
    endpoint.service.start.assert_not_called()
    endpoint.service.client.generate.assert_not_called()


def test_request_id_conflict_and_daily_quota_have_explicit_http_status(endpoint):
    first = endpoint.client.post("/api/image-diagrams/study/source-1/generate", json=manual_request())
    assert first.status_code == 202
    changed = endpoint.client.post("/api/image-diagrams/study/source-1/generate",
                                   json=manual_request(instructions="Changed after submission"))
    assert changed.status_code == 409
    endpoint.service.settings = replace(endpoint.service.settings, max_daily_generations=1)
    capped = endpoint.client.post("/api/image-diagrams/study/source-2/generate",
                                  json=manual_request(request_id="second-request-123456"))
    assert capped.status_code == 429


def test_all_routes_require_authentication_before_resolving_services(endpoint, monkeypatch):
    async def deny():
        raise HTTPException(status_code=401, detail="Authentication required")

    endpoint.app.dependency_overrides[endpoint.module.verify_token] = deny
    monkeypatch.setattr(endpoint.module, "get_image_diagram_service",
                        lambda: pytest.fail("service resolved before authentication"))
    paths = [
        ("get", "/api/image-diagrams/study/source-1"),
        ("post", "/api/image-diagrams/study/source-1/generate"),
        ("get", "/api/image-diagrams/jobs/" + "a" * 32),
        ("get", "/api/image-diagrams/jobs/" + "a" * 32 + "/image"),
    ]
    for method, path in paths:
        result = getattr(endpoint.client, method)(path, **({"json": manual_request()} if method == "post" else {}))
        assert result.status_code == 401


def test_unauthorized_state_cannot_load_cached_private_source(endpoint, monkeypatch):
    task = {"task_id": "task-1", "owner_user_id": "different-owner", "status": "completed"}
    monkeypatch.setattr(endpoint.module, "get_cache_manager",
                        lambda: SimpleNamespace(get_task_by_view_token=lambda _: task))
    monkeypatch.setattr(endpoint.module, "get_user_manager",
                        lambda: SimpleNamespace(get_user_by_id=lambda _: {"enabled": True}))
    endpoint.service.authorize = endpoint.module.require_source_access
    endpoint.service.source_loader = lambda _: pytest.fail("private source loaded before authorization")
    assert endpoint.client.get("/api/image-diagrams/study/source-1").status_code == 404
    assert endpoint.client.post("/api/image-diagrams/study/source-1/generate", json=manual_request()).status_code == 404


def test_foreign_job_identity_is_rejected_before_loading_private_snapshot(endpoint, monkeypatch):
    queued = endpoint.service.prepare("source-2", "owner-2", {
        "scope": "overview", "section_id": None, "style": "warm-guide", "instructions": "",
        "request_id": "foreign-request-123456", "revision_of": None, "regenerate": False,
    })
    monkeypatch.setattr(endpoint.service.repository, "get",
                        lambda _: pytest.fail("foreign snapshot loaded before ownership check"))
    assert endpoint.client.get(f"/api/image-diagrams/jobs/{queued['id']}").status_code == 404
    assert endpoint.client.get(f"/api/image-diagrams/jobs/{queued['id']}/image").status_code == 404


def test_private_download_requires_current_access_and_sets_private_headers(endpoint, monkeypatch):
    job = endpoint.service.prepare("source-1", "owner-1", {
        "scope": "overview", "section_id": None, "style": "warm-guide", "instructions": "",
        "request_id": "download-request-123456", "revision_of": None, "regenerate": False,
    })
    claim = endpoint.service.repository.claim_next()
    key = endpoint.service.artifacts.save_image(job["id"], png_bytes())
    endpoint.service.repository.update(job["id"], claim["generation_token"],
                                       status="succeeded", stage="completed", image_key=key)
    path = f"/api/image-diagrams/jobs/{job['id']}/image"
    inline = endpoint.client.get(path)
    assert inline.status_code == 200
    assert inline.content == png_bytes()
    assert inline.headers["content-type"] == "image/png"
    assert inline.headers["cache-control"] == "private, no-store"
    assert inline.headers["x-content-type-options"] == "nosniff"
    attachment = endpoint.client.get(path + "?download=1")
    assert attachment.status_code == 200
    assert attachment.headers["content-disposition"].startswith("attachment;")

    def revoke(*_args):
        raise HTTPException(status_code=403, detail="Access revoked")

    endpoint.service.authorize = revoke
    monkeypatch.setattr(endpoint.service.repository, "get",
                        lambda _: pytest.fail("snapshot loaded after source access revocation"))
    assert endpoint.client.get(path).status_code == 403


def test_disabled_without_openai_key_still_returns_state_200(endpoint):
    endpoint.service.settings = ImageDiagramSettings.from_config({}, environ={})
    endpoint.service.client = None
    result = endpoint.client.get("/api/image-diagrams/study/source-1")
    assert result.status_code == 200
    assert result.json()["data"]["enabled"] is False
    assert result.json()["data"]["source_ready"] is True
    endpoint.service.start.assert_not_called()


def test_pending_image_download_is_404_and_does_not_trigger_generation(endpoint):
    response = endpoint.client.post("/api/image-diagrams/study/source-1/generate", json=manual_request())
    job_id = response.json()["data"]["id"]
    assert endpoint.client.get(f"/api/image-diagrams/jobs/{job_id}/image").status_code == 404
    endpoint.service.client.generate.assert_not_called()


def test_authenticated_enabled_user_missing_optional_enabled_field_is_accepted(endpoint, monkeypatch):
    task = {"task_id": "task-1", "owner_user_id": "owner-1", "status": "completed"}
    monkeypatch.setattr(endpoint.module, "get_cache_manager",
                        lambda: SimpleNamespace(get_task_by_view_token=lambda _: task))
    monkeypatch.setattr(endpoint.module, "get_user_manager",
                        lambda: SimpleNamespace(get_user_by_id=lambda _: {"user_id": "owner-1"}))
    endpoint.service.authorize = endpoint.module.require_source_access
    result = endpoint.client.get("/api/image-diagrams/study/source-1")
    assert result.status_code == 200
    assert result.json()["data"]["source_ready"] is True
