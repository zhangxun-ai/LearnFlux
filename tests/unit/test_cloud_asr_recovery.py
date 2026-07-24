from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Lock

from video_transcript_api.transcriber.aliyun_client import (
    AliyunASRError,
    AliyunCredentials,
)
from video_transcript_api.transcriber.providers.aliyun_funasr import LeaseHeartbeat
from video_transcript_api.transcriber.media_snapshot import MediaSnapshotter
from video_transcript_api.transcriber.recovery import CloudASRRecoveryCoordinator
from video_transcript_api.transcriber.usage_repository import (
    NewASRAttempt,
    UsageEventRepository,
)


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
RECOVERY_MEDIA = b"recovery-media"


def _attempt(task_id="task-1"):
    return NewASRAttempt(
        task_id=task_id,
        model="fun-asr-2025-11-07",
        estimated_quantity=Decimal("2.1"),
        unit_price=Decimal("0.00022"),
        estimated_cost=Decimal("0.00066"),
        owner_key="",
        sample_sha256=hashlib.sha256(RECOVERY_MEDIA).hexdigest(),
        platform="youtube",
        media_id="video-1",
        output_name="lesson",
    )


def _terminal(task_id):
    return {
        "task_id": task_id,
        "status": "SUCCEEDED",
        "usage_seconds": 2,
        "results": [
            {
                "status": "SUCCEEDED",
                "transcript": {
                    "text": "Recovered text",
                    "sentences": [
                        {
                            "text": "Recovered text",
                            "start_time": 0.0,
                            "end_time": 2.0,
                        }
                    ],
                },
            }
        ],
    }


class _RecoveryClient:
    def __init__(self, poll_error=None):
        self.polled = []
        self.submits = 0
        self.poll_error = poll_error

    def submit(self, *args, **kwargs):
        self.submits += 1
        raise AssertionError("recovery must never submit")

    def poll(self, task_id, *, poll_interval_seconds, timeout_seconds):
        self.polled.append(task_id)
        if self.poll_error is not None:
            raise self.poll_error
        return _terminal(task_id)


class _RecoverySnapshotter:
    def __init__(self, temp_root: Path):
        self.temp_root = temp_root
        self.cleaned = []
        self.find_calls = []

    def find_attempt(
        self,
        *,
        task_id,
        attempt_no,
        expected_sha256,
        duration_seconds,
    ):
        self.find_calls.append((task_id, attempt_no, expected_sha256))
        task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        attempt_dir = self.temp_root / "remote_asr" / task_hash / str(attempt_no)
        attempt_dir.mkdir(parents=True, mode=0o700)
        (attempt_dir / "input.m4a").write_bytes(RECOVERY_MEDIA)
        return MediaSnapshotter(self.temp_root).find_attempt(
            task_id=task_id,
            attempt_no=attempt_no,
            expected_sha256=expected_sha256,
            duration_seconds=duration_seconds,
        )

    def cleanup_attempt(self, snapshot):
        self.cleaned.append(snapshot.attempt_no)


def _coordinator(
    tmp_path,
    repository,
    client,
    credentials_calls,
    now,
    result_callback=None,
    attempt_state_callback=None,
):
    return CloudASRRecoveryCoordinator(
        repository=repository,
        snapshotter=_RecoverySnapshotter(tmp_path / "snapshots"),
        output_dir=tmp_path / "outputs",
        credential_loader=lambda: credentials_calls.append("credentials")
        or AliyunCredentials("k", "w", "host"),
        client_factory=lambda credentials: client,
        clock=lambda: now,
        monotonic=lambda: 10.0,
        poll_interval_seconds=1,
        poll_timeout_seconds=300,
        result_callback=result_callback,
        attempt_state_callback=attempt_state_callback,
    )


def test_empty_recovery_scan_does_not_read_credentials(tmp_path):
    repository = UsageEventRepository(tmp_path / "usage.sqlite3")
    stale = repository.reserve_attempt(_attempt())
    assert repository.claim_submission(stale.id, "crashed", now=NOW)
    credentials_calls = []
    coordinator = _coordinator(
        tmp_path,
        repository,
        _RecoveryClient(),
        credentials_calls,
        NOW + timedelta(seconds=61),
    )

    assert coordinator.recover_pending() == []
    assert credentials_calls == []
    assert repository.get_event(stale.id).remote_status == "submission_unknown"


def test_polling_unknown_recovers_only_the_persisted_task(tmp_path):
    repository = UsageEventRepository(tmp_path / "usage.sqlite3")
    event = repository.reserve_attempt(_attempt())
    assert repository.claim_submission(event.id, "worker-1", now=NOW)
    assert repository.record_submitted(
        event.id,
        "worker-1",
        now=NOW + timedelta(seconds=1),
        provider_task_id="private-task",
    )
    assert repository.mark_polling_unknown(
        event.id,
        "worker-1",
        now=NOW + timedelta(seconds=2),
        error_code="polling_timeout",
    )
    uncertain_client = _RecoveryClient(AliyunASRError("request_error"))
    credentials_calls = []
    uncertain_coordinator = _coordinator(
        tmp_path,
        repository,
        uncertain_client,
        credentials_calls,
        NOW + timedelta(seconds=3),
    )
    assert uncertain_coordinator.recover_pending() == []
    uncertain = repository.get_event(event.id)
    assert (uncertain.remote_status, uncertain.error_code) == (
        "polling_unknown",
        "polling_timeout",
    )
    assert uncertain_client.polled == ["private-task"]

    client = _RecoveryClient()
    callbacks = []
    order = []
    coordinator = _coordinator(
        tmp_path,
        repository,
        client,
        credentials_calls,
        NOW + timedelta(seconds=4),
        result_callback=lambda result, event: (
            order.append("post_asr"),
            callbacks.append((result.transcript, event.id)),
        ),
        attempt_state_callback=lambda event_id: order.append(
            repository.get_event(event_id).status
        ),
    )

    results = coordinator.recover_pending()

    assert [result.transcript for result in results] == ["Recovered text"]
    assert client.polled == ["private-task"]
    assert client.submits == 0
    assert callbacks == [("Recovered text", event.id)]
    assert order == ["succeeded", "post_asr"]
    assert credentials_calls == ["credentials", "credentials"]
    final = repository.get_event(event.id)
    assert (final.remote_status, final.materialization_status) == (
        "succeeded",
        "succeeded",
    )
    assert final.reported_quantity == "2"


def test_settled_materialization_failure_reuses_same_result_without_resubmit(tmp_path):
    repository = UsageEventRepository(tmp_path / "usage.sqlite3")
    event = repository.reserve_attempt(_attempt())
    assert repository.claim_submission(event.id, "worker-1", now=NOW)
    assert repository.record_submitted(
        event.id,
        "worker-1",
        now=NOW + timedelta(seconds=1),
        provider_task_id="private-task",
    )
    assert repository.record_remote_success(
        event.id,
        "worker-1",
        now=NOW + timedelta(seconds=2),
        reported_quantity=Decimal("2"),
        elapsed_seconds=Decimal("7"),
    )
    assert repository.record_materialization_failed(
        event.id,
        "worker-1",
        now=NOW + timedelta(seconds=3),
        error_code="materialization_failed",
    )
    client = _RecoveryClient()
    coordinator = _coordinator(
        tmp_path,
        repository,
        client,
        [],
        NOW + timedelta(seconds=4),
    )

    result = coordinator.recover_pending()[0]

    assert result.transcript == "Recovered text"
    assert client.polled == ["private-task"]
    assert client.submits == 0
    final = repository.get_event(event.id)
    assert final.reported_quantity == "2"
    assert final.calculated_cost == "0.00044"
    assert final.materialization_status == "succeeded"

    expired = repository.reserve_attempt(_attempt(task_id="task-expired"))
    assert repository.claim_submission(
        expired.id, "worker-2", now=NOW + timedelta(seconds=5)
    )
    assert repository.record_submitted(
        expired.id,
        "worker-2",
        now=NOW + timedelta(seconds=6),
        provider_task_id="expired-private-task",
    )
    expiry_client = _RecoveryClient(
        AliyunASRError("result_expired", usage_seconds=3)
    )
    expiry_coordinator = _coordinator(
        tmp_path,
        repository,
        expiry_client,
        [],
        NOW + timedelta(seconds=66),
    )

    assert expiry_coordinator.recover_pending() == []
    expired_final = repository.get_event(expired.id)
    assert expired_final.status == "remote_result_expired"
    assert expired_final.reported_quantity == "3"
    assert expired_final.calculated_cost == "0.00066"
    assert repository.list_recoverable_events() == []


def test_heartbeat_with_controlled_clock_prevents_concurrent_takeover(tmp_path):
    repository = UsageEventRepository(tmp_path / "usage.sqlite3")
    event = repository.reserve_attempt(_attempt())
    assert repository.claim_submission(event.id, "submitter", now=NOW)
    assert repository.record_submitted(
        event.id,
        "submitter",
        now=NOW + timedelta(seconds=1),
        provider_task_id="private-task",
    )
    clock_value = [NOW + timedelta(seconds=61)]
    clock_lock = Lock()
    heartbeat_seen = Event()

    class SignalingRepository:
        def heartbeat_lease(self, event_id, owner, *, now):
            result = repository.heartbeat_lease(event_id, owner, now=now)
            if now == NOW + timedelta(seconds=100):
                heartbeat_seen.set()
            return result

    assert repository.claim_recovery(
        event.id, "recoverer-1", now=clock_value[0]
    )

    def clock():
        with clock_lock:
            return clock_value[0]

    heartbeat = LeaseHeartbeat(
        SignalingRepository(),
        event.id,
        "recoverer-1",
        clock=clock,
        interval_seconds=0.001,
    )
    heartbeat.start()
    with clock_lock:
        clock_value[0] = NOW + timedelta(seconds=100)
    assert heartbeat_seen.wait(1)

    assert not repository.claim_recovery(
        event.id, "recoverer-2", now=NOW + timedelta(seconds=130)
    )
    heartbeat.stop()
