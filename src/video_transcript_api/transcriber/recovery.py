"""Lease-aware same-task recovery for Aliyun cloud transcription."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .aliyun_client import AliyunASRError, PollTimeoutError
from .contracts import TranscriptionResult
from .media_snapshot import MediaSnapshot
from .providers.aliyun_funasr import (
    CloudProviderError,
    LeaseHeartbeat,
    _cleanup_attempt_best_effort,
    _atomic_write_text,
    _normalize_terminal_result,
)


class CloudASRRecoveryCoordinator:
    """Resume only provider tasks already persisted in ``usage_events``."""

    def __init__(
        self,
        *,
        repository: Any,
        snapshotter: Any,
        output_dir: str | Path,
        credential_loader: Callable[[], Any],
        client_factory: Callable[[Any], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 1,
        poll_timeout_seconds: float = 300,
        heartbeat_interval_seconds: float = 20,
        result_callback: Callable[[TranscriptionResult, Any], None] | None = None,
        attempt_state_callback: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.repository = repository
        self.snapshotter = snapshotter
        self.output_dir = Path(output_dir)
        self.credential_loader = credential_loader
        self.client_factory = client_factory
        self.clock = clock
        self.monotonic = monotonic
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.result_callback = result_callback
        self.attempt_state_callback = attempt_state_callback
        self._stop_event = stop_event or threading.Event()

    def stop(self) -> None:
        """Ask in-flight recovery to stop at the next request/wait boundary."""
        self._stop_event.set()

    def recover_pending(self) -> list[TranscriptionResult]:
        """Claim and recover each eligible row without ever submitting anew."""
        self.repository.freeze_stale_submissions(now=self.clock())
        events = self.repository.list_recoverable_events()
        if not events:
            return []

        recovered: list[TranscriptionResult] = []
        credentials: Any | None = None
        client: Any | None = None
        for event in events:
            if self._stop_event.is_set():
                break
            lease_owner = uuid4().hex
            if not self.repository.claim_recovery(
                event.id, lease_owner, now=self.clock()
            ):
                continue
            if self._stop_event.is_set():
                self._mark_stopped_pending(event, lease_owner)
                break
            if credentials is None:
                credentials = self.credential_loader()
                client = self.client_factory(credentials)
                self._attach_stop_event(client)
            result = self._recover_claimed(event, lease_owner, client)
            if result is not None:
                recovered.append(result)
        return recovered

    def recover_event(self, event_id: str) -> TranscriptionResult | None:
        """Recover one re-entered LearnFlux task without scanning or submitting."""
        if self._stop_event.is_set():
            return None
        event = self.repository.get_recovery_event(event_id)
        if not (
            event.remote_status in {"submitted", "polling_unknown"}
            or (
                event.remote_status == "succeeded"
                and event.materialization_status in {"pending", "failed"}
            )
        ):
            return None
        lease_owner = uuid4().hex
        if not self.repository.claim_recovery(
            event.id, lease_owner, now=self.clock()
        ):
            return None
        if self._stop_event.is_set():
            self._mark_stopped_pending(event, lease_owner)
            return None
        try:
            credentials = self.credential_loader()
            client = self.client_factory(credentials)
            self._attach_stop_event(client)
        except Exception:
            return None
        return self._recover_claimed(event, lease_owner, client)

    def _attach_stop_event(self, client: Any) -> None:
        setter = getattr(client, "set_stop_event", None)
        if callable(setter):
            setter(self._stop_event)

    def _mark_stopped_pending(self, event: Any, lease_owner: str) -> None:
        if event.remote_status == "succeeded":
            self.repository.record_materialization_failed(
                event.id,
                lease_owner,
                now=self.clock(),
                error_code="materialization_failed",
            )
            self._notify_attempt_state(event.id)
            return
        self.repository.mark_polling_unknown(
            event.id,
            lease_owner,
            now=self.clock(),
            error_code="polling_timeout",
        )
        self._notify_attempt_state(event.id)

    def _recover_claimed(
        self, event: Any, lease_owner: str, client: Any
    ) -> TranscriptionResult | None:
        if self._stop_event.is_set():
            self._mark_stopped_pending(event, lease_owner)
            return None
        task_id = event.provider_task_id
        if not isinstance(task_id, str) or not task_id:
            return None
        heartbeat = LeaseHeartbeat(
            self.repository,
            event.id,
            lease_owner,
            clock=self.clock,
            interval_seconds=self.heartbeat_interval_seconds,
        )
        heartbeat.start()
        started_at = self.monotonic()
        try:
            heartbeat.ensure_owned()
            try:
                terminal = client.poll(
                    task_id,
                    poll_interval_seconds=self.poll_interval_seconds,
                    timeout_seconds=self.poll_timeout_seconds,
                )
            except PollTimeoutError:
                if event.remote_status == "succeeded":
                    updated = self.repository.record_materialization_failed(
                        event.id,
                        lease_owner,
                        now=self.clock(),
                        error_code="materialization_failed",
                    )
                else:
                    updated = self.repository.mark_polling_unknown(
                        event.id,
                        lease_owner,
                        now=self.clock(),
                        error_code="polling_timeout",
                    )
                if not updated:
                    raise CloudProviderError("lease_lost") from None
                self._notify_attempt_state(event.id)
                return None
            except AliyunASRError as exc:
                if exc.code == "result_expired":
                    if (
                        event.remote_status != "succeeded"
                        and exc.usage_seconds is not None
                    ):
                        elapsed = max(
                            Decimal("0"),
                            Decimal(str(self.monotonic() - started_at)),
                        )
                        if not self.repository.record_remote_success(
                            event.id,
                            lease_owner,
                            now=self.clock(),
                            reported_quantity=Decimal(
                                str(exc.usage_seconds)
                            ),
                            elapsed_seconds=elapsed,
                        ):
                            raise CloudProviderError("lease_lost") from None
                    if not self.repository.mark_result_expired(
                        event.id, lease_owner, now=self.clock()
                    ):
                        raise CloudProviderError("lease_lost") from None
                    self._cleanup_event_attempt(event)
                    self._notify_attempt_state(event.id)
                elif exc.code == "provider_failed":
                    self.repository.record_remote_failure(
                        event.id,
                        lease_owner,
                        now=self.clock(),
                        error_code="provider_failed",
                    )
                    self._cleanup_event_attempt(event)
                    self._notify_attempt_state(event.id)
                elif event.remote_status == "succeeded":
                    self.repository.record_materialization_failed(
                        event.id,
                        lease_owner,
                        now=self.clock(),
                        error_code="materialization_failed",
                    )
                    self._notify_attempt_state(event.id)
                else:
                    if not self.repository.mark_polling_unknown(
                        event.id,
                        lease_owner,
                        now=self.clock(),
                        error_code="polling_timeout",
                    ):
                        raise CloudProviderError("lease_lost") from None
                    self._notify_attempt_state(event.id)
                return None

            heartbeat.ensure_owned()
            if self._stop_event.is_set():
                self._mark_stopped_pending(event, lease_owner)
                return None
            normalized = _normalize_terminal_result(terminal)
            elapsed = max(
                Decimal("0"), Decimal(str(self.monotonic() - started_at))
            )
            if event.remote_status != "succeeded":
                if not self.repository.record_remote_success(
                    event.id,
                    lease_owner,
                    now=self.clock(),
                    reported_quantity=normalized["usage_seconds"],
                    elapsed_seconds=elapsed,
                ):
                    raise CloudProviderError("lease_lost")
            elif event.elapsed_seconds is not None:
                elapsed = Decimal(event.elapsed_seconds)

            snapshot = self._snapshot_for(event)
            try:
                result = self._materialize(
                    event=event,
                    snapshot=snapshot,
                    normalized=normalized,
                    elapsed=elapsed,
                    task_id=task_id,
                )
            except Exception:
                self.repository.record_materialization_failed(
                    event.id,
                    lease_owner,
                    now=self.clock(),
                    error_code="materialization_failed",
                )
                self._notify_attempt_state(event.id)
                return None
            if not self.repository.record_materialization_succeeded(
                event.id, lease_owner, now=self.clock()
            ):
                raise CloudProviderError("lease_lost")
            _cleanup_attempt_best_effort(self.snapshotter, snapshot)
            self._notify_attempt_state(event.id)
            if (
                self.result_callback is not None
                and not self._stop_event.is_set()
            ):
                try:
                    self.result_callback(result, event)
                except Exception:
                    # The durable postprocess row remains pending for a scanner.
                    pass
            return result
        finally:
            heartbeat.stop()

    def _cleanup_event_attempt(self, event: Any) -> None:
        try:
            snapshot = self._snapshot_for(event)
        except Exception:
            return
        _cleanup_attempt_best_effort(self.snapshotter, snapshot)

    def _notify_attempt_state(self, event_id: str) -> None:
        if self.attempt_state_callback is None:
            return
        try:
            self.attempt_state_callback(event_id)
        except Exception:
            pass

    def _snapshot_for(self, event: Any) -> MediaSnapshot:
        return self.snapshotter.find_attempt(
            task_id=event.task_id,
            attempt_no=event.attempt_no,
            expected_sha256=event.sample_sha256,
            duration_seconds=Decimal(event.estimated_quantity),
        )

    def _materialize(
        self,
        *,
        event: Any,
        snapshot: MediaSnapshot,
        normalized: Mapping[str, Any],
        elapsed: Decimal,
        task_id: str,
    ) -> TranscriptionResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        txt_path = self.output_dir / f"{event.output_name}.txt"
        json_path = self.output_dir / f"{event.output_name}_funasr.json"
        payload = {
            "task_id": "",
            "file_name": snapshot.path.name,
            "duration": float(snapshot.duration_seconds),
            "segments": normalized["segments"],
            "created_at": self.clock().isoformat(),
            "processing_time": float(elapsed),
            "error": None,
        }
        _atomic_write_text(txt_path, normalized["text"])
        _atomic_write_text(
            json_path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        return TranscriptionResult(
            transcript=normalized["text"],
            txt_path=str(txt_path),
            funasr_json_data=payload,
            generated_files=(txt_path, json_path),
            provider="aliyun",
            model=event.model,
            elapsed_seconds=float(elapsed),
            audio_seconds=float(snapshot.duration_seconds),
            usage_seconds=float(normalized["usage_seconds"]),
            estimated_cost=Decimal(event.estimated_cost),
            currency="CNY",
            remote_status="succeeded",
            remote_task_id_hash=hashlib.sha256(task_id.encode()).hexdigest(),
            usage_event_id=event.id,
        )
