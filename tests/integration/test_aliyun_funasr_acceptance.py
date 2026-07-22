"""Opt-in, budget-locked acceptance for the production Aliyun provider.

The default mode is an offline dry-run.  Network-capable modes require an
explicit paid-execution flag and reuse state kept below the ignored test cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import pytest
from loguru import logger

from video_transcript_api.transcriber.aliyun_client import (
    AliyunASRClient,
    AliyunCredentials,
)
from video_transcript_api.transcriber.cloud_config import (
    MODEL,
    NewCloudSubmissionSettings,
)
from video_transcript_api.transcriber.contracts import TranscriptionContext
from video_transcript_api.transcriber.media_preparer import ASRMediaPreparer
from video_transcript_api.transcriber.media_snapshot import MediaSnapshotter
from video_transcript_api.transcriber.providers.aliyun_funasr import (
    AliyunFunASRProvider,
    CloudProviderError,
)
from video_transcript_api.transcriber.recovery import (
    CloudASRRecoveryCoordinator,
)
from video_transcript_api.transcriber.usage_repository import (
    NewASRAttempt,
    UsageEventRepository,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "cache" / "remote_asr_benchmark"
MANIFEST_PATH = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "remote_asr_benchmark" / "manifest.json"
)
RUN_ROOT = FIXTURE_ROOT / "aliyun_funasr_acceptance"
PRICE = Decimal("0.00022")
PRICE_VERIFIED_AT = "2026-07-21"


@dataclass(frozen=True)
class PinnedSample:
    sample_id: str
    filename: str
    sha256: str
    size_bytes: int
    duration_seconds: Decimal
    ceiling_cny: Decimal


SAMPLES = {
    "zh_terms_clean_15s": PinnedSample(
        sample_id="zh_terms_clean_15s",
        filename="zh_terms_clean_15s.flac",
        sha256="2d46a534d6aac1805a9a4721a6fa6bc77930368c75702df77453062af01c8c0b",
        size_bytes=463836,
        duration_seconds=Decimal("15.0"),
        ceiling_cny=Decimal("0.00330"),
    ),
    "long_natural_20_60m": PinnedSample(
        sample_id="long_natural_20_60m",
        filename="long_natural_20_60m.flac",
        sha256="a76206e02eb59324a0df3b60f82e1b67d93e9573fbb3a2c59fc52a5bae935a9a",
        size_bytes=45508973,
        duration_seconds=Decimal("1452.106313"),
        ceiling_cny=Decimal("0.31966"),
    ),
}
LONG_ANCHORS = {
    "start": "4361e47c317bd94c36c650d2c0cd62daf113b8c29804604ce1c451976784f4b4",
    "middle": "6a8e8aed3fcbd38f6cc2d2c18cf4be078e544ed999ac32f46a7679ef6483aa26",
    "end": "7a6fbd70702c745e08acc61ddbbfd227fb666566d6f4b82cd43d799e9316ba75",
}
LAST_REFERENCE_SPEECH = Decimal("1451.597188")
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 3600


@pytest.fixture(scope="module", autouse=True)
def setup_global_notifiers():
    """Override global notifier setup and restore scoped Loguru suppression."""
    logger.disable("video_transcript_api")
    try:
        yield
    finally:
        logger.enable("video_transcript_api")


class AcceptanceStop(RuntimeError):
    """Fail-closed acceptance stop carrying only a safe status."""


class RecordingRepository:
    """Persist the local event identity before the provider can continue."""

    def __init__(
        self,
        repository: UsageEventRepository,
        state_writer: Callable[[Any], None],
    ) -> None:
        self.repository = repository
        self.state_writer = state_writer
        self.event_id: str | None = None

    def reserve_attempt(self, attempt: Any) -> Any:
        event = self.repository.reserve_attempt(attempt)
        self.event_id = event.id
        self.state_writer(event)
        return event

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)


class CountingClient:
    """Count only high-level production-client actions for redacted reporting."""

    def __init__(self, client: AliyunASRClient, counter: dict[str, int]) -> None:
        self.client = client
        self.counter = counter

    def upload_audio(self, *args: Any, **kwargs: Any) -> Any:
        self.counter["remote_calls"] += 1
        return self.client.upload_audio(*args, **kwargs)

    def submit(self, *args: Any, **kwargs: Any) -> Any:
        self.counter["remote_calls"] += 1
        self.counter["submit_calls"] += 1
        return self.client.submit(*args, **kwargs)

    def poll(self, *args: Any, **kwargs: Any) -> Any:
        self.counter["remote_calls"] += 1
        return self.client.poll(*args, **kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_duration(path: Path) -> Decimal:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = Decimal(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError, InvalidOperation):
        raise AcceptanceStop("duration_unknown") from None
    if not duration.is_finite() or duration <= 0:
        raise AcceptanceStop("duration_unknown")
    return duration


def _manifest_sample(manifest: dict[str, Any], sample_id: str) -> dict[str, Any]:
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise AcceptanceStop("manifest_mismatch")
    matches = [
        item
        for item in samples
        if isinstance(item, dict) and item.get("id") == sample_id
    ]
    if len(matches) != 1:
        raise AcceptanceStop("manifest_mismatch")
    return matches[0]


def _verify_long_evidence(
    sample_data: dict[str, Any],
) -> list[tuple[Decimal, Decimal]]:
    reference = sample_data.get("reference")
    if not isinstance(reference, dict):
        raise AcceptanceStop("long_evidence_mismatch")
    try:
        last_reference_speech = Decimal(
            str(reference.get("last_reference_speech_end_seconds"))
        )
    except InvalidOperation:
        raise AcceptanceStop("long_evidence_mismatch") from None
    if last_reference_speech != LAST_REFERENCE_SPEECH:
        raise AcceptanceStop("long_evidence_mismatch")
    evidence = reference.get("last_reference_speech_end_evidence")
    expected_evidence = {
        "method": "ffmpeg_silencedetect",
        "noise_threshold_db": -45,
        "minimum_silence_seconds": 0.4,
        "terminal_silence_start_seconds": 1451.597188,
        "terminal_silence_end_seconds": 1452.106313,
        "tolerance_seconds": 1.0,
        "audio_sha256": SAMPLES["long_natural_20_60m"].sha256,
    }
    if evidence != expected_evidence:
        raise AcceptanceStop("long_evidence_mismatch")
    gap_evidence = reference.get("long_gap_silence_evidence")
    expected_gap_evidence = {
        "method": "ffmpeg_silencedetect",
        "noise_threshold_db": -45,
        "minimum_silence_seconds": 15.0,
        "audio_sha256": SAMPLES["long_natural_20_60m"].sha256,
        "intervals_seconds": [],
    }
    if gap_evidence != expected_gap_evidence:
        raise AcceptanceStop("long_evidence_mismatch")
    anchors = reference.get("anchors")
    if not isinstance(anchors, list) or len(anchors) != 3:
        raise AcceptanceStop("long_evidence_mismatch")
    by_name = {
        item.get("name"): item for item in anchors if isinstance(item, dict)
    }
    for name, expected_hash in LONG_ANCHORS.items():
        anchor = by_name.get(name)
        anchor_path = FIXTURE_ROOT / f"long_anchor_{name}.flac"
        try:
            anchor_matches = (
                isinstance(anchor, dict)
                and anchor.get("audio_sha256") == expected_hash
                and anchor_path.is_file()
                and not anchor_path.is_symlink()
                and _sha256(anchor_path) == expected_hash
            )
        except OSError:
            anchor_matches = False
        if not anchor_matches:
            raise AcceptanceStop("long_evidence_mismatch")
    return []


def _verify_pinned_sample(sample: PinnedSample) -> dict[str, Any]:
    try:
        manifest_bytes = MANIFEST_PATH.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError):
        raise AcceptanceStop("manifest_unknown") from None
    if not isinstance(manifest, dict):
        raise AcceptanceStop("manifest_mismatch")
    sample_data = _manifest_sample(manifest, sample.sample_id)
    expected = {
        "id": sample.sample_id,
        "duration_seconds": float(sample.duration_seconds),
        "size_bytes": sample.size_bytes,
        "sha256": sample.sha256,
    }
    if any(sample_data.get(key) != value for key, value in expected.items()):
        raise AcceptanceStop("manifest_mismatch")
    media_path = FIXTURE_ROOT / sample.filename
    try:
        media_matches = (
            media_path.is_file()
            and not media_path.is_symlink()
            and media_path.stat().st_size == sample.size_bytes
            and _sha256(media_path) == sample.sha256
            and _probe_duration(media_path) == sample.duration_seconds
        )
    except OSError:
        media_matches = False
    if not media_matches:
        raise AcceptanceStop("media_identity_mismatch")
    silence_intervals: list[tuple[Decimal, Decimal]] = []
    if sample.sample_id == "long_natural_20_60m":
        silence_intervals = _verify_long_evidence(sample_data)
    return {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "sample_sha256": sample.sha256,
        "silence_intervals": silence_intervals,
    }


def _exact_budget(sample: PinnedSample, *, required: bool) -> Decimal:
    value = os.environ.get("LEARNFLUX_ALIYUN_ASR_MAX_CNY")
    if value is None and not required:
        return sample.ceiling_cny
    try:
        budget = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise AcceptanceStop("budget_unknown") from None
    if not budget.is_finite() or budget != sample.ceiling_cny:
        raise AcceptanceStop("budget_mismatch")
    return budget


def _settings(max_cny: Decimal) -> NewCloudSubmissionSettings:
    try:
        return NewCloudSubmissionSettings.from_config(
            {
                "cloud_asr": {
                    "enabled": True,
                    "provider": "aliyun",
                    "model": MODEL,
                    "price_cny_per_second": str(PRICE),
                    "price_verified_at": PRICE_VERIFIED_AT,
                    "max_cny_per_task": str(max_cny),
                    "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                    "poll_timeout_seconds": POLL_TIMEOUT_SECONDS,
                }
            },
            today=date.today(),
        )
    except Exception:
        raise AcceptanceStop("price_or_config_unknown") from None


def _receipt_path(sample: PinnedSample) -> Path:
    return RUN_ROOT / sample.sample_id / "dry_run_receipt.json"


def _state_path(sample: PinnedSample) -> Path:
    return RUN_ROOT / sample.sample_id / "attempt_state.json"


def _prepare_media(
    sample: PinnedSample,
    temp_root: Path,
) -> tuple[ASRMediaPreparer, MediaSnapshotter, Any]:
    preparer = ASRMediaPreparer(temp_root)
    snapshotter = MediaSnapshotter(temp_root)
    prepared = preparer.prepare(
        FIXTURE_ROOT / sample.filename,
        _task_id(sample),
    )
    return preparer, snapshotter, prepared


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def _read_private_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AcceptanceStop(code) from None
    if not isinstance(payload, dict):
        raise AcceptanceStop(code)
    return payload


def _task_id(sample: PinnedSample) -> str:
    return f"aliyun-acceptance:{sample.sample_id}:{sample.sha256[:16]}"


def _event_state(event: Any, sample: PinnedSample) -> dict[str, Any]:
    return {
        "version": 1,
        "event_id": event.id,
        "sample_id": sample.sample_id,
        "source_sha256": sample.sha256,
        "snapshot_sha256": event.sample_sha256,
        "safe_status": event.status,
    }


def _write_event_state(path: Path, event: Any, sample: PinnedSample) -> None:
    _write_private_json(path, _event_state(event, sample))


def _event_ids_for_task(db_path: Path, task_id: str) -> list[str]:
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT id FROM usage_events
                WHERE task_id = ? AND step = 'asr'
                ORDER BY attempt_no
                """,
                (task_id,),
            ).fetchall()
    except sqlite3.Error:
        raise AcceptanceStop("usage_state_unknown") from None
    return [str(row[0]) for row in rows]


def _reconcile_existing_event(
    repository: UsageEventRepository,
    db_path: Path,
    state_path: Path,
    sample: PinnedSample,
    receipt: dict[str, Any],
) -> Any | None:
    repository.freeze_stale_submissions(now=datetime.now(UTC))
    event_ids = _event_ids_for_task(db_path, _task_id(sample))
    if len(event_ids) > 1:
        raise AcceptanceStop("multiple_attempts_require_review")
    if not event_ids:
        if state_path.exists():
            raise AcceptanceStop("attempt_state_mismatch")
        return None
    event = repository.get_event(event_ids[0])
    try:
        estimated_quantity = Decimal(event.estimated_quantity)
        unit_price = Decimal(event.unit_price)
        estimated_cost = Decimal(event.estimated_cost)
        receipt_quantity = Decimal(str(receipt.get("snapshot_duration_seconds")))
        receipt_unit_price = Decimal(str(receipt.get("price_cny_per_second")))
        receipt_cost = Decimal(str(receipt.get("ceiling_cny")))
        valid_sample_hash = (
            len(event.sample_sha256) == 64
            and int(event.sample_sha256, 16) >= 0
        )
    except (InvalidOperation, TypeError, ValueError):
        raise AcceptanceStop("attempt_state_mismatch") from None
    if (
        event.provider != "aliyun"
        or event.model != MODEL
        or event.step != "asr"
        or event.unit != "audio_second"
        or event.currency != "CNY"
        or not estimated_quantity.is_finite()
        or estimated_quantity <= 0
        or not unit_price.is_finite()
        or unit_price <= 0
        or not estimated_cost.is_finite()
        or estimated_cost < 0
        or not valid_sample_hash
        or event.sample_sha256 != receipt.get("snapshot_sha256")
        or estimated_quantity != receipt_quantity
        or unit_price != receipt_unit_price
        or estimated_cost != receipt_cost
        or event.output_name != f"aliyun_acceptance_{sample.sample_id}"
        or event.platform != "acceptance"
        or event.media_id != sample.sample_id
        or event.task_id != _task_id(sample)
    ):
        raise AcceptanceStop("attempt_state_mismatch")
    if state_path.exists():
        state = _read_private_json(state_path, "attempt_state_mismatch")
        if (
            state.get("event_id") != event.id
            or state.get("sample_id") != sample.sample_id
            or state.get("source_sha256") != sample.sha256
            or state.get("snapshot_sha256") != event.sample_sha256
        ):
            raise AcceptanceStop("attempt_state_mismatch")
    _write_event_state(state_path, event, sample)
    return event


def _existing_attempt_action(status: str) -> str:
    if status == "succeeded":
        return "load_artifacts"
    if status == "polling_unknown":
        return "resume_required"
    if status == "submission_unknown":
        return "freeze"
    if status == "reserved":
        return "continue_same_event"
    if status in {"submitted", "remote_succeeded", "materialization_failed"}:
        return "recover_same_event"
    return "stop"


def _load_existing_evidence(
    sample: PinnedSample,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = _verify_pinned_sample(sample)
    receipt = _read_private_json(
        _receipt_path(sample),
        "dry_run_receipt_missing",
    )
    expected = {
        "version": 1,
        "sample_id": sample.sample_id,
        "filename": sample.filename,
        "sample_sha256": identity["sample_sha256"],
        "manifest_sha256": identity["manifest_sha256"],
        "size_bytes": sample.size_bytes,
        "duration_seconds": str(sample.duration_seconds),
        "model": MODEL,
        "price_cny_per_second": str(PRICE),
        "price_verified_at": PRICE_VERIFIED_AT,
        "ceiling_cny": str(sample.ceiling_cny),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise AcceptanceStop("dry_run_receipt_mismatch")
    try:
        snapshot_sha256 = receipt["snapshot_sha256"]
        snapshot_size = int(receipt["snapshot_size_bytes"])
        snapshot_duration = Decimal(str(receipt["snapshot_duration_seconds"]))
        receipt_price = Decimal(str(receipt["price_cny_per_second"]))
        receipt_ceiling = Decimal(str(receipt["ceiling_cny"]))
        valid_snapshot_hash = (
            isinstance(snapshot_sha256, str)
            and len(snapshot_sha256) == 64
            and int(snapshot_sha256, 16) >= 0
        )
    except (KeyError, InvalidOperation, TypeError, ValueError):
        raise AcceptanceStop("dry_run_receipt_mismatch") from None
    calculated = (
        snapshot_duration.to_integral_value(rounding=ROUND_CEILING)
        * receipt_price
    )
    if (
        not valid_snapshot_hash
        or snapshot_size <= 0
        or not snapshot_duration.is_finite()
        or snapshot_duration <= 0
        or not receipt_price.is_finite()
        or receipt_price <= 0
        or not receipt_ceiling.is_finite()
        or calculated != receipt_ceiling
    ):
        raise AcceptanceStop("dry_run_receipt_mismatch")
    return identity, receipt


def _receipt(
    sample: PinnedSample,
    identity: dict[str, Any],
    staged: Any,
) -> dict[str, Any]:
    return {
        "version": 1,
        "sample_id": sample.sample_id,
        "filename": sample.filename,
        "sample_sha256": identity["sample_sha256"],
        "manifest_sha256": identity["manifest_sha256"],
        "size_bytes": sample.size_bytes,
        "duration_seconds": str(sample.duration_seconds),
        "snapshot_sha256": staged.sha256,
        "snapshot_size_bytes": staged.size_bytes,
        "snapshot_duration_seconds": str(staged.duration_seconds),
        "model": MODEL,
        "price_cny_per_second": str(PRICE),
        "price_verified_at": PRICE_VERIFIED_AT,
        "ceiling_cny": str(sample.ceiling_cny),
    }


def _report(
    sample: PinnedSample,
    *,
    elapsed: float,
    status: str,
    artifact_complete: bool,
    remote_calls: int,
    snapshot_sha256: str | None = None,
    snapshot_duration_seconds: Decimal | str | None = None,
) -> None:
    safe = {
        "model": MODEL,
        "sample_id": sample.sample_id,
        "sha256_prefix": (snapshot_sha256 or sample.sha256)[:12],
        "duration_seconds": str(
            snapshot_duration_seconds
            if snapshot_duration_seconds is not None
            else sample.duration_seconds
        ),
        "ceiling_cny": str(sample.ceiling_cny),
        "price_verified_at": PRICE_VERIFIED_AT,
        "elapsed_seconds": round(max(0.0, elapsed), 3),
        "safe_status": status,
        "artifact_complete": artifact_complete,
        "remote_calls": remote_calls,
    }
    print(json.dumps(safe, sort_keys=True, separators=(",", ":")))


def _client_factory(counter: dict[str, int]):
    def create(credentials: AliyunCredentials) -> CountingClient:
        return CountingClient(
            AliyunASRClient(
                credentials.api_key,
                credentials.workspace_id,
                api_host=credentials.api_host,
            ),
            counter,
        )

    return create


def _gap_fully_explained(
    gap_start: Decimal,
    gap_end: Decimal,
    silence_intervals: list[tuple[Decimal, Decimal]],
) -> bool:
    cursor = gap_start
    for silence_start, silence_end in sorted(silence_intervals):
        if silence_end <= cursor:
            continue
        if silence_start > cursor:
            return False
        cursor = max(cursor, silence_end)
        if cursor >= gap_end:
            return True
    return cursor >= gap_end


def _artifacts_complete_from_disk(
    event: Any,
    sample: PinnedSample,
    output_dir: Path,
    silence_intervals: list[tuple[Decimal, Decimal]],
) -> bool:
    if (
        not isinstance(event.output_name, str)
        or Path(event.output_name).name != event.output_name
    ):
        return False
    txt_path = output_dir / f"{event.output_name}.txt"
    json_path = output_dir / f"{event.output_name}_funasr.json"
    try:
        if not txt_path.is_file() or txt_path.stat().st_size <= 0:
            return False
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get("task_id") not in {"", None}:
        return False
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return False
    if sample.sample_id != "long_natural_20_60m":
        return True
    timed_segments: list[tuple[Decimal, Decimal, str]] = []
    previous_start = Decimal("-1")
    previous_end = Decimal("-1")
    for segment in segments:
        if not isinstance(segment, dict):
            return False
        try:
            start = Decimal(str(segment["start_time"]))
            end = Decimal(str(segment["end_time"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return False
        text = segment.get("text")
        if (
            not start.is_finite()
            or not end.is_finite()
            or start < 0
            or end < start
            or start < previous_start
            or end < previous_end
            or not isinstance(text, str)
        ):
            return False
        previous_start = start
        previous_end = end
        timed_segments.append((start, end, text))
    text_segments = [item for item in timed_segments if item[2].strip()]
    if not text_segments:
        return False
    anchor_ranges = (
        (Decimal("60"), Decimal("105")),
        (Decimal("700"), Decimal("745")),
        (Decimal("1392"), Decimal("1452")),
    )
    if not all(
        any(
            start < anchor_end and end > anchor_start
            for start, end, _ in text_segments
        )
        for anchor_start, anchor_end in anchor_ranges
    ):
        return False
    cursor = Decimal("0")
    for start, end, _ in text_segments:
        if (
            start - cursor >= Decimal("15")
            and not _gap_fully_explained(cursor, start, silence_intervals)
        ):
            return False
        cursor = max(cursor, end)
    return abs(text_segments[-1][1] - LAST_REFERENCE_SPEECH) <= Decimal("5")


def _paid_flag_enabled() -> bool:
    return os.environ.get("LEARNFLUX_ALIYUN_ASR_EXECUTE_PAID") == "1"


def _load_existing_artifacts(
    repository: UsageEventRepository,
    event: Any,
    sample: PinnedSample,
    output_dir: Path,
    silence_intervals: list[tuple[Decimal, Decimal]],
) -> bool:
    current = repository.get_event(event.id)
    if current.status != "succeeded":
        return False
    return _artifacts_complete_from_disk(
        current,
        sample,
        output_dir,
        silence_intervals,
    )


def _recover_persisted_event(
    repository: UsageEventRepository,
    event: Any,
    sample: PinnedSample,
    counter: dict[str, int],
    output_dir: Path,
) -> Any:
    recovery_event = repository.get_recovery_event(event.id)
    if not recovery_event.provider_task_id:
        raise AcceptanceStop("attempt_state_mismatch")
    recovery = CloudASRRecoveryCoordinator(
        repository=repository,
        snapshotter=MediaSnapshotter(RUN_ROOT / sample.sample_id / "temp"),
        output_dir=output_dir,
        credential_loader=lambda: AliyunCredentials.from_environ(os.environ),
        client_factory=_client_factory(counter),
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        poll_timeout_seconds=POLL_TIMEOUT_SECONDS,
    )
    recovery.recover_event(event.id)
    if counter["submit_calls"] != 0:
        raise AcceptanceStop("resume_submit_forbidden")
    current = repository.get_event(event.id)
    _write_event_state(_state_path(sample), current, sample)
    return current


def _run_resume(
    sample: PinnedSample,
    counter: dict[str, int],
    started: float,
) -> None:
    identity, receipt = _load_existing_evidence(sample)
    sample_root = RUN_ROOT / sample.sample_id
    db_path = sample_root / "usage.db"
    repository: UsageEventRepository | None = None
    event = None
    if db_path.is_file():
        repository = UsageEventRepository(db_path)
        event = _reconcile_existing_event(
            repository,
            db_path,
            _state_path(sample),
            sample,
            receipt,
        )
    if not _paid_flag_enabled():
        _report(
            sample,
            elapsed=time.monotonic() - started,
            status="paid_execution_disabled",
            artifact_complete=False,
            remote_calls=0,
        )
        pytest.skip("paid_execution_disabled_remote_calls_0")
    if repository is None or event is None:
        raise AcceptanceStop("attempt_state_missing")
    action = _existing_attempt_action(event.status)
    output_dir = sample_root / "output"
    if action == "load_artifacts":
        complete = _load_existing_artifacts(
            repository,
            event,
            sample,
            output_dir,
            identity["silence_intervals"],
        )
        _report(
            sample,
            elapsed=time.monotonic() - started,
            status="succeeded",
            artifact_complete=complete,
            remote_calls=0,
            snapshot_sha256=event.sample_sha256,
            snapshot_duration_seconds=event.estimated_quantity,
        )
        if not complete:
            raise AcceptanceStop("artifact_incomplete")
        return
    if action == "freeze":
        _report(
            sample,
            elapsed=time.monotonic() - started,
            status="submission_unknown",
            artifact_complete=False,
            remote_calls=0,
            snapshot_sha256=event.sample_sha256,
            snapshot_duration_seconds=event.estimated_quantity,
        )
        return
    if action not in {"recover_same_event", "resume_required"}:
        raise AcceptanceStop("resume_not_allowed")

    current = _recover_persisted_event(
        repository,
        event,
        sample,
        counter,
        output_dir,
    )
    if current.status == "polling_unknown":
        _report(
            sample,
            elapsed=time.monotonic() - started,
            status=current.status,
            artifact_complete=False,
            remote_calls=counter["remote_calls"],
            snapshot_sha256=current.sample_sha256,
            snapshot_duration_seconds=current.estimated_quantity,
        )
        return
    if current.status != "succeeded":
        raise AcceptanceStop(current.status)
    complete = _artifacts_complete_from_disk(
        current,
        sample,
        output_dir,
        identity["silence_intervals"],
    )
    _report(
        sample,
        elapsed=time.monotonic() - started,
        status=current.status,
        artifact_complete=complete,
        remote_calls=counter["remote_calls"],
        snapshot_sha256=current.sample_sha256,
        snapshot_duration_seconds=current.estimated_quantity,
    )
    if not complete:
        raise AcceptanceStop("artifact_incomplete")


def test_aliyun_funasr_acceptance() -> None:
    """Dry-run by default; execute/resume only through explicit paid gates."""
    started = time.monotonic()
    counter = {"remote_calls": 0, "submit_calls": 0}
    sample_name = os.environ.get(
        "LEARNFLUX_ALIYUN_ASR_SAMPLE", "zh_terms_clean_15s"
    )
    sample = SAMPLES.get(sample_name)
    if sample is None:
        pytest.fail("unknown_sample_remote_calls_0", pytrace=False)
    mode = os.environ.get("LEARNFLUX_ALIYUN_ASR_MODE", "dry-run")
    try:
        if mode not in {"dry-run", "execute", "resume"}:
            raise AcceptanceStop("unknown_mode")
        if mode == "resume":
            _run_resume(sample, counter, started)
            return

        sample_root = RUN_ROOT / sample.sample_id
        repository: UsageEventRepository | None = None
        existing = None
        identity: dict[str, Any] | None = None
        stored_receipt: dict[str, Any] | None = None
        db_path = sample_root / "usage.db"
        if mode == "execute" and db_path.is_file():
            identity, stored_receipt = _load_existing_evidence(sample)
            repository = UsageEventRepository(db_path)
            existing = _reconcile_existing_event(
                repository,
                db_path,
                _state_path(sample),
                sample,
                stored_receipt,
            )
        if mode == "execute" and not _paid_flag_enabled():
            _report(
                sample,
                elapsed=time.monotonic() - started,
                status="paid_execution_disabled",
                artifact_complete=False,
                remote_calls=0,
            )
            pytest.skip("paid_execution_disabled_remote_calls_0")

        if mode == "execute":
            if identity is None or stored_receipt is None:
                identity, stored_receipt = _load_existing_evidence(sample)
            if repository is None:
                repository = UsageEventRepository(db_path)
                existing = _reconcile_existing_event(
                    repository,
                    db_path,
                    _state_path(sample),
                    sample,
                    stored_receipt,
                )
            if existing is not None:
                action = _existing_attempt_action(existing.status)
                if action == "load_artifacts":
                    complete = _load_existing_artifacts(
                        repository,
                        existing,
                        sample,
                        sample_root / "output",
                        identity["silence_intervals"],
                    )
                    _report(
                        sample,
                        elapsed=time.monotonic() - started,
                        status="succeeded",
                        artifact_complete=complete,
                        remote_calls=0,
                        snapshot_sha256=existing.sample_sha256,
                        snapshot_duration_seconds=existing.estimated_quantity,
                    )
                    if not complete:
                        raise AcceptanceStop("artifact_incomplete")
                    return
                if action == "freeze":
                    _report(
                        sample,
                        elapsed=time.monotonic() - started,
                        status="submission_unknown",
                        artifact_complete=False,
                        remote_calls=0,
                        snapshot_sha256=existing.sample_sha256,
                        snapshot_duration_seconds=existing.estimated_quantity,
                    )
                    return
                if action == "resume_required":
                    raise AcceptanceStop("resume_required")
                if action == "recover_same_event":
                    current = _recover_persisted_event(
                        repository,
                        existing,
                        sample,
                        counter,
                        sample_root / "output",
                    )
                    complete = current.status == "succeeded" and (
                        _artifacts_complete_from_disk(
                            current,
                            sample,
                            sample_root / "output",
                            identity["silence_intervals"],
                        )
                    )
                    _report(
                        sample,
                        elapsed=time.monotonic() - started,
                        status=current.status,
                        artifact_complete=complete,
                        remote_calls=counter["remote_calls"],
                        snapshot_sha256=current.sample_sha256,
                        snapshot_duration_seconds=current.estimated_quantity,
                    )
                    if current.status == "polling_unknown":
                        return
                    if not complete:
                        raise AcceptanceStop(current.status)
                    return
                if action != "continue_same_event":
                    raise AcceptanceStop("existing_attempt_requires_review")

        if identity is None:
            identity = _verify_pinned_sample(sample)
        temp_root = (
            sample_root / "dry_run_temp"
            if mode == "dry-run"
            else sample_root / "temp"
        )
        preparer, snapshotter, staged = _prepare_media(sample, temp_root)
        try:
            settings = _settings(
                _exact_budget(sample, required=mode == "execute")
            )
            if settings.estimated_cost(staged.duration_seconds) != sample.ceiling_cny:
                raise AcceptanceStop("ceiling_mismatch")
            expected_receipt = _receipt(sample, identity, staged)
            if mode == "dry-run":
                _write_private_json(_receipt_path(sample), expected_receipt)
                _report(
                    sample,
                    elapsed=time.monotonic() - started,
                    status="dry_run_ready",
                    artifact_complete=False,
                    remote_calls=0,
                    snapshot_sha256=staged.sha256,
                    snapshot_duration_seconds=staged.duration_seconds,
                )
                return
            if stored_receipt != expected_receipt:
                raise AcceptanceStop("snapshot_receipt_mismatch")

            output_dir = sample_root / "output"
            state_path = _state_path(sample)
            recording_repository = RecordingRepository(
                repository,
                lambda event: _write_event_state(state_path, event, sample),
            )
            provider = AliyunFunASRProvider(
                settings=settings,
                repository=recording_repository,
                snapshotter=snapshotter,
                output_dir=output_dir,
                credential_loader=lambda: AliyunCredentials.from_environ(os.environ),
                client_factory=_client_factory(counter),
                attempt_reserver=recording_repository.reserve_attempt,
                prepared_media_cleanup=preparer.cleanup,
            )
            try:
                provider.transcribe(
                    str(staged.path),
                    f"aliyun_acceptance_{sample.sample_id}",
                    context=TranscriptionContext(
                        task_id=_task_id(sample),
                        platform="acceptance",
                        media_id=sample.sample_id,
                        continuation_json=json.dumps(
                            {"version": 1, "sample_id": sample.sample_id},
                            separators=(",", ":"),
                        ),
                        prepared_media=staged,
                    ),
                )
            except CloudProviderError as exc:
                event_id = recording_repository.event_id
                status = exc.code
                report_sha256 = staged.sha256
                report_duration = staged.duration_seconds
                if event_id is not None:
                    current = repository.get_event(event_id)
                    status = current.status
                    report_sha256 = current.sample_sha256
                    report_duration = current.estimated_quantity
                    _write_event_state(state_path, current, sample)
                if status in {"submission_unknown", "polling_unknown"}:
                    _report(
                        sample,
                        elapsed=time.monotonic() - started,
                        status=status,
                        artifact_complete=False,
                        remote_calls=counter["remote_calls"],
                        snapshot_sha256=report_sha256,
                        snapshot_duration_seconds=report_duration,
                    )
                    return
                raise AcceptanceStop(status) from None
            event_id = recording_repository.event_id
            if event_id is None:
                raise AcceptanceStop("usage_event_missing")
            current = repository.get_event(event_id)
            _write_event_state(state_path, current, sample)
            complete = _artifacts_complete_from_disk(
                current,
                sample,
                output_dir,
                identity["silence_intervals"],
            )
            _report(
                sample,
                elapsed=time.monotonic() - started,
                status=current.status,
                artifact_complete=complete,
                remote_calls=counter["remote_calls"],
                snapshot_sha256=current.sample_sha256,
                snapshot_duration_seconds=current.estimated_quantity,
            )
            if current.status != "succeeded" or not complete:
                raise AcceptanceStop("artifact_incomplete")
        finally:
            preparer.cleanup(staged)
    except AcceptanceStop as exc:
        _report(
            sample,
            elapsed=time.monotonic() - started,
            status=str(exc),
            artifact_complete=False,
            remote_calls=counter["remote_calls"],
        )
        pytest.fail(str(exc), pytrace=False)
    except Exception:
        _report(
            sample,
            elapsed=time.monotonic() - started,
            status="acceptance_internal_error",
            artifact_complete=False,
            remote_calls=counter["remote_calls"],
        )
        pytest.fail("acceptance_internal_error", pytrace=False)


def test_reserved_state_is_immediate_and_reconciles_a_stale_submit(tmp_path: Path) -> None:
    """The real crash window freezes from SQLite and rebuilds private state."""
    sample = SAMPLES["zh_terms_clean_15s"]
    db_path = tmp_path / "usage.db"
    state_path = tmp_path / "attempt_state.json"
    repository = UsageEventRepository(db_path)
    recording = RecordingRepository(
        repository,
        lambda event: _write_event_state(state_path, event, sample),
    )
    event = recording.reserve_attempt(
        NewASRAttempt(
            task_id=_task_id(sample),
            model=MODEL,
            estimated_quantity=Decimal("15"),
            unit_price=PRICE,
            estimated_cost=sample.ceiling_cny,
            owner_key="",
            sample_sha256=sample.sha256,
            platform="acceptance",
            media_id=sample.sample_id,
            output_name=f"aliyun_acceptance_{sample.sample_id}",
            continuation_json=json.dumps(
                {"version": 1, "sample_id": sample.sample_id},
                separators=(",", ":"),
            ),
        )
    )
    assert _read_private_json(state_path, "missing")["event_id"] == event.id
    stale_now = datetime(2000, 1, 1, tzinfo=UTC)
    assert repository.claim_submission(event.id, "owner", now=stale_now)
    state_path.unlink()
    receipt = {
        "snapshot_sha256": sample.sha256,
        "snapshot_duration_seconds": "15",
        "price_cny_per_second": str(PRICE),
        "ceiling_cny": str(sample.ceiling_cny),
    }

    reconciled = _reconcile_existing_event(
        repository,
        db_path,
        state_path,
        sample,
        receipt,
    )

    assert reconciled is not None
    assert reconciled.status == "submission_unknown"
    assert _existing_attempt_action(reconciled.status) == "freeze"
    assert _read_private_json(state_path, "missing")["event_id"] == event.id
    assert _existing_attempt_action("reserved") == "continue_same_event"
    assert _existing_attempt_action("submitted") == "recover_same_event"
    assert _existing_attempt_action("remote_succeeded") == "recover_same_event"
    assert _existing_attempt_action("materialization_failed") == "recover_same_event"
    assert _existing_attempt_action("polling_unknown") == "resume_required"
    with pytest.raises(AcceptanceStop, match="attempt_state_mismatch"):
        _reconcile_existing_event(
            repository,
            db_path,
            state_path,
            sample,
            receipt | {"snapshot_sha256": "0" * 64},
        )


def test_long_gap_requires_complete_reference_silence_coverage() -> None:
    """A long result gap is explainable only when silence covers all of it."""
    silences = [(Decimal("10"), Decimal("20")), (Decimal("20"), Decimal("30"))]
    assert _gap_fully_explained(Decimal("12"), Decimal("28"), silences)
    assert not _gap_fully_explained(
        Decimal("12"),
        Decimal("31"),
        silences,
    )
