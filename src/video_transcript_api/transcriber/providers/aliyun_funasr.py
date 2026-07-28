"""Fail-closed orchestration for one Aliyun Fun-ASR attempt."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from ..aliyun_client import (
    AliyunASRError,
    PollTimeoutError,
)
from ..cloud_config import NewCloudSubmissionSettings
from ..contracts import TranscriptionContext, TranscriptionResult
from ..media_preparer import PreparedASRMedia
from ..media_snapshot import SnapshotError
from ..usage_repository import NewASRAttempt, UsageEvent
from ...utils.logging import setup_logger


logger = setup_logger("transcriber")


class CloudProviderError(RuntimeError):
    """A cloud orchestration error containing only a stable safe code."""

    def __init__(
        self,
        code: str,
        *,
        provider_error_code: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        self.code = code
        self.provider_error_code = provider_error_code
        self.provider_request_id = provider_request_id
        super().__init__(code)


class LeaseHeartbeat:
    """Maintain one repository lease while blocking remote work is in flight."""

    def __init__(
        self,
        repository: Any,
        event_id: str,
        lease_owner: str,
        *,
        clock: Callable[[], datetime],
        interval_seconds: float = 20,
    ) -> None:
        self._repository = repository
        self._event_id = event_id
        self._lease_owner = lease_owner
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lost = threading.Event()
        self._refresh_lock = threading.Lock()
        self._last_refresh_at: datetime | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="aliyun-asr-lease-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if not self._refresh_or_reclaim():
                    self._lost.set()
                    return
                self._ready.set()
                if self._stop.wait(self._interval_seconds):
                    return
        except Exception as exc:
            logger.warning(
                "Cloud ASR lease heartbeat failed: {}",
                type(exc).__name__,
            )
            self._lost.set()
        finally:
            self._ready.set()

    def _refresh_or_reclaim(self) -> bool:
        with self._refresh_lock:
            now = self._clock()
            refreshed = self._repository.heartbeat_lease(
                self._event_id,
                self._lease_owner,
                now=now,
            )
            if not refreshed:
                reclaim = getattr(self._repository, "reclaim_lease", None)
                refreshed = bool(
                    callable(reclaim)
                    and reclaim(
                        self._event_id,
                        self._lease_owner,
                        now=now,
                    )
                )
            if refreshed:
                self._last_refresh_at = now
            return refreshed

    def ensure_owned(self) -> None:
        if self._lost.is_set():
            raise CloudProviderError("lease_lost")
        now = self._clock()
        last_refresh = self._last_refresh_at
        if (
            last_refresh is None
            or (now - last_refresh).total_seconds() >= self._interval_seconds
        ):
            if not self._refresh_or_reclaim():
                self._lost.set()
                raise CloudProviderError("lease_lost")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()


class AliyunFunASRProvider:
    """Coordinate local gates, one paid task, settlement, and artifacts."""

    name = "aliyun"

    def __init__(
        self,
        *,
        settings: NewCloudSubmissionSettings,
        repository: Any,
        snapshotter: Any,
        output_dir: str | Path,
        credential_loader: Callable[[], Any],
        client_factory: Callable[[Any], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        heartbeat_interval_seconds: float = 20,
        attempt_reserver: Callable[[NewASRAttempt], UsageEvent],
        prepared_media_cleanup: Callable[[PreparedASRMedia], None],
        submission_guard: Any | None = None,
        capacity_transfer_callback: Callable[[UsageEvent], None] | None = None,
        attempt_state_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.snapshotter = snapshotter
        self.output_dir = Path(output_dir)
        self.credential_loader = credential_loader
        self.client_factory = client_factory
        self.clock = clock
        self.monotonic = monotonic
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.attempt_reserver = attempt_reserver
        self.prepared_media_cleanup = prepared_media_cleanup
        self.submission_guard = submission_guard
        self.capacity_transfer_callback = capacity_transfer_callback
        self.attempt_state_callback = attempt_state_callback

    def transcribe(
        self,
        audio_path: str,
        output_base: str,
        *,
        context: TranscriptionContext | None = None,
    ) -> TranscriptionResult:
        """Submit exactly once after all local media and budget gates pass."""
        if context is None:
            raise CloudProviderError("context_required")
        prepared = context.prepared_media
        if not isinstance(prepared, PreparedASRMedia):
            raise CloudProviderError("prepared_media_required")
        del audio_path

        accepted_max_cost = context.accepted_max_cost
        if accepted_max_cost is None:
            accepted_max_cost = self.settings.accepted_max_cost
        estimated_cost = self.settings.estimated_cost(prepared.duration_seconds)
        if accepted_max_cost is None:
            estimated_cost = self.settings.reserve_estimate(
                prepared.duration_seconds
            )
        if (
            accepted_max_cost is not None
            and estimated_cost > accepted_max_cost
        ):
            raise CloudProviderError("cloud_quote_changed")
        event = self.attempt_reserver(
            NewASRAttempt(
                task_id=context.task_id,
                model=self.settings.model,
                estimated_quantity=prepared.duration_seconds,
                unit_price=self.settings.price_cny_per_second,
                estimated_cost=estimated_cost,
                owner_key=context.owner_key or "",
                sample_sha256=prepared.sha256,
                platform=context.platform,
                media_id=context.media_id,
                output_name=output_base,
                continuation_json=context.continuation_json,
            )
        )

        create_snapshot = event.remote_status == "reserved"
        try:
            snapshot = self.snapshotter.promote(
                prepared,
                task_id=context.task_id,
                attempt_no=event.attempt_no,
                expected_sha256=event.sample_sha256,
                create=create_snapshot,
            )
        except Exception:
            self._notify_attempt_state(event.id)
            raise
        try:
            self.prepared_media_cleanup(prepared)
        except Exception:
            logger.warning("prepared_media_cleanup_failed")
        if self.capacity_transfer_callback is not None:
            try:
                self.capacity_transfer_callback(event)
            except Exception:
                self._notify_attempt_state(event.id)
                raise
        if not create_snapshot:
            from ..recovery import CloudASRRecoveryCoordinator

            recovery = CloudASRRecoveryCoordinator(
                repository=self.repository,
                snapshotter=self.snapshotter,
                output_dir=self.output_dir,
                credential_loader=self.credential_loader,
                client_factory=self.client_factory,
                clock=self.clock,
                monotonic=self.monotonic,
                poll_interval_seconds=self.settings.poll_interval_seconds,
                poll_timeout_seconds=self.settings.poll_timeout_seconds,
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                attempt_state_callback=self.attempt_state_callback,
            )
            result = recovery.recover_event(event.id)
            if result is not None:
                return result
            current = self.repository.get_event(event.id)
            if current.remote_status in {"submitted", "polling_unknown"}:
                raise CloudProviderError("polling_unknown")
            raise CloudProviderError("attempt_requires_recovery")

        return self.submit_reserved_event(event, snapshot)

    def submit_reserved_event(
        self, event: UsageEvent, snapshot: Any
    ) -> TranscriptionResult:
        """Claim and submit one already-reserved durable attempt."""
        if event.remote_status != "reserved":
            raise CloudProviderError("attempt_requires_recovery")

        lease_owner = uuid4().hex
        now = self.clock()
        if not self.repository.claim_submission(event.id, lease_owner, now=now):
            self._notify_attempt_state(event.id)
            raise CloudProviderError("attempt_in_progress")

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
                credentials = self.credential_loader()
                client = self.client_factory(credentials)
            except Exception:
                self._record_failure(
                    event.id, lease_owner, "local_preflight_failed"
                )
                raise CloudProviderError("local_preflight_failed") from None
            heartbeat.ensure_owned()
            try:
                guard = (
                    self.submission_guard.hold()
                    if self.submission_guard is not None
                    else nullcontext()
                )
                with guard, self.snapshotter.open_for_upload(snapshot) as upload_handle:
                    try:
                        staged_uri = client.upload_audio(
                            upload_handle.file, snapshot.path.name
                        )
                    except AliyunASRError:
                        heartbeat.ensure_owned()
                        self._record_failure(
                            event.id, lease_owner, "upload_failed"
                        )
                        raise CloudProviderError("upload_failed") from None
                    self.snapshotter.verify_unchanged(upload_handle)

                    heartbeat.ensure_owned()
                    try:
                        submission = client.submit(staged_uri, ["zh", "en"])
                        if not isinstance(submission, Mapping):
                            raise CloudProviderError("invalid_response")
                        task_id = submission.get("task_id")
                        if not isinstance(task_id, str) or not task_id:
                            raise CloudProviderError("invalid_response")
                        if not self.repository.record_submitted(
                            event.id,
                            lease_owner,
                            now=self.clock(),
                            provider_task_id=task_id,
                        ):
                            raise CloudProviderError(
                                "task_id_persistence_failed"
                            )
                    except Exception:
                        self.repository.freeze_claimed_submission_unknown(
                            event.id,
                            lease_owner,
                            now=self.clock(),
                            error_code="submission_timeout",
                        )
                        raise CloudProviderError(
                            "submission_unknown"
                        ) from None
            except SnapshotError:
                self._record_failure(
                    event.id,
                    lease_owner,
                    "media_changed_before_submit",
                )
                raise
            except CloudProviderError:
                raise
            except Exception:
                self._record_failure(
                    event.id, lease_owner, "local_preflight_failed"
                )
                raise CloudProviderError("local_preflight_failed") from None

            heartbeat.ensure_owned()
            terminal = self._poll(
                client,
                event.id,
                lease_owner,
                task_id,
                heartbeat,
                started_at,
            )
            result = self._settle_and_materialize(
                event=event,
                lease_owner=lease_owner,
                snapshot=snapshot,
                terminal=terminal,
                output_base=event.output_name,
                started_at=started_at,
                task_id=task_id,
            )
            return result
        finally:
            heartbeat.stop()
            self._finalize_attempt(event.id, snapshot)

    def _poll(
        self,
        client: Any,
        event_id: str,
        lease_owner: str,
        task_id: str,
        heartbeat: LeaseHeartbeat,
        started_at: float,
    ) -> Mapping[str, Any]:
        heartbeat.ensure_owned()
        try:
            return client.poll(
                task_id,
                poll_interval_seconds=self.settings.poll_interval_seconds,
                timeout_seconds=self.settings.poll_timeout_seconds,
            )
        except PollTimeoutError:
            if not self.repository.mark_polling_unknown(
                event_id,
                lease_owner,
                now=self.clock(),
                error_code="polling_timeout",
            ):
                raise CloudProviderError("lease_lost") from None
            raise CloudProviderError("polling_unknown") from None
        except AliyunASRError as exc:
            if exc.code == "result_expired":
                if exc.usage_seconds is not None:
                    elapsed = max(
                        Decimal("0"),
                        Decimal(str(self.monotonic() - started_at)),
                    )
                    if not self.repository.record_remote_success(
                        event_id,
                        lease_owner,
                        now=self.clock(),
                        reported_quantity=Decimal(str(exc.usage_seconds)),
                        elapsed_seconds=elapsed,
                    ):
                        raise CloudProviderError("lease_lost") from None
                if not self.repository.mark_result_expired(
                    event_id, lease_owner, now=self.clock()
                ):
                    raise CloudProviderError("lease_lost") from None
                raise CloudProviderError("result_expired") from None
            if exc.code == "provider_failed":
                self._record_failure(
                    event_id,
                    lease_owner,
                    "provider_failed",
                    provider_error_code=exc.provider_error_code,
                    provider_request_id=exc.provider_request_id,
                )
                raise CloudProviderError(
                    "provider_failed",
                    provider_error_code=exc.provider_error_code,
                    provider_request_id=exc.provider_request_id,
                ) from None
            if not self.repository.mark_polling_unknown(
                event_id,
                lease_owner,
                now=self.clock(),
                error_code="polling_timeout",
            ):
                raise CloudProviderError("lease_lost") from None
            raise CloudProviderError("polling_unknown") from None

    def _settle_and_materialize(
        self,
        *,
        event: Any,
        lease_owner: str,
        snapshot: Any,
        terminal: Mapping[str, Any],
        output_base: str,
        started_at: float,
        task_id: str,
    ) -> TranscriptionResult:
        normalized = _normalize_terminal_result(terminal)
        elapsed = max(Decimal("0"), Decimal(str(self.monotonic() - started_at)))
        if not self.repository.record_remote_success(
            event.id,
            lease_owner,
            now=self.clock(),
            reported_quantity=normalized["usage_seconds"],
            elapsed_seconds=elapsed,
        ):
            raise CloudProviderError("lease_lost")

        try:
            result = self._materialize(
                output_base=output_base,
                snapshot=snapshot,
                normalized=normalized,
                elapsed=elapsed,
                estimated_cost=Decimal(event.estimated_cost),
                task_id=task_id,
                event_id=event.id,
            )
        except Exception:
            self.repository.record_materialization_failed(
                event.id,
                lease_owner,
                now=self.clock(),
                error_code="materialization_failed",
            )
            raise CloudProviderError("materialization_failed") from None
        if not self.repository.record_materialization_succeeded(
            event.id, lease_owner, now=self.clock()
        ):
            raise CloudProviderError("lease_lost")
        return result

    def _materialize(
        self,
        *,
        output_base: str,
        snapshot: Any,
        normalized: Mapping[str, Any],
        elapsed: Decimal,
        estimated_cost: Decimal,
        task_id: str,
        event_id: str,
    ) -> TranscriptionResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        txt_path = self.output_dir / f"{output_base}.txt"
        json_path = self.output_dir / f"{output_base}_funasr.json"
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
            provider=self.name,
            model=self.settings.model,
            elapsed_seconds=float(elapsed),
            audio_seconds=float(snapshot.duration_seconds),
            usage_seconds=float(normalized["usage_seconds"]),
            estimated_cost=estimated_cost,
            currency="CNY",
            remote_status="succeeded",
            remote_task_id_hash=hashlib.sha256(task_id.encode()).hexdigest(),
            usage_event_id=event_id,
        )

    def _record_failure(
        self,
        event_id: str,
        lease_owner: str,
        error_code: str,
        *,
        provider_error_code: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        self.repository.record_remote_failure(
            event_id,
            lease_owner,
            now=self.clock(),
            error_code=error_code,
            provider_error_code=provider_error_code,
            provider_request_id=provider_request_id,
        )

    def _finalize_attempt(self, event_id: str, snapshot: Any) -> None:
        try:
            event = self.repository.get_event(event_id)
            if event.remote_status in {"failed", "result_expired"} or (
                event.remote_status == "succeeded"
                and event.materialization_status == "succeeded"
            ):
                _cleanup_attempt_best_effort(self.snapshotter, snapshot)
        finally:
            self._notify_attempt_state(event_id)

    def _notify_attempt_state(self, event_id: str) -> None:
        if self.attempt_state_callback is None:
            return
        try:
            self.attempt_state_callback(event_id)
        except Exception:
            pass


def _normalize_terminal_result(terminal: Mapping[str, Any]) -> dict[str, Any]:
    usage = terminal.get("usage_seconds")
    if isinstance(usage, bool) or not isinstance(usage, (int, float)):
        raise CloudProviderError("invalid_response")
    usage_seconds = Decimal(str(usage))
    if not usage_seconds.is_finite() or usage_seconds < 0:
        raise CloudProviderError("invalid_response")
    results = terminal.get("results")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise CloudProviderError("invalid_response")
    texts: list[str] = []
    segments: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, Mapping) or result.get("status") != "SUCCEEDED":
            continue
        transcript = result.get("transcript")
        if not isinstance(transcript, Mapping):
            raise CloudProviderError("invalid_response")
        text = transcript.get("text")
        if not isinstance(text, str):
            raise CloudProviderError("invalid_response")
        texts.append(text)
        sentences = transcript.get("sentences", [])
        if not isinstance(sentences, Sequence) or isinstance(sentences, (str, bytes)):
            raise CloudProviderError("invalid_response")
        for sentence in sentences:
            if not isinstance(sentence, Mapping):
                raise CloudProviderError("invalid_response")
            segment = {
                field: sentence[field]
                for field in ("start_time", "end_time", "text", "speaker")
                if field in sentence
            }
            segments.append(segment)
    if not texts:
        raise CloudProviderError("invalid_response")
    return {
        "text": "\n".join(texts),
        "segments": segments,
        "usage_seconds": usage_seconds,
    }


def _cleanup_attempt_best_effort(snapshotter: Any, snapshot: Any) -> None:
    """Clean one private snapshot without changing an already-successful result."""
    try:
        snapshotter.cleanup_attempt(snapshot)
    except Exception:
        pass


def _atomic_write_text(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
