from __future__ import annotations

import json
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import pytest

from video_transcript_api.api.services.post_asr import (
    build_cloud_continuation,
    dispatch_pending_post_asr,
    dispatch_post_asr,
)
import video_transcript_api.api.services.transcription as transcription_service
import video_transcript_api.api.services.llm_ops as llm_ops
import video_transcript_api.api.context as api_context
import video_transcript_api.transcriber.cloud_runtime as cloud_runtime
import video_transcript_api.transcriber.transcriber as transcriber_module
from video_transcript_api.transcriber.aliyun_client import PollTimeoutError
from video_transcript_api.transcriber.contracts import TranscriptionResult
from video_transcript_api.transcriber.cloud_quote_repository import (
    CloudQuoteRepository,
    NewCloudQuote,
)
from video_transcript_api.transcriber.media_preparer import (
    MediaPreparationError,
    PreparedASRMedia,
)
from video_transcript_api.transcriber.providers.aliyun_funasr import CloudProviderError
from video_transcript_api.transcriber.usage_repository import (
    NewASRAttempt,
    UsageEventRepository,
)


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)


def _attempt(continuation_json: str) -> NewASRAttempt:
    return NewASRAttempt(
        task_id="task-1",
        model="fun-asr-2025-11-07",
        estimated_quantity=Decimal("2"),
        unit_price=Decimal("0.00022"),
        estimated_cost=Decimal("0.00044"),
        owner_key="",
        sample_sha256="a" * 64,
        platform="youtube",
        media_id="video-1",
        output_name="lesson",
        continuation_json=continuation_json,
    )


def _materialized(repository: UsageEventRepository, continuation_json: str):
    event = repository.reserve_attempt(_attempt(continuation_json))
    assert repository.claim_submission(event.id, "asr", now=NOW)
    assert repository.record_submitted(
        event.id,
        "asr",
        now=NOW + timedelta(seconds=1),
        provider_task_id="private-task",
    )
    assert repository.record_remote_success(
        event.id,
        "asr",
        now=NOW + timedelta(seconds=2),
        reported_quantity=Decimal("2"),
        elapsed_seconds=Decimal("1"),
    )
    assert repository.record_materialization_succeeded(
        event.id, "asr", now=NOW + timedelta(seconds=3)
    )
    return repository.get_event(event.id)


def test_cloud_continuation_is_sanitized_and_persisted_before_postprocess(tmp_path):
    signed_url = (
        "https://bucket.s3.example/lesson.mp3?"
        "X-Amz-Credential=temporary&X-Amz-Signature=secret#fragment"
    )
    continuation_json = build_cloud_continuation(
        task_id="task-1",
        url=signed_url,
        display_url=signed_url,
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="Description",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    payload = json.loads(continuation_json)
    assert payload["version"] == 1
    assert payload["url"] == "https://bucket.s3.example/lesson.mp3"
    assert payload["display_url"] == "https://bucket.s3.example/lesson.mp3"
    assert "secret" not in continuation_json
    assert not {
        "wechat_webhook",
        "notification_webhooks",
        "credentials",
        "source_path",
    } & payload.keys()

    repository = UsageEventRepository(tmp_path / "cache.db")
    event = repository.reserve_attempt(_attempt(continuation_json))

    assert event.continuation_json == continuation_json
    assert "continuation_json" not in event.serialize()


def test_postprocess_duplicate_delivery_has_one_lease_and_stale_work_retries(tmp_path):
    continuation_json = build_cloud_continuation(
        task_id="task-1",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    repository = UsageEventRepository(tmp_path / "cache.db")
    event = _materialized(repository, continuation_json)

    assert repository.claim_postprocess(
        event.id, "worker-1", now=NOW + timedelta(seconds=4)
    )
    assert not repository.claim_postprocess(
        event.id, "worker-2", now=NOW + timedelta(seconds=5)
    )
    assert repository.claim_postprocess(
        event.id, "worker-2", now=NOW + timedelta(seconds=65)
    )
    assert repository.complete_postprocess(
        event.id, "worker-2", now=NOW + timedelta(seconds=66)
    )


def test_shutdown_during_post_asr_dispatch_leaves_durable_pending(tmp_path):
    continuation_json = build_cloud_continuation(
        task_id="task-1",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    repository = UsageEventRepository(tmp_path / "cache.db")
    event = _materialized(repository, continuation_json)
    (tmp_path / "lesson.txt").write_text("cloud text", encoding="utf-8")
    (tmp_path / "lesson_funasr.json").write_text(
        json.dumps({"segments": []}), encoding="utf-8"
    )
    stop_event = Event()
    queued = []
    status_updates = []

    class Cache:
        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def save_cache(self, **kwargs):
            stop_event.set()
            return True

        def update_task_status(self, *args, **kwargs):
            status_updates.append((args, kwargs))

    class Queue:
        def put(self, payload):
            queued.append(payload)

    dispatched = dispatch_pending_post_asr(
        repository=repository,
        output_dir=tmp_path,
        cache_manager=Cache(),
        llm_queue=Queue(),
        stop_event=stop_event,
    )

    assert dispatched == 0
    assert queued == []
    assert status_updates == []
    assert repository.get_event(event.id).postprocess_status == "pending"


def test_successful_task_old_queue_message_only_completes_usage(
    monkeypatch, tmp_path
):
    continuation_json = build_cloud_continuation(
        task_id="task-1",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    repository = UsageEventRepository(tmp_path / "cache.db")
    event = _materialized(repository, continuation_json)
    assert repository.claim_postprocess(event.id, "crashed", now=NOW)
    event = repository.get_event(event.id)

    class Cache:
        db_path = tmp_path / "cache.db"

        def get_task_by_id(self, task_id):
            return {"status": "success"}

    class Queue:
        def __init__(self):
            self.done = 0

        def task_done(self):
            self.done += 1

    class Coordinator:
        calls = 0

        def process(self, **kwargs):
            self.calls += 1
            raise AssertionError("terminal convergence must not call LLM")

    queue = Queue()
    coordinator = Coordinator()
    monkeypatch.setattr(llm_ops, "cache_manager", Cache())
    monkeypatch.setattr(llm_ops, "llm_task_queue", queue)
    monkeypatch.setattr(llm_ops, "llm_coordinator", coordinator)

    llm_ops._handle_llm_task(
        {
            "task_id": "task-1",
            "usage_event_id": event.id,
            "postprocess_key": event.postprocess_key,
        }
    )

    assert repository.get_event(event.id).postprocess_status == "completed"
    assert coordinator.calls == 0
    assert queue.done == 1


def test_live_and_recovered_results_use_the_same_post_asr_seam(tmp_path):
    continuation_json = build_cloud_continuation(
        task_id="task-1",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    repository = UsageEventRepository(tmp_path / "cache.db")
    event = _materialized(repository, continuation_json)
    result = TranscriptionResult(
        transcript="hello",
        txt_path=str(tmp_path / "lesson.txt"),
        funasr_json_data={"segments": []},
        generated_files=(Path(tmp_path / "lesson.txt"),),
        provider="aliyun",
        usage_event_id=event.id,
    )

    class Cache:
        def __init__(self):
            self.saved = []
            self.updated = []

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def save_cache(self, **kwargs):
            self.saved.append(kwargs)
            return True

        def update_task_status(self, *args, **kwargs):
            self.updated.append((args, kwargs))
            return True

    class Queue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

    cache = Cache()
    queue = Queue()

    assert dispatch_post_asr(
        result,
        continuation_json,
        cache_manager=cache,
        llm_queue=queue,
        repository=repository,
    )
    assert cache.saved[0]["transcript_data"] == "hello"
    assert queue.items[0]["postprocess_key"] == event.postprocess_key
    assert queue.items[0]["usage_event_id"] == event.id
    assert "source_path" not in queue.items[0]

    class QueueBeforeInsertCrash:
        def put(self, item):
            raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError, match="queue unavailable"):
        dispatch_post_asr(
            result,
            continuation_json,
            cache_manager=cache,
            llm_queue=QueueBeforeInsertCrash(),
            repository=repository,
        )
    assert repository.get_event(event.id).postprocess_status == "pending"

    class CacheAfterInsertCrash(Cache):
        def update_task_status(self, *args, **kwargs):
            raise RuntimeError("worker stopped after enqueue")

    with pytest.raises(RuntimeError, match="worker stopped after enqueue"):
        dispatch_post_asr(
            result,
            continuation_json,
            cache_manager=CacheAfterInsertCrash(),
            llm_queue=queue,
            repository=repository,
        )
    assert repository.get_event(event.id).postprocess_status == "pending"
    assert len(queue.items) == 2

    class SuccessfulCache(Cache):
        def get_task_by_id(self, task_id):
            return {"status": "success"}

    assert dispatch_post_asr(
        result,
        continuation_json,
        cache_manager=SuccessfulCache(),
        llm_queue=queue,
        repository=repository,
    )
    assert repository.get_event(event.id).postprocess_status == "completed"
    assert len(queue.items) == 2


def test_private_snapshot_protection_has_a_thirty_day_upper_bound(tmp_path):
    continuation_json = build_cloud_continuation(
        task_id="task-1",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    repository = UsageEventRepository(tmp_path / "cache.db")
    repository.reserve_attempt(_attempt(continuation_json))
    snapshot_root = tmp_path / "temp"

    assert repository.list_protected_snapshot_roots(
        snapshot_root, now=NOW
    )
    with repository._connect() as connection:
        connection.execute(
            "UPDATE usage_events SET created_at = ?, updated_at = ?",
            (
                (NOW - timedelta(days=31)).isoformat(),
                NOW.isoformat(),
            ),
        )
    assert not repository.list_protected_snapshot_roots(
        snapshot_root, now=NOW
    )


def test_internal_local_upload_cloud_path_prepares_once_and_uses_shared_seam(
    monkeypatch, tmp_path
):
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"media")
    prepared_path = tmp_path / "temp" / "cloud_quotes" / ("a" * 64) / "quote-test" / "input.m4a"
    prepared_path.parent.mkdir(parents=True)
    prepared_path.write_bytes(b"prepared")
    prepared = PreparedASRMedia(
        path=prepared_path,
        media_format="m4a",
        duration_seconds=Decimal("2"),
        size_bytes=prepared_path.stat().st_size,
        sha256=hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
        preparation="demuxed",
    )
    order = []

    class Preparer:
        def prepare(self, source_path, task_id):
            order.append("prepare")
            assert source_path == str(source)
            assert task_id == "task-local"
            return prepared

        def cleanup(self, candidate):
            order.append("cleanup")
            assert candidate is prepared

    class Cache:
        db_path = tmp_path / "cache.db"

        def update_task_status(self, *args, **kwargs):
            order.append("status")

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

    class CloudTranscriber:
        def __init__(self, *args, **kwargs):
            assert kwargs["strategy"] == "cloud"
            order.append("transcriber")

        def transcribe(self, local_file, output_base, *, context):
            order.append("transcribe")
            assert local_file == str(prepared.path)
            assert context.task_id == "task-local"
            assert context.prepared_media is prepared
            assert "source_path" not in json.loads(context.continuation_json)
            self.last_result = TranscriptionResult(
                transcript="cloud local text",
                txt_path=str(tmp_path / "lesson.txt"),
                funasr_json_data={"segments": []},
                generated_files=(tmp_path / "lesson.txt",),
                provider="aliyun",
                usage_event_id="event-1",
            )
            return self.last_result.to_legacy_dict()

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service, "get_config", lambda: {"local_whisper": {}}
    )
    monkeypatch.setattr(
        transcription_service,
        "_extract_audio_to_file",
        lambda *args: pytest.fail("cloud upload must skip legacy extraction"),
    )
    monkeypatch.setattr(
        transcription_service, "_new_media_preparer", lambda: Preparer(), raising=False
    )
    monkeypatch.setattr(transcription_service, "Transcriber", CloudTranscriber)
    monkeypatch.setattr(
        transcription_service,
        "dispatch_post_asr",
        lambda *args, **kwargs: order.append("seam") or True,
    )

    result = transcription_service.process_local_upload(
        "task-local",
        str(source),
        "lesson.mp4",
        "local://lesson",
        "media-local",
        transcription_strategy="cloud",
    )

    assert result["status"] == "success"
    assert order.count("prepare") == 1
    assert order.index("prepare") < order.index("transcriber") < order.index("transcribe")
    assert order.index("transcribe") < order.index("cleanup") < order.index("seam")


def test_cloud_upload_preparation_failure_stops_before_all_downstream_work(
    monkeypatch, tmp_path
):
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"media")
    prepare_calls = []
    downstream_calls = []

    class Preparer:
        def prepare(self, source_path, task_id):
            prepare_calls.append((source_path, task_id))
            raise MediaPreparationError("media_probe_failed")

    class Cache:
        def update_task_status(self, *args, **kwargs):
            return None

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

    def fail_if_called(seam):
        downstream_calls.append(seam)
        raise AssertionError(f"unexpected downstream seam: {seam}")

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service, "_new_media_preparer", lambda: Preparer()
    )
    monkeypatch.setattr(
        transcription_service,
        "CloudQuoteRepository",
        lambda *args, **kwargs: fail_if_called("quote"),
    )
    monkeypatch.setattr(
        transcription_service,
        "UsageEventRepository",
        lambda *args, **kwargs: fail_if_called("usage"),
    )
    monkeypatch.setattr(
        transcription_service,
        "Transcriber",
        lambda *args, **kwargs: fail_if_called("transcriber"),
    )
    monkeypatch.setattr(
        transcription_service,
        "build_aliyun_provider",
        lambda *args, **kwargs: fail_if_called("provider_factory"),
    )
    monkeypatch.setattr(
        cloud_runtime.AliyunCredentials,
        "from_environ",
        classmethod(
            lambda cls, environ: fail_if_called("credentials")
        ),
    )
    monkeypatch.setattr(
        cloud_runtime,
        "AliyunASRClient",
        lambda *args, **kwargs: fail_if_called("remote"),
    )

    result = transcription_service.process_local_upload(
        "task-prepare-failed",
        str(source),
        source.name,
        "local://lesson",
        "media-prepare-failed",
        transcription_strategy="cloud",
        cloud_confirmation_required=True,
    )

    assert result == {"status": "failed", "message": "media_probe_failed"}
    assert prepare_calls == [(str(source), "task-prepare-failed")]
    assert downstream_calls == []


def test_confirmed_quote_rehydrates_prepared_media_before_provider(
    monkeypatch, tmp_path
):
    temp_root = tmp_path / "temp"
    media_path = temp_root / "cloud_quotes" / ("b" * 64) / "quote-test" / "input.m4a"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"prepared")
    media_sha256 = hashlib.sha256(media_path.read_bytes()).hexdigest()
    prepared = PreparedASRMedia(
        path=media_path,
        media_format="m4a",
        duration_seconds=Decimal("2"),
        size_bytes=media_path.stat().st_size,
        sha256=media_sha256,
        preparation="reused",
    )
    continuation_json = build_cloud_continuation(
        task_id="task-resume",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id="task-resume",
            media_ref=media_path.relative_to(temp_root).as_posix(),
            media_sha256=media_sha256,
            duration_seconds=Decimal("2"),
            billable_seconds=2,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00044"),
            continuation_json=continuation_json,
        ),
        token="quote-token",
    )
    repository.confirm_and_queue("task-resume", "quote-token", Decimal("0.00044"))
    repository.claim_queued("task-resume", "claim-owner")
    captured = {}

    class Preparer:
        def verify_existing(self, path, expected_sha256, expected_duration):
            captured["verify"] = (Path(path), expected_sha256, expected_duration)
            return prepared

    class Cache:
        def __init__(self):
            self.db_path = db_path

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def update_task_status(self, *args, **kwargs):
            return None

    class CloudTranscriber:
        def __init__(self, *args, **kwargs):
            captured["constructed"] = True

        def transcribe(self, local_file, output_base, *, context):
            captured["path"] = local_file
            captured["context"] = context
            self.last_result = TranscriptionResult(
                transcript="cloud text",
                txt_path=str(tmp_path / "lesson.txt"),
                funasr_json_data={"segments": []},
                generated_files=(tmp_path / "lesson.txt",),
                provider="aliyun",
            )
            return self.last_result.to_legacy_dict()

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )
    monkeypatch.setattr(
        transcription_service, "_new_media_preparer", lambda: Preparer(), raising=False
    )
    monkeypatch.setattr(transcription_service, "Transcriber", CloudTranscriber)
    monkeypatch.setattr(
        transcription_service,
        "get_executor",
        lambda: SimpleNamespace(submit=lambda *args, **kwargs: None),
    )

    result = transcription_service.resume_confirmed_cloud_quote(
        "task-resume",
        claim_owner="claim-owner",
        slot_owner="slot-owner",
    )

    assert result["status"] == "processing"
    assert captured["verify"] == (media_path, media_sha256, Decimal("2"))
    assert captured["path"] == str(prepared.path)
    assert captured["context"].prepared_media is prepared


def test_corrupted_quote_media_fails_before_usage_and_provider(
    monkeypatch, tmp_path
):
    temp_root = tmp_path / "temp"
    media_path = temp_root / "cloud_quotes" / ("c" * 64) / "quote-test" / "input.m4a"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"prepared")
    media_sha256 = hashlib.sha256(media_path.read_bytes()).hexdigest()
    continuation_json = build_cloud_continuation(
        task_id="task-corrupted",
        url="https://example.com/watch/1",
        display_url="https://example.com/watch/1",
        platform="youtube",
        media_id="video-1",
        video_title="Lesson",
        author="Author",
        description="",
        is_generic=False,
        include_comments=False,
        comment_limit=100,
    )
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id="task-corrupted",
            media_ref=media_path.relative_to(temp_root).as_posix(),
            media_sha256=media_sha256,
            duration_seconds=Decimal("2"),
            billable_seconds=2,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00044"),
            continuation_json=continuation_json,
        ),
        token="quote-token",
    )
    repository.confirm_and_queue(
        "task-corrupted", "quote-token", Decimal("0.00044")
    )
    repository.claim_queued("task-corrupted", "claim-owner")
    media_path.write_bytes(b"corrupted after quote")
    provider_calls = []

    class Preparer:
        def verify_existing(self, path, expected_sha256, expected_duration):
            assert Path(path).read_bytes() == b"corrupted after quote"
            raise MediaPreparationError("media_identity_mismatch")

    class Cache:
        def __init__(self):
            self.db_path = db_path

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

        def update_task_status(self, *args, **kwargs):
            return None

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )
    monkeypatch.setattr(
        transcription_service, "_new_media_preparer", lambda: Preparer(), raising=False
    )
    monkeypatch.setattr(
        transcription_service,
        "Transcriber",
        lambda *args, **kwargs: provider_calls.append(True),
    )

    with pytest.raises(ValueError, match="retained_media_(invalid|changed)"):
        transcription_service.resume_confirmed_cloud_quote(
            "task-corrupted",
            claim_owner="claim-owner",
            slot_owner="slot-owner",
        )

    assert provider_calls == []
    with repository._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='usage_events'"
        ).fetchone()[0] == 0


def test_canceled_confirmed_cloud_quote_never_starts_provider(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id="task-canceled",
            media_ref="cloud_quotes/task-canceled/input.m4a",
            media_sha256="0" * 64,
            duration_seconds=Decimal("2"),
            billable_seconds=2,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00044"),
            continuation_json='{"version": 1}',
        ),
        token="quote-token",
    )
    repository.confirm_and_queue("task-canceled", "quote-token", Decimal("0.00044"))
    repository.claim_queued("task-canceled", "claim-owner")

    class Cache:
        def __init__(self):
            self.db_path = db_path

        def get_task_by_id(self, task_id):
            return {"status": "canceled"}

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service,
        "Transcriber",
        lambda *args, **kwargs: pytest.fail("Canceled task must not start provider"),
    )

    result = transcription_service.resume_confirmed_cloud_quote(
        "task-canceled",
        claim_owner="claim-owner",
        slot_owner="slot-owner",
    )

    assert result == {"status": "canceled", "message": "任务已取消"}


def test_cloud_quote_local_selection_retries_preparation_without_remote_asr(
    monkeypatch, tmp_path
):
    temp_root = tmp_path / "temp"
    task_id = "task-local-retry"
    media_path = (
        temp_root
        / "cloud_quotes"
        / hashlib.sha256(task_id.encode()).hexdigest()
        / "quote-local"
        / "input.m4a"
    )
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"retained quote media")
    media_sha256 = hashlib.sha256(media_path.read_bytes()).hexdigest()
    db_path = tmp_path / "cache.db"
    repository = CloudQuoteRepository(db_path)
    repository.create(
        NewCloudQuote(
            task_id=task_id,
            media_ref=media_path.relative_to(temp_root).as_posix(),
            media_sha256=media_sha256,
            duration_seconds=Decimal("2"),
            billable_seconds=2,
            model="fun-asr-2025-11-07",
            unit_price=Decimal("0.00022"),
            max_cost=Decimal("0.00044"),
            continuation_json=build_cloud_continuation(
                task_id=task_id,
                url="https://example.com/watch/1",
                display_url="https://example.com/watch/1",
                platform="youtube",
                media_id="video-1",
                video_title="Lesson",
                author="Author",
                description="",
                is_generic=False,
                include_comments=False,
                comment_limit=100,
            ),
        ),
        token="quote-token",
    )

    class Cache:
        def __init__(self, path):
            self.db_path = path

        def get_task_by_id(self, _task_id):
            return {"status": "waiting_confirmation"}

        def update_task_status(self, *args, **kwargs):
            return None

    monkeypatch.setattr(transcription_service, "cache_manager", Cache(db_path))
    monkeypatch.setattr(
        transcription_service,
        "get_transcription_control_database",
        lambda cache: db_path,
    )
    monkeypatch.setattr(
        transcription_service,
        "get_temp_manager",
        lambda: SimpleNamespace(get_temp_dir=lambda: temp_root),
    )

    first, first_acquired = transcription_service.claim_cloud_quote_local_selection(
        task_id, owner="local-1"
    )
    duplicate, duplicate_acquired = (
        transcription_service.claim_cloud_quote_local_selection(
            task_id, owner="local-2"
        )
    )
    assert first_acquired is True
    assert duplicate_acquired is False
    assert first.media_ref == duplicate.media_ref

    derived = media_path.parent / "local.audio.m4a"
    extraction_calls = []

    def extract(*args):
        extraction_calls.append(args)
        if len(extraction_calls) == 1:
            return None
        derived.write_bytes(b"derived local audio")
        return str(derived)

    queued_media = []
    monkeypatch.setattr(transcription_service, "_extract_audio_to_file", extract)
    monkeypatch.setattr(
        transcription_service,
        "submit_local_asr_continuation",
        lambda **kwargs: queued_media.append(kwargs["media"]),
    )
    monkeypatch.setattr(
        transcription_service,
        "Transcriber",
        lambda *args, **kwargs: pytest.fail("Provider must not run before queue work"),
    )

    with pytest.raises(ValueError, match="^local_media_preparation_failed$"):
        transcription_service.resume_cloud_quote_locally(
            task_id, claim_owner="local-1"
        )
    assert media_path.exists()

    _, retry_acquired = transcription_service.claim_cloud_quote_local_selection(
        task_id, owner="local-3"
    )
    assert retry_acquired is True
    transcription_service.resume_cloud_quote_locally(
        task_id, claim_owner="local-3"
    )

    assert len(queued_media) == 1
    assert queued_media[0].paths == (media_path, derived)
    assert repository.get(task_id).status == "local_queued"
    assert cloud_runtime.reconcile_stale_local_queued(
        repository,
        temp_root,
        datetime.now(UTC) + timedelta(seconds=1),
    ) == [task_id]
    assert repository.get(task_id).status == "local_selected"
    assert media_path.exists()
    with repository._connection() as connection:
        usage_table = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='usage_events'"
        ).fetchone()[0]
    assert usage_table == 0


def test_strategy_is_public_and_speaker_conflict_never_constructs_asr(
    monkeypatch, tmp_path
):
    assert "transcription_strategy" in transcription_service.TranscribeRequest.model_fields
    assert (
        transcription_service.TranscribeRequest(url="https://example.com/video")
        .transcription_strategy
        == "local"
    )
    assert (
        inspect.signature(transcription_service.process_local_upload)
        .parameters["transcription_strategy"]
        .kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    constructed = []

    class Cache:
        def update_task_status(self, *args, **kwargs):
            return True

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service,
        "Transcriber",
        lambda *args, **kwargs: constructed.append(True),
    )
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"media")

    result = transcription_service.process_local_upload(
        "task-conflict",
        str(source),
        "lesson.mp4",
        "local://lesson",
        "media-conflict",
        use_speaker_recognition=True,
        transcription_strategy="cloud",
    )

    assert result == {
        "status": "failed",
        "message": "strategy_conflicts_with_speaker_mode",
    }
    assert constructed == []

    missing = transcription_service.process_local_upload(
        "task-missing",
        str(tmp_path / "missing.mp4"),
        "missing.mp4",
        "local://missing",
        "media-missing",
        transcription_strategy="cloud",
    )
    assert missing["status"] == "failed"
    assert constructed == []


def test_cloud_unknown_states_remain_recoverable_in_service(monkeypatch, tmp_path):
    status_updates = []
    prepared_path = tmp_path / "prepared.m4a"
    prepared_path.write_bytes(b"prepared")

    class Preparer:
        def prepare(self, source_path, task_id):
            return PreparedASRMedia(
                path=prepared_path,
                media_format="m4a",
                duration_seconds=Decimal("2"),
                size_bytes=prepared_path.stat().st_size,
                sha256=hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
                preparation="demuxed",
            )

        def cleanup(self, prepared):
            return None

    class Cache:
        def update_task_status(self, task_id, status, **kwargs):
            status_updates.append(status)

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

    errors = iter(("polling_unknown", "submission_unknown"))

    class PendingCloudTranscriber:
        def __init__(self, *args, **kwargs):
            assert kwargs["strategy"] == "cloud"

        def transcribe(self, local_file, output_base, *, context):
            raise CloudProviderError(next(errors))

    monkeypatch.setattr(transcription_service, "cache_manager", Cache())
    monkeypatch.setattr(
        transcription_service, "get_config", lambda: {"local_whisper": {}}
    )
    monkeypatch.setattr(
        transcription_service, "_new_media_preparer", lambda: Preparer()
    )
    monkeypatch.setattr(
        transcription_service, "Transcriber", PendingCloudTranscriber
    )

    results = []
    for index in range(2):
        source = tmp_path / f"pending-{index}.mp4"
        source.write_bytes(b"media")
        results.append(
            transcription_service.process_local_upload(
                f"task-pending-{index}",
                str(source),
                source.name,
                f"local://pending-{index}",
                f"media-pending-{index}",
                transcription_strategy="cloud",
            )
        )

    assert [result["status"] for result in results] == [
        "processing",
        "processing",
    ]
    assert "failed" not in status_updates


def test_disabled_cloud_config_recovers_existing_task_without_resubmitting(
    monkeypatch, tmp_path
):
    status_updates = []
    prepared_path = tmp_path / "prepared.m4a"
    prepared_path.write_bytes(b"prepared")

    class Preparer:
        def prepare(self, source_path, task_id):
            return PreparedASRMedia(
                path=prepared_path,
                media_format="m4a",
                duration_seconds=Decimal("2"),
                size_bytes=prepared_path.stat().st_size,
                sha256=hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
                preparation="demuxed",
            )

        def cleanup(self, prepared):
            return None

    class Cache:
        db_path = tmp_path / "cache.db"

        def update_task_status(self, task_id, status, **kwargs):
            status_updates.append(status)

        def get_task_by_id(self, task_id):
            return {"status": "processing"}

    cache = Cache()
    repository = UsageEventRepository(cache.db_path)
    event = repository.reserve_attempt(
        NewASRAttempt(
            task_id="task-disabled-recovery",
            model="fun-asr-2025-11-07",
            estimated_quantity=Decimal("2"),
            unit_price=Decimal("0.00022"),
            estimated_cost=Decimal("0.00044"),
            owner_key="",
            sample_sha256="a" * 64,
            platform="generic",
            media_id="media-disabled-recovery",
            output_name="lesson",
        )
    )
    expired = datetime.now(UTC) - timedelta(minutes=2)
    assert repository.claim_submission(event.id, "crashed", now=expired)
    assert repository.record_submitted(
        event.id,
        "crashed",
        now=expired,
        provider_task_id="private-task",
    )

    class PollOnlyClient:
        polls = 0
        submits = 0

        def poll(self, task_id, *, poll_interval_seconds, timeout_seconds):
            self.polls += 1
            assert task_id == "private-task"
            raise PollTimeoutError("polling_unknown")

        def submit(self, *args, **kwargs):
            self.submits += 1
            raise AssertionError("same-task recovery must never submit")

    client = PollOnlyClient()
    temp_manager = SimpleNamespace(
        get_temp_dir=lambda: tmp_path / "temp"
    )
    disabled_config = {
        "local_whisper": {},
        "cloud_asr": {
            "enabled": False,
            "poll_interval_seconds": 1,
            "poll_timeout_seconds": 300,
        },
    }
    monkeypatch.setattr(transcription_service, "cache_manager", cache)
    monkeypatch.setattr(
        transcription_service, "get_config", lambda: disabled_config
    )
    monkeypatch.setattr(
        transcription_service, "_new_media_preparer", lambda: Preparer()
    )
    monkeypatch.setattr(
        transcription_service, "Transcriber", transcriber_module.Transcriber
    )
    monkeypatch.setattr(
        transcriber_module, "get_workspace_dir", lambda: tmp_path / "outputs"
    )
    monkeypatch.setattr(api_context, "get_cache_manager", lambda: cache)
    monkeypatch.setattr(api_context, "get_temp_manager", lambda: temp_manager)
    monkeypatch.setattr(
        api_context,
        "get_transcription_control_store",
        lambda: SimpleNamespace(usage_repository=repository),
    )
    monkeypatch.setattr(
        cloud_runtime.AliyunCredentials,
        "from_environ",
        classmethod(
            lambda cls, environ: SimpleNamespace(
                api_key="key",
                workspace_id="workspace",
                api_host="https://example.invalid",
            )
        ),
    )
    monkeypatch.setattr(
        cloud_runtime, "AliyunASRClient", lambda *args, **kwargs: client
    )
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"media")

    result = transcription_service.process_local_upload(
        "task-disabled-recovery",
        str(source),
        source.name,
        "local://lesson",
        "media-disabled-recovery",
        preserve_source_file=True,
        transcription_strategy="cloud",
    )

    assert result == {"status": "processing", "message": "polling_unknown"}
    assert client.polls == 1
    assert client.submits == 0
    assert "failed" not in status_updates
    with repository._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM usage_events"
        ).fetchone()[0] == 1
    factory_source = inspect.getsource(cloud_runtime.build_aliyun_provider)
    assert factory_source.index("find_recoverable_event_by_task_id") < (
        factory_source.index("NewCloudSubmissionSettings.from_config")
    )
