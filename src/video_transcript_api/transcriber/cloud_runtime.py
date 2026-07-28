"""Trusted service-process wiring for the Aliyun cloud provider."""

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from .aliyun_client import AliyunASRClient, AliyunCredentials
from .cloud_config import NewCloudSubmissionSettings
from .control_store import QuoteBackedReservedAttempt
from .media_preparer import (
    ASRMediaPreparer,
    MEDIA_SUFFIXES,
    MediaPreparationError,
    PreparedASRMedia,
)
from .media_snapshot import MediaSnapshotter, SnapshotError
from .providers.aliyun_funasr import AliyunFunASRProvider, CloudProviderError
from .recovery import CloudASRRecoveryCoordinator


@dataclass(frozen=True, slots=True)
class IdentifiedReservedAttempts:
    """Validated startup candidates and roots needed during temp cleanup."""

    records: tuple[QuoteBackedReservedAttempt, ...]
    media_roots: frozenset[Path]


def _resolve_quote_media(
    record: QuoteBackedReservedAttempt, temp_root: str | Path
) -> Path:
    root = Path(temp_root).absolute()
    reference = Path(record.media_ref)
    expected_task_hash = hashlib.sha256(record.task_id.encode()).hexdigest()
    if (
        reference.is_absolute()
        or len(reference.parts) != 4
        or reference.parts[0] != "cloud_quotes"
        or reference.parts[1] != expected_task_hash
        or not reference.parts[2].startswith("quote-")
        or reference.parts[3]
        not in {f"input{suffix}" for suffix in MEDIA_SUFFIXES.values()}
    ):
        raise MediaPreparationError("media_identity_mismatch")
    candidate = root / reference
    try:
        resolved_root = root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
        if candidate.absolute() != resolved_candidate:
            raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise MediaPreparationError("media_identity_mismatch") from None
    return resolved_candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconcile_stale_local_queued(
    repository, temp_root: str | Path, cutoff: datetime
) -> list[str]:
    """Reset prior-process local handoffs only when quote media still matches."""
    valid_task_ids = []
    for quote in repository.list_stale_local_queued(created_before=cutoff):
        try:
            media_path = _resolve_quote_media(quote, temp_root)
            if _file_sha256(media_path) != quote.media_sha256:
                continue
        except (MediaPreparationError, OSError):
            continue
        valid_task_ids.append(quote.task_id)
    return repository.reset_stale_local_queued(
        valid_task_ids, created_before=cutoff
    )


def _verify_quote_media(
    record: QuoteBackedReservedAttempt, temp_root: str | Path
) -> tuple[ASRMediaPreparer, PreparedASRMedia]:
    preparer = ASRMediaPreparer(temp_root)
    prepared = preparer.verify_existing(
        _resolve_quote_media(record, temp_root),
        record.media_sha256,
        record.duration_seconds,
    )
    return preparer, prepared


def identify_quote_backed_reserved(
    store, temp_root: str | Path, cutoff: datetime
) -> IdentifiedReservedAttempts:
    """Protect only old consumed reservations with one trustworthy media copy."""
    snapshotter = MediaSnapshotter(temp_root)
    records: list[QuoteBackedReservedAttempt] = []
    media_roots: set[Path] = set()
    for record in store.list_quote_backed_reserved(created_before=cutoff):
        try:
            snapshot = snapshotter.find_attempt(
                task_id=record.task_id,
                attempt_no=record.attempt_no,
                expected_sha256=record.media_sha256,
                duration_seconds=record.duration_seconds,
            )
            media_root = snapshot.path.parent
        except SnapshotError:
            try:
                _, prepared = _verify_quote_media(record, temp_root)
                media_root = prepared.path.parent
            except MediaPreparationError:
                continue
        records.append(record)
        media_roots.add(media_root)
    return IdentifiedReservedAttempts(tuple(records), frozenset(media_roots))


def resume_quote_backed_reserved_attempt(
    record: QuoteBackedReservedAttempt,
    *,
    store,
    temp_root: str | Path,
    provider,
):
    """Resume the same reserved event without creating usage or another quote."""
    event = store.usage_repository.get_event(record.event_id)
    if (
        event.task_id != record.task_id
        or event.attempt_no != record.attempt_no
        or event.remote_status != "reserved"
        or event.sample_sha256 != record.media_sha256
    ):
        raise CloudProviderError("attempt_requires_recovery")

    snapshotter = MediaSnapshotter(temp_root)
    quote_media: tuple[ASRMediaPreparer, PreparedASRMedia] | None = None
    try:
        snapshot = snapshotter.find_attempt(
            task_id=record.task_id,
            attempt_no=record.attempt_no,
            expected_sha256=record.media_sha256,
            duration_seconds=record.duration_seconds,
        )
    except SnapshotError:
        try:
            quote_media = _verify_quote_media(record, temp_root)
            snapshot = snapshotter.promote(
                quote_media[1],
                task_id=record.task_id,
                attempt_no=record.attempt_no,
                expected_sha256=record.media_sha256,
                create=True,
            )
        except (MediaPreparationError, SnapshotError):
            raise CloudProviderError("media_identity_mismatch") from None
    else:
        try:
            quote_media = _verify_quote_media(record, temp_root)
        except MediaPreparationError:
            quote_media = None

    if quote_media is not None:
        try:
            quote_media[0].cleanup(quote_media[1])
        except Exception:
            pass
    return provider.submit_reserved_event(event, snapshot)


class _ExistingAttemptRecoveryProvider:
    """Expose one persisted provider task through the normal provider seam."""

    name = "aliyun"

    def __init__(self, *, event_id, task_id, repository, recovery) -> None:
        self.event_id = event_id
        self.task_id = task_id
        self.repository = repository
        self.recovery = recovery

    def transcribe(self, audio_path, output_base, *, context=None):
        del audio_path, output_base
        if context is None or context.task_id != self.task_id:
            raise CloudProviderError("context_required")
        result = self.recovery.recover_event(self.event_id)
        if result is not None:
            return result
        current = self.repository.get_event(self.event_id)
        if current.remote_status in {"submitted", "polling_unknown"}:
            raise CloudProviderError("polling_unknown")
        raise CloudProviderError("attempt_requires_recovery")


def build_aliyun_provider(
    *, config, output_dir, progress_callback=None, context=None
):
    """Build one provider without reading credentials before local gates pass."""
    del progress_callback
    from ..api.context import (
        get_temp_manager,
        get_transcription_control_store,
        get_transcription_concurrency_controller,
        get_cloud_submission_guard,
    )

    temp_manager = get_temp_manager()
    control_store = get_transcription_control_store()
    repository = control_store.usage_repository
    controller = get_transcription_concurrency_controller()

    def update_capacity(event_id: str) -> None:
        if repository.remote_attempt_occupies_capacity(event_id):
            return
        try:
            controller.release("cloud", f"usage:{event_id}")
        except Exception:
            pass

    def transfer_capacity(event) -> None:
        if context is not None and context.owner_key:
            controller.transfer_cloud_owner(
                context.owner_key, f"usage:{event.id}"
            )

    if context is not None:
        existing = repository.find_recoverable_event_by_task_id(
            context.task_id
        )
        if existing is not None:
            transfer_capacity(existing)
            recovery = build_aliyun_recovery(
                config=config,
                output_dir=output_dir,
                repository=repository,
                attempt_state_callback=update_capacity,
            )
            return _ExistingAttemptRecoveryProvider(
                event_id=existing.id,
                task_id=context.task_id,
                repository=repository,
                recovery=recovery,
            )

    settings = NewCloudSubmissionSettings.from_config(config, today=date.today())
    if context is not None and context.accepted_max_cost is not None:
        settings = replace(settings, accepted_max_cost=context.accepted_max_cost)
    snapshotter = MediaSnapshotter(temp_manager.get_temp_dir())
    temp_root = temp_manager.get_temp_dir()

    def cleanup_prepared_media(prepared) -> None:
        preparer = ASRMediaPreparer(temp_root)
        verified = preparer.verify_existing(
            prepared.path,
            prepared.sha256,
            prepared.duration_seconds,
        )
        if (
            verified.media_format != prepared.media_format
            or verified.size_bytes != prepared.size_bytes
        ):
            raise MediaPreparationError("media_identity_mismatch")
        preparer.cleanup(verified)
        if os.path.lexists(verified.path):
            raise RuntimeError("prepared_media_cleanup_failed")

    attempt_reserver = repository.reserve_attempt
    if context is not None and context.accepted_max_cost is not None:
        attempt_reserver = control_store.reserve_attempt_and_consume_quote

    def load_credentials():
        return AliyunCredentials.from_environ(os.environ)

    def create_client(credentials: AliyunCredentials):
        return AliyunASRClient(
            credentials.api_key,
            credentials.workspace_id,
            api_host=credentials.api_host,
        )

    return AliyunFunASRProvider(
        settings=settings,
        repository=repository,
        snapshotter=snapshotter,
        output_dir=Path(output_dir),
        credential_loader=load_credentials,
        client_factory=create_client,
        attempt_reserver=attempt_reserver,
        prepared_media_cleanup=cleanup_prepared_media,
        submission_guard=get_cloud_submission_guard(),
        capacity_transfer_callback=transfer_capacity,
        attempt_state_callback=update_capacity,
    )


def build_aliyun_reserved_provider(
    *, config, output_dir, repository, attempt_state_callback=None
):
    """Build the submitter for an existing reserved event without reserving."""
    from ..api.context import get_temp_manager

    settings = NewCloudSubmissionSettings.from_config(config, today=date.today())
    snapshotter = MediaSnapshotter(get_temp_manager().get_temp_dir())

    def load_credentials():
        return AliyunCredentials.from_environ(os.environ)

    def create_client(credentials: AliyunCredentials):
        return AliyunASRClient(
            credentials.api_key,
            credentials.workspace_id,
            api_host=credentials.api_host,
        )

    def refuse_new_attempt(_attempt):
        raise CloudProviderError("attempt_requires_recovery")

    return AliyunFunASRProvider(
        settings=settings,
        repository=repository,
        snapshotter=snapshotter,
        output_dir=Path(output_dir),
        credential_loader=load_credentials,
        client_factory=create_client,
        attempt_reserver=refuse_new_attempt,
        prepared_media_cleanup=lambda _prepared: None,
        attempt_state_callback=attempt_state_callback,
    )


def build_aliyun_recovery(
    *,
    config,
    output_dir,
    repository,
    result_callback=None,
    attempt_state_callback=None,
    stop_event=None,
):
    """Build poll-only recovery without applying new-submission config gates."""
    from ..api.context import get_temp_manager

    cloud_config = config.get("cloud_asr", {})
    poll_interval = cloud_config.get("poll_interval_seconds", 1)
    poll_timeout = cloud_config.get("poll_timeout_seconds", 3600)
    if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)):
        poll_interval = 1
    if isinstance(poll_timeout, bool) or not isinstance(poll_timeout, (int, float)):
        poll_timeout = 3600
    poll_interval = min(max(float(poll_interval), 0.1), 60.0)
    poll_timeout = min(max(float(poll_timeout), 1.0), 43200.0)
    snapshotter = MediaSnapshotter(get_temp_manager().get_temp_dir())

    def load_credentials():
        return AliyunCredentials.from_environ(os.environ)

    def create_client(credentials: AliyunCredentials):
        return AliyunASRClient(
            credentials.api_key,
            credentials.workspace_id,
            api_host=credentials.api_host,
        )

    return CloudASRRecoveryCoordinator(
        repository=repository,
        snapshotter=snapshotter,
        output_dir=Path(output_dir),
        credential_loader=load_credentials,
        client_factory=create_client,
        poll_interval_seconds=poll_interval,
        poll_timeout_seconds=poll_timeout,
        result_callback=result_callback,
        attempt_state_callback=attempt_state_callback,
        stop_event=stop_event,
    )
