import threading
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from video_transcript_api.api.routes import collections
from video_transcript_api.api.services.transcription import verify_token
from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.collections import repository as collection_repository_module
from video_transcript_api.collections.repository import LearningCollectionRepository
from video_transcript_api.collections.service import LearningCollectionService
from video_transcript_api.collections.transcription import (
    CollectionQuoteConfirmationResult,
    CollectionQuoteRefreshResult,
    CollectionQuoteSnapshot,
    CollectionStartResult,
    CollectionStopResult,
    SourceLaunch,
)
from video_transcript_api.transcriber.cloud_quote_repository import CloudQuoteConflict


class RecordingController:
    def __init__(self):
        self.calls = []

    def update_soft_limits(self, **values):
        self.calls.append(values)


def _client(tmp_path, monkeypatch, *, strategy="local", concurrency=1):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repository = LearningCollectionRepository(tmp_path / "collections.db")
    service = LearningCollectionService(repository=repository, cache_manager=cache)
    collection = service.create_collection(
        "Series", "Teacher", "video_course", owner_user_id="owner",
        transcription_strategy=strategy, transcription_concurrency=concurrency,
    )
    controller = RecordingController()
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    monkeypatch.setattr(collections, "cache_manager", cache)
    monkeypatch.setattr(collections, "get_collection_service", lambda: service)
    monkeypatch.setattr(
        collections, "get_transcription_concurrency_controller", lambda: controller
    )
    monkeypatch.setattr(collections, "_source_files_dir", lambda: source_dir)
    # Multipart staging now uses temp/collection_staging; keep tests on one dir.
    monkeypatch.setattr(collections, "_ephemeral_collection_staging_dir", lambda: source_dir)
    scheduled = []
    monkeypatch.setattr(collections, "process_local_upload", lambda *a, **kw: scheduled.append((a, kw)))
    app = FastAPI()
    app.include_router(collections.router)
    app.dependency_overrides[verify_token] = lambda: {"user_id": "owner", "api_key": "test"}
    return TestClient(app), collection, repository, cache, controller, scheduled


def _task_rows(cache):
    with sqlite3.connect(cache.db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM task_status")]


def test_upload_uses_saved_preference_and_updates_local_effective_limit(tmp_path, monkeypatch):
    client, collection, repository, _, controller, scheduled = _client(
        tmp_path, monkeypatch, strategy="local", concurrency=3
    )

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("one.mp4", b"one", "video/mp4"))],
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["pending_count"] == 1
    assert data["requested_concurrency"] == 3
    assert data["effective_concurrency"] == 1
    assert controller.calls == [{"local": 1}]
    assert len(scheduled) == 1
    args, kwargs = scheduled[0]
    # use_speaker=False, preserve_source=True (open/re-parse UX), timestamps=True
    assert args[5:8] == (False, True, True)
    assert kwargs == {
        "transcription_strategy": "local",
        "cloud_confirmation_required": False,
    }
    assert repository.get_collection(collection["id"])["transcription_concurrency"] == 3


def test_cloud_upload_saves_override_but_does_not_update_soft_limit(tmp_path, monkeypatch):
    client, collection, repository, _, controller, scheduled = _client(tmp_path, monkeypatch)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        data={"transcription_strategy": "cloud", "transcription_concurrency": "7"},
        files=[("files", ("one.mp4", b"one", "video/mp4"))],
    )

    assert response.status_code == 202
    assert controller.calls == []
    assert scheduled[0][1] == {
        "transcription_strategy": "cloud",
        "cloud_confirmation_required": True,
    }
    saved = repository.get_collection(collection["id"])
    assert (saved["transcription_strategy"], saved["transcription_concurrency"]) == ("cloud", 7)


def test_retry_cloud_source_preserves_strategy_and_requires_new_quote(
    tmp_path, monkeypatch
):
    client, collection, _, cache, _, scheduled = _client(
        tmp_path, monkeypatch, strategy="cloud", concurrency=5
    )
    uploaded = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("one.mp4", b"one", "video/mp4"))],
    )
    source = uploaded.json()["data"]["sources"][0]
    cache.update_task_status(
        source["task_id"],
        "failed",
        error_message="云端转录失败（provider_failed）",
    )
    scheduled.clear()

    response = client.post(
        f"/api/collections/{collection['id']}/sources/{source['id']}/retry"
    )

    assert response.status_code == 202
    assert len(scheduled) == 1
    args, kwargs = scheduled[0]
    assert args[5:8] == (False, True, True)
    assert kwargs == {
        "transcription_strategy": "cloud",
        "cloud_confirmation_required": True,
        "skip_cache": True,
    }


def test_successful_source_can_be_explicitly_reparsed_without_reusing_cache(
    tmp_path, monkeypatch
):
    client, collection, _, cache, _, scheduled = _client(
        tmp_path, monkeypatch, strategy="cloud", concurrency=5
    )
    uploaded = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("one.mp4", b"one", "video/mp4"))],
    )
    source = uploaded.json()["data"]["sources"][0]
    cache.update_task_status(
        source["task_id"],
        "success",
        platform="generic",
        media_id="one",
    )
    scheduled.clear()

    response = client.post(
        f"/api/collections/{collection['id']}/sources/{source['id']}/retry"
    )

    assert response.status_code == 202
    retried_source = response.json()["data"]["source"]
    assert retried_source["view_token"] != source["view_token"]
    retried_task = cache.get_task_by_id(retried_source["task_id"])
    assert retried_task["owner_user_id"] == "owner"
    assert scheduled[0][1] == {
        "transcription_strategy": "cloud",
        "cloud_confirmation_required": True,
        "skip_cache": True,
    }


def test_all_cached_upload_does_not_schedule_or_touch_controller(tmp_path, monkeypatch):
    client, collection, _, cache, controller, scheduled = _client(tmp_path, monkeypatch)
    content = b"same-video"
    digest = collections._sha256_bytes(content)
    media_id = collections._media_id_for_upload_hash(digest)
    task = cache.create_task(
        url=f"local://collection-source/{media_id}/old.mp4",
        platform="generic", media_id=media_id, owner_user_id="old-owner",
    )
    cache.update_task_status(
        task["task_id"], "success", platform="generic", media_id=media_id,
        title="old.mp4", author="old", cache_id=1,
    )
    monkeypatch.setattr(cache, "get_cache", lambda **kwargs: {"id": 1, "llm_summary": "ready"})

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("again.mp4", content, "video/mp4"))],
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["cache_hit_count"] == 1
    assert data["pending_count"] == 0
    assert data["effective_concurrency"] is None
    assert controller.calls == []
    assert scheduled == []
    alias_task = cache.get_task_by_id(data["sources"][0]["task_id"])
    assert alias_task["owner_user_id"] == "owner"
    assert alias_task["progress"]["evidence"]["cache_hit"] is True
    assert alias_task["cache_id"] == 1


def test_upload_partial_override_uses_and_saves_existing_concurrency(tmp_path, monkeypatch):
    client, collection, repository, _, controller, scheduled = _client(
        tmp_path, monkeypatch, strategy="local", concurrency=3
    )

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        data={"transcription_strategy": "cloud"},
        files=[("files", ("one.mp4", b"one", "video/mp4"))],
    )

    assert response.status_code == 202
    saved = repository.get_collection(collection["id"])
    assert (saved["transcription_strategy"], saved["transcription_concurrency"]) == ("cloud", 3)
    assert controller.calls == []
    assert len(scheduled) == 1


def test_upload_rejects_out_of_range_concurrency_before_creating_tasks(tmp_path, monkeypatch):
    client, collection, repository, cache, controller, scheduled = _client(tmp_path, monkeypatch)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        data={"transcription_concurrency": "4"},
        files=[("files", ("one.mp4", b"one", "video/mp4"))],
    )

    assert response.status_code == 422
    assert repository.get_sources(collection["id"]) == []
    assert cache.get_existing_task_by_media("generic", "missing", False) is None
    assert controller.calls == []
    assert scheduled == []


def test_duplicate_hash_removes_only_unreferenced_extension_file(tmp_path, monkeypatch):
    client, collection, repository, _, _, _ = _client(tmp_path, monkeypatch)
    content = b"same-video"

    first = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("lesson.mp4", content, "video/mp4"))],
    )
    different_extension = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("lesson.mov", content, "video/quicktime"))],
    )
    same_path = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[("files", ("lesson.mp4", content, "video/mp4"))],
    )

    assert [first.status_code, different_extension.status_code, same_path.status_code] == [202, 202, 202]
    assert len(repository.get_sources(collection["id"])) == 1
    assert [path.suffix for path in (tmp_path / "sources").iterdir()] == [".mp4"]


def test_concurrent_duplicate_hash_removes_loser_stable_file(tmp_path, monkeypatch):
    client, collection, repository, _, _, _ = _client(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    responses = []

    def upload(filename, content_type):
        barrier.wait()
        responses.append(
            client.post(
                f"/api/collections/{collection['id']}/sources/upload",
                files=[("files", (filename, b"same-video", content_type))],
            )
        )

    threads = [
        threading.Thread(target=upload, args=("lesson.mp4", "video/mp4")),
        threading.Thread(target=upload, args=("lesson.mov", "video/quicktime")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [response.status_code for response in responses] == [202, 202]
    assert len(repository.get_sources(collection["id"])) == 1
    assert len(list((tmp_path / "sources").iterdir())) == 1


def test_same_hash_across_collections_uses_independent_owned_files(
    tmp_path, monkeypatch
):
    client, first_collection, repository, cache, _, _ = _client(
        tmp_path, monkeypatch
    )
    second_collection = LearningCollectionService(
        repository=repository, cache_manager=cache
    ).create_collection(
        "Other Series",
        "Teacher",
        "video_course",
        owner_user_id="owner",
    )
    content = b"same-video"

    first = client.post(
        f"/api/collections/{first_collection['id']}/sources/upload",
        files=[("files", ("lesson.mp4", content, "video/mp4"))],
    )
    second = client.post(
        f"/api/collections/{second_collection['id']}/sources/upload",
        files=[("files", ("lesson.mp4", content, "video/mp4"))],
    )

    assert [first.status_code, second.status_code] == [202, 202]
    first_task = cache.get_task_by_id(first.json()["data"]["sources"][0]["task_id"])
    second_task = cache.get_task_by_id(second.json()["data"]["sources"][0]["task_id"])
    first_path = first_task["source_file_path"]
    second_path = second_task["source_file_path"]
    assert first_path != second_path
    assert Path(first_path).is_file()
    assert Path(second_path).is_file()

    collections._cleanup_unreferenced_candidate_files(
        candidates=[{"file_path": first_path}],
        sources=(),
        launches=(),
        created_paths={str(Path(first_path).resolve())},
    )

    assert not Path(first_path).exists()
    assert Path(second_path).is_file()


def test_upload_validates_entire_batch_before_writing_any_file(
    tmp_path, monkeypatch
):
    client, collection, repository, cache, controller, scheduled = _client(
        tmp_path, monkeypatch
    )

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[
            ("files", ("lesson.mp4", b"valid-video", "video/mp4")),
            ("files", ("notes.txt", b"not-a-video", "text/plain")),
        ],
    )

    assert response.status_code == 400
    assert repository.get_sources(collection["id"]) == []
    assert _task_rows(cache) == []
    assert list((tmp_path / "sources").iterdir()) == []
    assert controller.calls == []
    assert scheduled == []


def test_second_source_registration_failure_rolls_back_batch_and_files(
    tmp_path, monkeypatch
):
    client, collection, repository, cache, controller, scheduled = _client(
        tmp_path, monkeypatch
    )
    app = client.app
    client.close()
    client = TestClient(app, raise_server_exceptions=False)
    original_execute = collection_repository_module._ConnectionCursor.execute
    source_insert_count = 0

    def fail_second_source_insert(self, statement, parameters=()):
        nonlocal source_insert_count
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("INSERT INTO LEARNING_COLLECTION_SOURCES"):
            source_insert_count += 1
            if source_insert_count == 2:
                raise RuntimeError("injected second source failure")
        return original_execute(self, statement, parameters)

    monkeypatch.setattr(
        collection_repository_module._ConnectionCursor,
        "execute",
        fail_second_source_insert,
    )

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[
            ("files", ("one.mp4", b"one", "video/mp4")),
            ("files", ("two.mp4", b"two", "video/mp4")),
        ],
    )

    assert response.status_code == 500
    assert repository.get_sources(collection["id"]) == []
    assert all(row["status"] != "queued" for row in _task_rows(cache))
    assert list((tmp_path / "sources").iterdir()) == []
    assert controller.calls == []
    assert scheduled == []


def test_registration_failure_preserves_concurrent_replacement_file(
    tmp_path, monkeypatch
):
    client, collection, repository, cache, _, _ = _client(tmp_path, monkeypatch)
    app = client.app
    client.close()
    client = TestClient(app, raise_server_exceptions=False)
    concurrent_task_id = None

    def add_concurrent_winner_then_fail(collection_id, entries):
        nonlocal concurrent_task_id
        first_task = cache.get_task_by_id(entries[0]["task_id"])
        winner = cache.create_task(
            url=first_task["url"],
            platform="generic",
            media_id=first_task["media_id"],
            source_file_path=first_task["source_file_path"],
            owner_user_id="owner",
        )
        concurrent_task_id = winner["task_id"]
        repository.add_source(
            collection_id,
            winner["task_id"],
            winner["view_token"],
            entries[0]["title"],
            entries[0]["source_type"],
            position=entries[0]["position"],
            content_sha256=entries[0]["content_sha256"],
        )
        raise RuntimeError("injected failure after concurrent winner")

    monkeypatch.setattr(
        repository, "register_source_batch", add_concurrent_winner_then_fail
    )

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[
            ("files", ("one.mp4", b"one", "video/mp4")),
            ("files", ("two.mp4", b"two", "video/mp4")),
        ],
    )

    assert response.status_code == 500
    sources = repository.get_sources(collection["id"])
    assert len(sources) == 1
    assert sources[0]["task_id"] == concurrent_task_id
    winner = cache.get_task_by_id(concurrent_task_id)
    assert winner["status"] == "queued"
    assert Path(winner["source_file_path"]).is_file()


def test_batch_registration_failure_preserves_collection_derived_state(
    tmp_path, monkeypatch
):
    client, collection, repository, cache, _, scheduled = _client(
        tmp_path, monkeypatch
    )
    source_dir = tmp_path / "sources"
    original_file = source_dir / "original.mp4"
    original_file.write_bytes(b"original")
    original_task = cache.create_task(
        url="local://collection-source/original/original.mp4",
        platform="generic",
        media_id="original",
        source_file_path=str(original_file),
        owner_user_id="owner",
    )
    cache.update_task_status(original_task["task_id"], "success")
    original_source = repository.add_source(
        collection["id"],
        original_task["task_id"],
        original_task["view_token"],
        "original.mp4",
        "video",
        content_sha256="original-sha",
    )
    repository.save_summary(collection["id"], "# Existing summary")
    repository.mark_exported(collection["id"])
    repository.save_knowledge_map(
        collection["id"],
        "collection",
        {"version": 1, "scope": "collection", "nodes": ["existing"]},
    )
    repository.save_knowledge_map(
        collection["id"],
        "source",
        {"version": 1, "scope": "source", "nodes": ["existing-source"]},
        source_id=original_source["id"],
    )
    before_collection = repository.get_collection(collection["id"])
    before_sources = repository.get_sources(collection["id"])
    before_collection_map = repository.get_knowledge_map(
        collection["id"], "collection"
    )
    before_source_map = repository.get_knowledge_map(
        collection["id"], "source", original_source["id"]
    )
    before_files = sorted(path.name for path in source_dir.iterdir())
    original_execute = collection_repository_module._ConnectionCursor.execute
    source_insert_count = 0

    def fail_second_source_insert(self, statement, parameters=()):
        nonlocal source_insert_count
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("INSERT INTO LEARNING_COLLECTION_SOURCES"):
            source_insert_count += 1
            if source_insert_count == 2:
                raise RuntimeError("injected second source insert failure")
        return original_execute(self, statement, parameters)

    monkeypatch.setattr(
        collection_repository_module._ConnectionCursor,
        "execute",
        fail_second_source_insert,
    )
    app = client.app
    client.close()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/collections/{collection['id']}/sources/upload",
        files=[
            ("files", ("one.mp4", b"one", "video/mp4")),
            ("files", ("two.mp4", b"two", "video/mp4")),
        ],
    )

    assert response.status_code == 500
    after_collection = repository.get_collection(collection["id"])
    assert repository.get_sources(collection["id"]) == before_sources
    assert after_collection["status"] == before_collection["status"] == "summarized"
    assert after_collection["summary_status"] == before_collection["summary_status"]
    assert after_collection["summary_markdown"] == before_collection["summary_markdown"]
    assert after_collection["exported_at"] == before_collection["exported_at"]
    assert (
        after_collection["transcription_revision"]
        == before_collection["transcription_revision"]
    )
    assert repository.get_knowledge_map(
        collection["id"], "collection"
    ) == before_collection_map
    assert repository.get_knowledge_map(
        collection["id"], "source", original_source["id"]
    ) == before_source_map
    assert sorted(path.name for path in source_dir.iterdir()) == before_files
    new_tasks = [
        row for row in _task_rows(cache)
        if row["task_id"] != original_task["task_id"]
    ]
    assert all(row["status"] != "queued" for row in new_tasks)
    assert scheduled == []


class _CollectionTranscriptionDouble:
    def __init__(self, collection, *, quote_snapshot=None, refresh_result=None):
        self.repository = SimpleNamespace(get_collection=lambda collection_id: collection)
        self.quote_snapshot = quote_snapshot
        self.refresh_result = refresh_result
        self.confirm_calls = []
        self.continue_calls = []
        self.stop_calls = []

    def get_cloud_quote_snapshot(self, collection_id, *, owner_user_id):
        assert owner_user_id == "owner"
        return self.quote_snapshot

    def refresh_collection_cloud_quotes(self, collection_id, *, owner_user_id):
        assert owner_user_id == "owner"
        return self.refresh_result

    def confirm_collection_cloud_quotes(self, collection_id, **kwargs):
        self.confirm_calls.append((collection_id, kwargs))
        return CollectionQuoteConfirmationResult("confirmed", ("task-a",))

    def continue_collection(self, collection_id, **kwargs):
        self.continue_calls.append((collection_id, kwargs))
        return CollectionStartResult(
            sources=(),
            launches=(
                SourceLaunch(
                    source_id="source-a",
                    task_id="task-a",
                    file_path="/stable/a.mp4",
                    original_name="a.mp4",
                    display_url="local://collection/a.mp4",
                    media_id="media-a",
                    strategy=kwargs["strategy"],
                ),
            ),
            cache_hit_count=0,
            requested_concurrency=kwargs["requested_concurrency"],
            effective_concurrency=1,
        )

    def stop_collection(self, collection_id, *, owner_user_id):
        self.stop_calls.append((collection_id, owner_user_id))
        return CollectionStopResult(self.repository.get_collection(collection_id), 1, 0)


def _route_client(tmp_path, monkeypatch, *, strategy="cloud"):
    client, collection, _, _, _, scheduled = _client(
        tmp_path, monkeypatch, strategy=strategy
    )
    snapshot = CollectionQuoteSnapshot(
        state="ready",
        video_count=1,
        cache_hit_count=0,
        pending_count=1,
        duration_seconds=Decimal("1.25"),
        billable_seconds=2,
        max_cost_cny=Decimal("0.50"),
        transcription_revision=3,
        items=(
            SimpleNamespace(
                task_id="task-a",
                source_id="source-a",
                title="a.mp4",
                quote_token="quote-a",
                duration_seconds=Decimal("1.25"),
                billable_seconds=2,
                max_cost_cny=Decimal("0.50"),
            ),
        ),
        failures=(),
    )
    transcription = _CollectionTranscriptionDouble(collection, quote_snapshot=snapshot)
    monkeypatch.setattr(
        collections,
        "get_collection_transcription_service",
        lambda: transcription,
        raising=False,
    )
    return client, collection, transcription, scheduled


def test_cloud_quote_serializes_decimal_snapshot(tmp_path, monkeypatch):
    client, collection, _, _ = _route_client(tmp_path, monkeypatch)

    response = client.get(f"/api/collections/{collection['id']}/cloud-quote")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "ready"
    assert data["max_cost_cny"] == "0.50"
    assert data["items"] == [{
        "task_id": "task-a", "source_id": "source-a", "title": "a.mp4",
        "quote_token": "quote-a", "duration_seconds": "1.25",
        "billable_seconds": 2, "max_cost_cny": "0.50",
    }]


def test_cloud_refresh_returns_refreshed_snapshot(tmp_path, monkeypatch):
    client, collection, transcription, _ = _route_client(tmp_path, monkeypatch)
    transcription.refresh_result = CollectionQuoteRefreshResult(
        snapshot=transcription.quote_snapshot,
        failures=(),
    )

    response = client.post(
        f"/api/collections/{collection['id']}/cloud-quote/refresh"
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "snapshot": {
            "state": "ready", "video_count": 1, "cache_hit_count": 0,
            "pending_count": 1, "duration_seconds": "1.25",
            "billable_seconds": 2, "max_cost_cny": "0.50",
            "transcription_revision": 3,
            "items": [{
                "task_id": "task-a", "source_id": "source-a", "title": "a.mp4",
                "quote_token": "quote-a", "duration_seconds": "1.25",
                "billable_seconds": 2, "max_cost_cny": "0.50",
            }],
            "failures": [],
        },
        "failures": [],
    }


def test_cloud_confirm_translates_decimal_and_notifies_only_after_configuration_check(
    tmp_path, monkeypatch
):
    client, collection, transcription, _ = _route_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        collections,
        "get_cloud_asr_dispatcher",
        lambda: (_ for _ in ()).throw(RuntimeError("cloud_asr_dispatcher_unavailable")),
    )

    unavailable = client.post(
        f"/api/collections/{collection['id']}/cloud-confirm",
        json={
            "transcription_revision": 3,
            "accepted_total_cny": "0.50",
            "confirmations": [{
                "task_id": "task-a", "quote_token": "quote-a",
                "accepted_max_cost_cny": "0.50",
            }],
        },
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "cloud_asr_dispatcher_unavailable"
    assert transcription.confirm_calls == []


def test_cloud_confirm_accepts_unchanged_quote_and_maps_quote_conflict(
    tmp_path, monkeypatch
):
    client, collection, transcription, _ = _route_client(tmp_path, monkeypatch)
    dispatcher = SimpleNamespace(notify=lambda task_id: True)
    monkeypatch.setattr(collections, "get_cloud_asr_dispatcher", lambda: dispatcher)
    body = {
        "transcription_revision": 3,
        "accepted_total_cny": "0.50",
        "confirmations": [{
            "task_id": "task-a", "quote_token": "quote-a",
            "accepted_max_cost_cny": "0.50",
        }],
    }

    accepted = client.post(
        f"/api/collections/{collection['id']}/cloud-confirm", json=body
    )
    transcription.confirm_collection_cloud_quotes = lambda *args, **kwargs: (
        (_ for _ in ()).throw(CloudQuoteConflict("collection_cloud_quote_changed"))
    )
    conflict = client.post(
        f"/api/collections/{collection['id']}/cloud-confirm", json=body
    )

    assert accepted.status_code == 202
    assert transcription.confirm_calls[0][1]["accepted_total"] == Decimal("0.50")
    assert transcription.confirm_calls[0][1]["confirmations"][0].token == "quote-a"
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "collection_cloud_quote_changed"


@pytest.mark.parametrize("strategy", ["local", "cloud"])
def test_continue_collection_schedules_source_launches_and_cancel_uses_stop(
    tmp_path, monkeypatch, strategy
):
    client, collection, transcription, scheduled = _route_client(
        tmp_path, monkeypatch, strategy=strategy
    )

    continued = client.post(
        f"/api/collections/{collection['id']}/continue",
        json={"transcription_strategy": strategy, "transcription_concurrency": 2},
    )
    stopped = client.post(f"/api/collections/{collection['id']}/cancel")

    assert continued.status_code == 202
    assert transcription.continue_calls == [(
        collection["id"], {"owner_user_id": "owner", "strategy": strategy, "requested_concurrency": 2}
    )]
    assert len(scheduled) == 1
    assert scheduled[0][0][0] == "task-a"
    assert scheduled[0][1]["transcription_strategy"] == strategy
    assert scheduled[0][1]["cloud_confirmation_required"] is (strategy == "cloud")
    assert stopped.status_code == 200
    assert transcription.stop_calls == [(collection["id"], "owner")]
