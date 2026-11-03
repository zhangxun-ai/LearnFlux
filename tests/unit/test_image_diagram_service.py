"""Offline end-to-end coverage for manual paid image jobs and source access."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import struct
import zlib

import pytest

from video_transcript_api.image_diagrams.artifacts import ImageDiagramArtifacts
from video_transcript_api.image_diagrams.client import ImageDiagramAPIError
from video_transcript_api.image_diagrams.config import ImageDiagramSettings
from video_transcript_api.image_diagrams.repository import ImageDiagramRepository
from video_transcript_api.image_diagrams.service import ImageDiagramService
from video_transcript_api.image_diagrams.source import snapshot_session


def tiny_png() -> bytes:
    """Build a complete valid RGB PNG with CRCs, without an image service."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * 2) * 2))
            + chunk(b"IEND", b""))


class FakeImageClient:
    def __init__(self):
        self.plan_calls = []
        self.image_calls = []
        self.review_calls = []
        self.plan_error = None
        self.image_error = None
        self.review_error = None
        self.after_plan = None

    def plan(self, source, request, *, on_progress=None):
        self.plan_calls.append((deepcopy(source), deepcopy(request)))
        if on_progress:
            on_progress({"phase": "reading", "completed_chunks": 0, "total_chunks": 1})
        if self.plan_error:
            raise self.plan_error
        if self.after_plan:
            self.after_plan()
        return {
            "title": "Source-based guide", "learning_goal": "Understand the relation",
            "must_show": [{"text": "Source-supported relationship", "source_ref_ids": [source["paragraphs"][0]["id"]]}],
            "sections": [{"id": "main", "title": "Main idea", "source_ref_ids": [source["paragraphs"][0]["id"]]}],
            "caveats": ["Author experience"],
            "usage": {"input_tokens": 11, "output_tokens": 12},
        }

    def generate(self, prompt, references, revision_image=None):
        self.image_calls.append({"prompt": prompt, "references": references, "revision_image": revision_image})
        if self.image_error:
            raise self.image_error
        return {"image_bytes": tiny_png(), "usage": {"output_tokens": 20}, "request_id": "provider-test-request"}

    def review(self, image_path, source, plan):
        self.review_calls.append((image_path, deepcopy(source), deepcopy(plan)))
        if self.review_error:
            raise self.review_error
        return {"status": "passed", "summary": "Source relationships match", "issues": [],
                "usage": {"input_tokens": 30, "output_tokens": 4}}


def request(**overrides):
    result = {
        "scope": "overview", "section_id": None, "style": "warm-guide",
        "instructions": "", "revision_of": None, "request_id": "request-123456",
        "regenerate": False,
    }
    result.update(overrides)
    return result


@pytest.fixture
def service(tmp_path):
    source = snapshot_session({
        "metadata": {"title": "Source title"},
        "transcript": {"lines": [
            {"id": "line-1", "text": "a" * 35000 + "PRIVATE_SOURCE_TAIL", "start_seconds": 3},
            {"id": "line-2", "text": "A second source detail", "start_seconds": 8},
        ]},
        "ai": {"overview": "Existing summary"},
    })
    reference_dir = tmp_path / "references"
    reference_dir.mkdir()
    for name in ("warm-guide.png", "handdrawn.png"):
        (reference_dir / name).write_bytes(tiny_png())
    settings = ImageDiagramSettings(api_key="test-key-never-export", enabled=True,
                                    data_dir=tmp_path / "private-images")
    record = ImageDiagramService(
        repository=ImageDiagramRepository(tmp_path / "jobs.db"), settings=settings,
        client=FakeImageClient(), source_loader=lambda _token: deepcopy(source),
        authorize=lambda _token, _owner: None, reference_dir=reference_dir,
    )
    return record


def test_state_and_prepare_never_invoke_external_apis(service):
    initial = service.state("source-1", "owner-1")
    assert initial["enabled"] and initial["source_ready"]
    assert initial["versions"] == []
    first = service.prepare("source-1", "owner-1", request())
    state = service.state("source-1", "owner-1")
    assert first["status"] == "queued"
    assert state["active_job"]["id"] == first["id"]
    assert service.client.plan_calls == service.client.image_calls == service.client.review_calls == []


def test_planning_progress_is_persisted_and_removed_when_final_plan_arrives(service):
    job = service.prepare("source-1", "owner-1", request())
    seen = []
    service.client.after_plan = lambda: seen.append(service.public(service.repository.get(job["id"])))
    service.process_next()
    assert seen[0]["progress"] == {"phase": "reading", "completed_chunks": 0, "total_chunks": 1}
    assert "source" not in seen[0]
    assert service.public(service.repository.get(job["id"]))["progress"] is None


def test_public_evidence_includes_refs_from_later_sections(service):
    job = service.prepare("source-1", "owner-1", request())
    token = service.repository.claim_next()["generation_token"]
    refs = job["source"]["paragraphs"]
    service.repository.update(job["id"], token, plan={
        "must_show": [{"text": "Headline", "source_ref_ids": [refs[0]["id"]]}],
        "sections": [{"title": "Later topic", "source_ref_ids": [refs[-1]["id"]]}],
    })
    public = service.public(service.repository.get(job["id"]))
    assert {item["id"] for item in public["source_refs"]} == {refs[0]["id"], refs[-1]["id"]}


def test_process_once_caches_recipe_and_preserves_usage_and_image(service):
    first = service.prepare("source-1", "owner-1", request())
    same = service.prepare("source-1", "owner-1", request())
    assert same["id"] == first["id"]
    assert service.process_next()
    assert service.process_next() is False
    record = service.repository.get(first["id"])
    assert record["status"] == "succeeded"
    assert record["review"] is None
    assert service.artifacts.image_path(record["image_key"]).read_bytes() == tiny_png()
    assert record["usage"]["image"]["usage"]["output_tokens"] == 20
    assert record["usage"]["planning"]["input_tokens"] == 11
    assert "review" not in record["usage"]
    assert service.client.review_calls == []
    assert len(service.client.image_calls) == 1
    cached = service.prepare("source-1", "owner-1", request(request_id="another-click"))
    assert cached["id"] == first["id"]
    assert service.process_next() is False
    assert len(service.client.image_calls) == 1


@pytest.mark.parametrize("failure", [
    ImageDiagramAPIError("openai_access_denied"),
    ImageDiagramAPIError("image_outcome_unknown", unknown_outcome=True),
])
def test_same_request_id_cannot_change_payload_after_failed_or_unknown(service, failure):
    service.client.image_error = failure
    first = service.prepare("source-1", "owner-1", request())
    service.process_next()
    result = service.repository.get(first["id"])
    assert result["status"] in {"failed", "unknown"}
    assert service.prepare("source-1", "owner-1", request())["id"] == first["id"]
    with pytest.raises(ValueError, match="request_key_conflict"):
        service.prepare("source-1", "owner-1", request(instructions="Different instructions"))
    assert service.process_next() is False
    assert len(service.client.image_calls) == 1


@pytest.mark.parametrize("failure,status", [
    (TimeoutError("untrusted provider exception text"), "unknown"),
    (ImageDiagramAPIError("image_outcome_unknown", unknown_outcome=True), "unknown"),
    (ImageDiagramAPIError("openai_request_rejected"), "failed"),
])
def test_image_request_errors_have_conservative_outcomes(service, failure, status):
    service.client.image_error = failure
    job = service.prepare("source-1", "owner-1", request())
    service.process_next()
    result = service.repository.get(job["id"])
    assert result["status"] == status
    assert result["submitted_at"]
    assert len(service.client.image_calls) == 1
    assert service.process_next() is False
    assert "untrusted provider exception text" not in json.dumps(result)


def test_local_failure_after_remote_success_is_unknown_without_duplicate_image_call(service, monkeypatch):
    monkeypatch.setattr(service.artifacts, "save_image", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    job = service.prepare("source-1", "owner-1", request())
    service.process_next()
    result = service.repository.get(job["id"])
    assert result["status"] == "unknown"
    assert result["error_code"] == "image_outcome_unknown"
    assert service.process_next() is False
    assert len(service.client.image_calls) == 1


def test_image_finishes_without_ever_calling_review(service):
    service.client.review_error = RuntimeError("review unavailable")
    job = service.prepare("source-1", "owner-1", request())
    service.process_next()
    result = service.repository.get(job["id"])
    assert result["status"] == "succeeded"
    assert result["review"] is None
    assert service.client.review_calls == []
    assert service.artifacts.image_path(result["image_key"]).is_file()
    assert len(service.client.image_calls) == 1
    assert service.prepare("source-1", "owner-1", request(request_id="read-again"))["id"] == job["id"]


def test_short_content_and_its_edits_only_make_one_image_call_each(service, monkeypatch):
    short = snapshot_session({"metadata": {"title": "A short source"}, "transcript": {
        "lines": [{"id": "line-1", "text": "Original source with a concrete example."}]}})
    service.source_loader = lambda *_: deepcopy(short)
    statuses = []
    update = service.repository.update

    def record(*args, **kwargs):
        if kwargs.get("status"):
            statuses.append(kwargs["status"])
        return update(*args, **kwargs)

    monkeypatch.setattr(service.repository, "update", record)
    first = service.prepare("source-1", "owner-1", request())
    service.process_next()
    result = service.repository.get(first["id"])
    assert result["status"] == "succeeded"
    assert result["plan"]["mode"] == "direct"
    assert service.client.plan_calls == service.client.review_calls == []
    assert len(service.client.image_calls) == 1
    assert statuses == ["generating", "succeeded"]
    assert "Original source with a concrete example." in service.client.image_calls[0]["prompt"]
    child = service.prepare("source-1", "owner-1", request(
        request_id="direct-edit", revision_of=first["id"], instructions="Larger labels"))
    service.process_next()
    assert service.repository.get(child["id"])["status"] == "succeeded"
    assert service.client.plan_calls == service.client.review_calls == []
    assert len(service.client.image_calls) == 2


def test_unchanged_long_content_reuses_plan_when_explicitly_redrawing(service):
    first = service.prepare("source-1", "owner-1", request())
    service.process_next()
    second = service.prepare("source-1", "owner-1", request(request_id="redraw-request", regenerate=True))
    service.process_next()
    assert first["id"] != second["id"]
    result = service.repository.get(second["id"])
    assert result["status"] == "succeeded"
    assert result["usage"]["planning"]["mode"] == "reused"
    assert len(service.client.plan_calls) == 1
    assert len(service.client.image_calls) == 2
    assert service.client.review_calls == []


def test_changed_source_does_not_reuse_an_older_plan(service):
    service.prepare("source-1", "owner-1", request())
    service.process_next()
    previous_loader = service.source_loader
    service.source_loader = lambda token: {**previous_loader(token), "source_hash": "new-version"}
    service.prepare("source-1", "owner-1", request(request_id="changed-source", regenerate=True))
    service.process_next()
    assert len(service.client.plan_calls) == 2


def test_revocation_during_planning_stops_before_image_call(service):
    access = {"allowed": True}

    def authorize(_token, _owner):
        if not access["allowed"]:
            raise PermissionError("access revoked")

    service.authorize = authorize
    service.client.after_plan = lambda: access.update(allowed=False)
    job = service.prepare("source-1", "owner-1", request())
    service.process_next()
    result = service.repository.get(job["id"])
    assert result["status"] == "failed"
    assert not result["submitted_at"]
    assert service.client.image_calls == []


def test_read_authorization_happens_before_source_loading(service):
    service.authorize = lambda *_: (_ for _ in ()).throw(PermissionError("denied"))
    service.source_loader = lambda *_: pytest.fail("private source loaded before authorization")
    with pytest.raises(PermissionError):
        service.state("source-1", "owner-2")
    with pytest.raises(PermissionError):
        service.prepare("source-1", "owner-2", request())


def test_owned_job_checks_identity_and_access_before_private_snapshot(service, monkeypatch):
    job = service.prepare("source-1", "owner-1", request())
    monkeypatch.setattr(service.repository, "get", lambda *_: pytest.fail("private snapshot loaded before authorization"))
    with pytest.raises(LookupError):
        service.get_owned(job["id"], "owner-2")
    service.authorize = lambda *_: (_ for _ in ()).throw(PermissionError("revoked"))
    with pytest.raises(PermissionError):
        service.get_owned(job["id"], "owner-1")


def test_explicit_revision_preserves_parent_and_passes_previous_image(service):
    first = service.prepare("source-1", "owner-1", request())
    service.process_next()
    parent = service.repository.get(first["id"])
    child = service.prepare("source-1", "owner-1", request(
        request_id="revision-123456", revision_of=parent["id"], instructions="Improve only the labels"))
    assert child["parent_id"] == parent["id"]
    assert child["id"] != parent["id"]
    service.process_next()
    assert service.repository.get(child["id"])["status"] == "succeeded"
    assert service.client.image_calls[1]["revision_image"] == service.artifacts.image_path(parent["image_key"])
    assert service.client.plan_calls[1][1]["previous_plan"] == parent["plan"]
    assert "previous_review" not in service.client.image_calls[1]["prompt"]
    assert service.repository.get(parent["id"])["image_key"] == parent["image_key"]


def test_revision_rejects_foreign_parent_without_reading_private_snapshot(service, monkeypatch):
    foreign = service.prepare("source-foreign", "owner-2", request(request_id="foreign-123456"))
    service.process_next()
    original_get = service.repository.get

    def guarded_get(job_id):
        if job_id == foreign["id"]:
            pytest.fail("foreign revision loaded a private snapshot before identity validation")
        return original_get(job_id)

    monkeypatch.setattr(service.repository, "get", guarded_get)
    with pytest.raises(ValueError, match="invalid_revision"):
        service.prepare("source-1", "owner-1", request(revision_of=foreign["id"]))


def test_quota_blocks_new_paid_work_but_allows_cached_image_reads(service):
    service.settings = replace(service.settings, max_daily_generations=1)
    first = service.prepare("source-1", "owner-1", request())
    service.process_next()
    assert service.prepare("source-1", "owner-1", request(request_id="cached-123456"))["id"] == first["id"]
    with pytest.raises(ValueError, match="^image_diagram_daily_limit$"):
        service.prepare("source-2", "owner-1", request(request_id="new-source-123456"))
    assert len(service.client.image_calls) == 1


def test_public_record_excludes_private_snapshot_prompt_request_and_fencing_token(service):
    job = service.prepare("source-1", "owner-1", request(instructions="PRIVATE_REQUEST_INSTRUCTIONS"))
    service.process_next()
    private = service.repository.get(job["id"])
    public = service.public(private)
    payload = json.dumps(public)
    for key in ("source", "request", "plan", "generation_token", "request_key", "recipe_key", "owner_user_id", "image_key"):
        assert key not in public
    for value in ("PRIVATE_SOURCE_TAIL", "PRIVATE_REQUEST_INSTRUCTIONS", service.settings.api_key,
                  private["generation_token"], private["request_key"]):
        assert value not in payload
    assert public["source_refs"][0]["line_id"] == "line-1"
    assert len(public["source_refs"][0]["excerpt"]) <= 240


def test_disabled_configuration_still_serves_read_state_without_clients(service):
    service.settings = replace(service.settings, enabled=False, api_key="")
    service.client = None
    state = service.state("source-1", "owner-1")
    assert state["enabled"] is False
    assert state["source_ready"] is True
    with pytest.raises(ValueError, match="feature_disabled"):
        service.prepare("source-1", "owner-1", request())


def test_unready_source_returns_readable_state_and_no_paid_work(service):
    service.source_loader = lambda *_: (_ for _ in ()).throw(ValueError("source_not_ready"))
    state = service.state("source-1", "owner-1")
    assert state["source_ready"] is False
    assert state["sections"] == []
    assert service.client.image_calls == []


def test_worker_rechecks_access_before_decoding_a_private_source_snapshot(service):
    job = service.prepare("source-1", "owner-1", request())
    with service.repository.database.transaction() as connection:
        connection.execute("UPDATE image_diagram_jobs SET source_json = ? WHERE id = ?",
                           ("PRIVATE_SNAPSHOT_MUST_NOT_BE_DECODED", job["id"]))
    service.authorize = lambda *_: (_ for _ in ()).throw(PermissionError("revoked"))
    assert service.process_next()
    with service.repository.database.transaction() as connection:
        row = connection.execute("SELECT status, submitted_at FROM image_diagram_jobs WHERE id = ?", (job["id"],)).fetchone()
    assert row["status"] == "failed"
    assert row["submitted_at"] is None
    assert service.client.plan_calls == service.client.image_calls == []
