from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_transcript_api.transcriber.aliyun_client import (
    AliyunASRError,
    AliyunCredentials,
    PotentiallyAcceptedError,
)
from video_transcript_api.transcriber.cloud_config import NewCloudSubmissionSettings
from video_transcript_api.transcriber.contracts import TranscriptionContext
from video_transcript_api.transcriber.media_preparer import PreparedASRMedia
from video_transcript_api.transcriber.providers.aliyun_funasr import (
    AliyunFunASRProvider,
    CloudProviderError,
    LeaseHeartbeat,
)
from video_transcript_api.transcriber.providers import aliyun_funasr as provider_module
from video_transcript_api.transcriber.media_snapshot import SnapshotError
from video_transcript_api.transcriber.recovery import CloudASRRecoveryCoordinator
from video_transcript_api.transcriber.usage_repository import UsageEventRepository


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)


def _settings(accepted_cny: str | None = None) -> NewCloudSubmissionSettings:
    return NewCloudSubmissionSettings(
        provider="aliyun",
        model="fun-asr-2025-11-07",
        region="cn-beijing",
        price_cny_per_second=Decimal("0.00022"),
        price_verified_at=date(2026, 7, 21),
        poll_interval_seconds=1,
        poll_timeout_seconds=300,
        accepted_max_cost=(Decimal(accepted_cny) if accepted_cny else None),
    )


def _prepared_media(
    root: Path, task_id: str, *, duration_seconds: Decimal = Decimal("2.1")
) -> PreparedASRMedia:
    content = b"audio"
    path = (
        root
        / "cloud_quotes"
        / sha256(task_id.encode("utf-8")).hexdigest()
        / "quote-test"
        / "input.m4a"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return PreparedASRMedia(
        path=path,
        media_format="m4a",
        duration_seconds=duration_seconds,
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        preparation="reused",
    )


def _attempt_dependencies(repository):
    return {
        "attempt_reserver": repository.reserve_attempt,
        "prepared_media_cleanup": lambda _prepared: None,
    }


def test_accepted_quote_ceiling_blocks_before_usage_and_credentials(tmp_path):
    events = []
    prepared = _prepared_media(tmp_path, "task-quote")

    def never_reserve(attempt):
        events.append("reserve_and_consume")
        raise AssertionError("usage must not be reserved")

    provider = AliyunFunASRProvider(
        settings=_settings(accepted_cny="0.00044"),
        repository=SimpleNamespace(),
        snapshotter=_Snapshotter(tmp_path, events),
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: events.append("credentials"),
        client_factory=lambda credentials: None,
        attempt_reserver=never_reserve,
        prepared_media_cleanup=lambda media: events.append("cleanup_quote"),
    )

    with pytest.raises(CloudProviderError, match="cloud_quote_changed") as exc:
        provider.transcribe(
            str(tmp_path / "audio.wav"),
            "output",
            context=TranscriptionContext(
                "task-quote",
                "generic",
                "media-quote",
                accepted_max_cost=Decimal("0.00044"),
                prepared_media=prepared,
            ),
        )

    assert exc.value.code == "cloud_quote_changed"
    assert "reserve_and_consume" not in events
    assert "promote_copy" not in events
    assert "credentials" not in events
    assert "cleanup_quote" not in events


def test_accepted_long_quote_can_exceed_legacy_task_cap_before_reserving(
    tmp_path,
):
    prepared = _prepared_media(
        tmp_path, "task-long-quote", duration_seconds=Decimal("5400")
    )
    reserved = []

    def stop_after_reservation(attempt):
        reserved.append(attempt)
        raise RuntimeError("stop_after_reservation")

    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=SimpleNamespace(),
        snapshotter=SimpleNamespace(),
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: pytest.fail("credentials must not be read"),
        client_factory=lambda credentials: pytest.fail("client must not be created"),
        attempt_reserver=stop_after_reservation,
        prepared_media_cleanup=lambda media: None,
    )

    with pytest.raises(RuntimeError, match="stop_after_reservation"):
        provider.transcribe(
            str(tmp_path / "audio.wav"),
            "output",
            context=TranscriptionContext(
                "task-long-quote",
                "generic",
                "media-long-quote",
                accepted_max_cost=Decimal("1.18800"),
                prepared_media=prepared,
            ),
        )

    assert reserved[0].estimated_cost == Decimal("1.18800")


class _Snapshotter:
    def __init__(
        self,
        root: Path,
        events: list[str],
        *,
        cleanup_error: bool = False,
    ) -> None:
        self.root = root
        self.temp_root = root
        self.events = events
        self.cleanup_error = cleanup_error
        self.snapshot = SimpleNamespace(
            path=root / "1" / "input.m4a",
            task_hash="a" * 64,
            attempt_no=1,
            media_format="m4a",
            sha256="b" * 64,
            size_bytes=5,
            duration_seconds=Decimal("2.1"),
        )

    def promote(
        self,
        prepared,
        *,
        task_id,
        attempt_no,
        expected_sha256,
        create,
    ):
        self.events.append("promote_copy")
        self.snapshot.attempt_no = attempt_no
        self.snapshot.task_hash = sha256(task_id.encode("utf-8")).hexdigest()
        self.snapshot.sha256 = expected_sha256
        self.snapshot.size_bytes = prepared.size_bytes
        self.snapshot.duration_seconds = prepared.duration_seconds
        return self.snapshot

    def find_attempt(
        self,
        *,
        task_id,
        attempt_no,
        expected_sha256,
        duration_seconds,
    ):
        self.events.append("find_attempt")
        self.snapshot.task_hash = sha256(task_id.encode("utf-8")).hexdigest()
        self.snapshot.attempt_no = attempt_no
        self.snapshot.sha256 = expected_sha256
        self.snapshot.duration_seconds = Decimal(duration_seconds)
        return self.snapshot

    @contextmanager
    def open_for_upload(self, snapshot):
        self.events.append(f"open_upload:{snapshot.path.name}")
        yield SimpleNamespace(file=BytesIO(b"audio"))

    def verify_unchanged(self, handle):
        self.events.append("verify_unchanged")

    def cleanup_attempt(self, snapshot):
        self.events.append("cleanup_attempt")
        if self.cleanup_error:
            raise SnapshotError("media_cleanup_failed")


class _Repository:
    def __init__(self, delegate, events, *, persist_submitted=True):
        self.delegate = delegate
        self.events = events
        self.persist_submitted = persist_submitted

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def reserve_attempt(self, attempt, *, new_paid_attempt=False):
        event = self.delegate.reserve_attempt(
            attempt, new_paid_attempt=new_paid_attempt
        )
        self.last_event_id = event.id
        return event

    def claim_submission(self, event_id, lease_owner, *, now):
        self.events.append("claim_submission")
        return self.delegate.claim_submission(event_id, lease_owner, now=now)

    def heartbeat_lease(self, event_id, lease_owner, *, now):
        self.events.append("heartbeat")
        return self.delegate.heartbeat_lease(event_id, lease_owner, now=now)

    def record_submitted(self, event_id, lease_owner, *, now, provider_task_id):
        self.events.append("record_submitted")
        if not self.persist_submitted:
            return False
        return self.delegate.record_submitted(
            event_id,
            lease_owner,
            now=now,
            provider_task_id=provider_task_id,
        )

    def record_remote_success(self, event_id, lease_owner, **kwargs):
        self.events.append("settle")
        return self.delegate.record_remote_success(
            event_id, lease_owner, **kwargs
        )

    def record_materialization_succeeded(self, event_id, lease_owner, *, now):
        self.events.append("materialized")
        return self.delegate.record_materialization_succeeded(
            event_id, lease_owner, now=now
        )


class _Client:
    def __init__(self, events, *, text="你好，世界。"):
        self.events = events
        self.text = text

    def upload_audio(self, audio, filename):
        self.events.append("upload")
        return "oss://temporary-object"

    def submit(self, staged_uri, language_hints):
        self.events.append("submit")
        return {"task_id": "private-task", "status": "PENDING"}

    def poll(self, task_id, *, poll_interval_seconds, timeout_seconds):
        self.events.append("poll")
        assert task_id == "private-task"
        return {
            "task_id": task_id,
            "status": "SUCCEEDED",
            "usage_seconds": 2,
            "results": [
                {
                    "status": "SUCCEEDED",
                    "transcript": {
                        "text": self.text,
                        "sentences": [
                            {
                                "text": self.text,
                                "start_time": 0.0,
                                "end_time": 2.0,
                                "speaker": 0,
                            }
                        ],
                    },
                }
            ],
        }


class _SubmissionGuard:
    @contextmanager
    def hold(self):
        self.events.append("submission_guard_enter")
        try:
            yield
        finally:
            self.events.append("submission_guard_exit")

    def __init__(self, events):
        self.events = events


def test_lease_heartbeat_reclaims_same_owner_after_sleep():
    calls = []

    class Repository:
        def heartbeat_lease(self, event_id, lease_owner, *, now):
            calls.append(("heartbeat", event_id, lease_owner))
            return False

        def reclaim_lease(self, event_id, lease_owner, *, now):
            calls.append(("reclaim", event_id, lease_owner))
            return True

    heartbeat = LeaseHeartbeat(
        Repository(),
        "event-1",
        "owner-1",
        clock=lambda: NOW,
        interval_seconds=60,
    )

    heartbeat.start()
    heartbeat.ensure_owned()
    heartbeat.stop()

    assert calls == [
        ("heartbeat", "event-1", "owner-1"),
        ("reclaim", "event-1", "owner-1"),
    ]


def test_submission_guard_wraps_upload_and_task_id_persistence(tmp_path):
    events = []
    delegate = UsageEventRepository(tmp_path / "usage.sqlite3")
    repository = _Repository(delegate, events)
    snapshotter = _Snapshotter(tmp_path / "snapshots", events)
    prepared = _prepared_media(tmp_path / "prepared", "task-guard")
    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=snapshotter,
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: events.append("credentials") or object(),
        client_factory=lambda credentials: _Client(events),
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        submission_guard=_SubmissionGuard(events),
        **_attempt_dependencies(repository),
    )

    provider.transcribe(
        str(tmp_path / "source.mp3"),
        "lesson",
        context=TranscriptionContext(
            "task-guard",
            "generic",
            "media-guard",
            prepared_media=prepared,
        ),
    )

    assert events.index("submission_guard_enter") < events.index("upload")
    assert events.index("record_submitted") < events.index("submission_guard_exit")
    assert events.index("submission_guard_exit") < events.index("poll")


def test_success_orders_one_submission_settlement_and_atomic_artifacts(tmp_path):
    events: list[str] = []
    delegate = UsageEventRepository(tmp_path / "usage.sqlite3")
    repository = _Repository(delegate, events)
    snapshotter = _Snapshotter(
        tmp_path / "snapshots", events, cleanup_error=True
    )
    client = _Client(events, text="")
    prepared = _prepared_media(tmp_path / "prepared", "task-1")

    def load_credentials():
        events.append("credentials")
        return AliyunCredentials("key", "workspace", "https://example.invalid")

    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=snapshotter,
        output_dir=tmp_path / "outputs",
        credential_loader=load_credentials,
        client_factory=lambda credentials: client,
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        attempt_reserver=lambda attempt: (
            events.append("reserve_and_consume")
            or repository.reserve_attempt(attempt)
        ),
        prepared_media_cleanup=lambda media: events.append("cleanup_quote"),
        capacity_transfer_callback=lambda event: events.append(
            "capacity_transfer"
        ),
    )

    result = provider.transcribe(
        str(tmp_path / "source.mp3"),
        "lesson",
        context=TranscriptionContext(
            "task-1",
            "youtube",
            "video-1",
            prepared_media=prepared,
        ),
    )

    assert events == [
        "reserve_and_consume",
        "promote_copy",
        "cleanup_quote",
        "capacity_transfer",
        "claim_submission",
        "heartbeat",
        "credentials",
        "open_upload:input.m4a",
        "upload",
        "verify_unchanged",
        "submit",
        "record_submitted",
        "poll",
        "settle",
        "materialized",
        "cleanup_attempt",
    ]
    assert result.transcript == ""
    assert Path(result.txt_path).read_text(encoding="utf-8") == result.transcript
    assert result.funasr_json_data["segments"] == [
        {
            "start_time": 0.0,
            "end_time": 2.0,
            "text": "",
            "speaker": 0,
        }
    ]
    assert json.loads(result.generated_files[1].read_text(encoding="utf-8")) == (
        result.funasr_json_data
    )
    assert result.provider == "aliyun"
    assert result.model == "fun-asr-2025-11-07"
    assert result.remote_task_id_hash == sha256(b"private-task").hexdigest()
    assert "private-task" not in result.generated_files[1].read_text(encoding="utf-8")
    event = delegate.get_event(repository.last_event_id)
    assert event.reported_quantity == "2"
    assert event.calculated_cost == "0.00044"
    assert event.materialization_status == "succeeded"


def test_local_media_gate_fails_before_credentials_or_network(tmp_path):
    calls = {"credentials": 0, "client": 0}
    repository = UsageEventRepository(tmp_path / "usage.sqlite3")

    def load_credentials():
        calls["credentials"] += 1

    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=SimpleNamespace(),
        output_dir=tmp_path / "outputs",
        credential_loader=load_credentials,
        client_factory=lambda credentials: calls.__setitem__("client", 1),
        clock=lambda: NOW,
        **_attempt_dependencies(repository),
    )

    try:
        provider.transcribe(
            str(tmp_path / "missing.mp3"),
            "lesson",
            context=TranscriptionContext("task-1", "youtube", "video-1"),
        )
    except CloudProviderError as exc:
        assert exc.code == "prepared_media_required"
    else:
        raise AssertionError("prepared media gate must fail")

    assert calls == {"credentials": 0, "client": 0}
    assert provider.repository.list_recoverable_events() == []

    events: list[str] = []
    delegate = UsageEventRepository(tmp_path / "claimed.sqlite3")
    claimed_repository = _Repository(delegate, events)
    reserved_attempts = []

    def fail_credentials():
        calls["credentials"] += 1
        raise RuntimeError("SENTINEL_LOCAL_SECRET")

    claimed_provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=claimed_repository,
        snapshotter=_Snapshotter(tmp_path / "claimed-snapshot", events),
        output_dir=tmp_path / "outputs",
        credential_loader=fail_credentials,
        client_factory=lambda credentials: calls.__setitem__("client", 1),
        clock=lambda: NOW,
        **_attempt_dependencies(claimed_repository),
        capacity_transfer_callback=reserved_attempts.append,
    )
    with pytest.raises(CloudProviderError) as local_error:
        claimed_provider.transcribe(
            str(tmp_path / "source.mp3"),
            "lesson",
            context=TranscriptionContext(
                "task-claimed",
                "youtube",
                "video-2",
                prepared_media=_prepared_media(
                    tmp_path / "claimed-prepared", "task-claimed"
                ),
            ),
        )
    assert local_error.value.code == "local_preflight_failed"
    assert "SENTINEL" not in str(local_error.value)
    assert calls == {"credentials": 1, "client": 0}
    assert reserved_attempts[0].task_id == "task-claimed"
    assert "upload" not in events and "submit" not in events
    claimed = delegate.get_event(claimed_repository.last_event_id)
    assert (claimed.remote_status, claimed.error_code) == (
        "failed",
        "local_preflight_failed",
    )
    assert delegate.freeze_stale_submissions(
        now=NOW.replace(minute=2)
    ) == 0
    assert delegate.get_event(claimed.id).remote_status == "failed"


def test_media_change_after_upload_records_failure_and_never_submits(tmp_path):
    events: list[str] = []
    delegate = UsageEventRepository(tmp_path / "usage.sqlite3")
    repository = _Repository(delegate, events)

    class ChangedSnapshotter(_Snapshotter):
        def verify_unchanged(self, handle):
            self.events.append("verify_unchanged")
            raise SnapshotError("media_changed_before_submit")

    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=ChangedSnapshotter(tmp_path / "snapshots", events),
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: _Client(events),
        clock=lambda: NOW,
        **_attempt_dependencies(repository),
    )

    try:
        provider.transcribe(
            str(tmp_path / "source.mp3"),
            "lesson",
            context=TranscriptionContext(
                "task-1",
                "youtube",
                "video-1",
                prepared_media=_prepared_media(tmp_path / "changed", "task-1"),
            ),
        )
    except SnapshotError as exc:
        assert exc.code == "media_changed_before_submit"
    else:
        raise AssertionError("changed upload must fail")

    assert events.count("upload") == 1
    assert "submit" not in events
    event = delegate.get_event(repository.last_event_id)
    assert (event.remote_status, event.error_code) == (
        "failed",
        "media_changed_before_submit",
    )

    class ExpiredResultClient(_Client):
        def poll(self, task_id, *, poll_interval_seconds, timeout_seconds):
            self.events.append("poll_expired")
            raise AliyunASRError("result_expired", usage_seconds=3)

    expiry_provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=_Snapshotter(tmp_path / "expiry-snapshot", events),
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: ExpiredResultClient(events),
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        **_attempt_dependencies(repository),
    )
    with pytest.raises(CloudProviderError) as expired_error:
        expiry_provider.transcribe(
            str(tmp_path / "source.mp3"),
            "expired",
            context=TranscriptionContext(
                "task-expired",
                "youtube",
                "video-expired",
                prepared_media=_prepared_media(
                    tmp_path / "expired", "task-expired"
                ),
            ),
        )
    assert expired_error.value.code == "result_expired"
    expired_event = delegate.get_event(repository.last_event_id)
    assert expired_event.status == "remote_result_expired"
    assert (expired_event.reported_quantity, expired_event.calculated_cost) == (
        "3",
        "0.00066",
    )


def test_provider_terminal_failure_cleans_snapshot_and_notifies_once(tmp_path):
    events: list[str] = []
    delegate = UsageEventRepository(tmp_path / "usage.sqlite3")
    repository = _Repository(delegate, events)

    class FailedClient(_Client):
        def poll(self, task_id, *, poll_interval_seconds, timeout_seconds):
            raise AliyunASRError("provider_failed")

    state_changes = []
    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=_Snapshotter(tmp_path / "snapshots", events),
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: FailedClient(events),
        clock=lambda: NOW,
        **_attempt_dependencies(repository),
        attempt_state_callback=state_changes.append,
    )

    with pytest.raises(CloudProviderError, match="provider_failed"):
        provider.transcribe(
            str(tmp_path / "source.mp3"),
            "lesson",
            context=TranscriptionContext(
                "task-1",
                "youtube",
                "video-1",
                prepared_media=_prepared_media(tmp_path / "terminal", "task-1"),
            ),
        )

    assert events.count("cleanup_attempt") == 1
    assert state_changes == [repository.last_event_id]


@pytest.mark.parametrize(
    "failure_mode",
    ("timeout", "request_error", "persistence_failure"),
)
def test_submission_unknown_freezes_attempt_and_reentry_never_resubmits(
    tmp_path, failure_mode
):
    events: list[str] = []
    delegate = UsageEventRepository(tmp_path / "usage.sqlite3")
    repository = _Repository(
        delegate,
        events,
        persist_submitted=failure_mode != "persistence_failure",
    )
    snapshotter = _Snapshotter(tmp_path / "snapshots", events)

    class UnknownSubmitClient(_Client):
        def submit(self, staged_uri, language_hints):
            self.events.append("submit")
            if failure_mode == "timeout":
                raise PotentiallyAcceptedError("submission_unknown")
            if failure_mode == "request_error":
                raise AliyunASRError("request_error")
            return {"task_id": "private-task", "status": "PENDING"}

    client = UnknownSubmitClient(events)
    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=snapshotter,
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: client,
        clock=lambda: NOW,
        **_attempt_dependencies(repository),
    )
    context = TranscriptionContext(
        "task-1",
        "youtube",
        "video-1",
        prepared_media=_prepared_media(tmp_path / "unknown", "task-1"),
    )

    try:
        provider.transcribe(str(tmp_path / "source.mp3"), "lesson", context=context)
    except CloudProviderError as exc:
        assert exc.code == "submission_unknown"
    else:
        raise AssertionError("unknown submit must freeze")

    frozen = delegate.get_event(repository.last_event_id)
    assert (frozen.remote_status, frozen.materialization_status) == (
        "submission_unknown",
        "not_applicable",
    )
    try:
        provider.transcribe(str(tmp_path / "source.mp3"), "lesson", context=context)
    except CloudProviderError as exc:
        assert exc.code == "attempt_requires_recovery"
    else:
        raise AssertionError("frozen attempt must not be retried")
    assert events.count("submit") == 1


def test_real_artifact_write_failure_recovers_from_settled_same_task(
    tmp_path, monkeypatch
):
    events: list[str] = []
    delegate = UsageEventRepository(tmp_path / "usage.sqlite3")
    repository = _Repository(delegate, events)
    snapshotter = _Snapshotter(tmp_path / "snapshots", events)
    client = _Client(events)
    provider = AliyunFunASRProvider(
        settings=_settings(),
        repository=repository,
        snapshotter=snapshotter,
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: client,
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        **_attempt_dependencies(repository),
    )
    original_write = provider_module._atomic_write_text
    write_calls = 0

    def fail_first_write(path, content):
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            raise OSError("simulated disk failure")
        return original_write(path, content)

    monkeypatch.setattr(provider_module, "_atomic_write_text", fail_first_write)

    try:
        provider.transcribe(
            str(tmp_path / "source.mp3"),
            "lesson",
            context=TranscriptionContext(
                "task-1",
                "youtube",
                "video-1",
                prepared_media=_prepared_media(tmp_path / "artifact", "task-1"),
            ),
        )
    except CloudProviderError as exc:
        assert exc.code == "materialization_failed"
    else:
        raise AssertionError("write failure must be recoverable")

    failed = delegate.get_event(repository.last_event_id)
    assert failed.remote_status == "succeeded"
    assert failed.materialization_status == "failed"
    assert (failed.reported_quantity, failed.calculated_cost) == ("2", "0.00044")

    coordinator = CloudASRRecoveryCoordinator(
        repository=delegate,
        snapshotter=snapshotter,
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: client,
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
        poll_interval_seconds=1,
        poll_timeout_seconds=300,
    )
    recovered = coordinator.recover_pending()[0]

    assert recovered.transcript == "你好，世界。"
    assert events.count("submit") == 1
    assert events.count("poll") == 2
    final = delegate.get_event(repository.last_event_id)
    assert final.materialization_status == "succeeded"
    assert (final.reported_quantity, final.calculated_cost) == ("2", "0.00044")
