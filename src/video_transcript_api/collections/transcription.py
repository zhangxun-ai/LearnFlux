"""Transcription strategy and concurrency policy for learning collections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping, Sequence

from ..transcriber.cloud_quote_repository import (
    CloudQuoteConfirmation,
    CloudQuoteConflict,
)
from ..utils.logging import setup_logger


logger = setup_logger("collection_transcription")


TranscriptionStrategy = Literal["local", "cloud"]

STRATEGY_HARD_LIMITS: dict[TranscriptionStrategy, int] = {
    "local": 3,
    "cloud": 10,
}


@dataclass(frozen=True)
class SourceLaunch:
    source_id: str
    task_id: str
    file_path: str
    original_name: str
    display_url: str
    media_id: str
    strategy: TranscriptionStrategy


@dataclass(frozen=True)
class CollectionStartResult:
    sources: tuple[dict, ...]
    launches: tuple[SourceLaunch, ...]
    cache_hit_count: int
    requested_concurrency: int
    effective_concurrency: int | None


@dataclass(frozen=True)
class CollectionStopResult:
    collection: dict
    stopped_count: int
    in_flight_count: int


@dataclass(frozen=True)
class CollectionQuoteItem:
    task_id: str
    source_id: str
    title: str
    quote_token: str
    duration_seconds: Decimal
    billable_seconds: int
    max_cost_cny: Decimal


@dataclass(frozen=True)
class CollectionQuoteSnapshot:
    state: Literal["empty", "preparing", "ready", "refresh_required", "failed"]
    video_count: int
    cache_hit_count: int
    pending_count: int
    duration_seconds: Decimal
    billable_seconds: int
    max_cost_cny: Decimal
    transcription_revision: int
    items: tuple[CollectionQuoteItem, ...]
    failures: tuple[dict, ...]


@dataclass(frozen=True)
class CollectionQuoteRefreshResult:
    snapshot: CollectionQuoteSnapshot | None
    failures: tuple[dict, ...]


@dataclass(frozen=True)
class CollectionQuoteConfirmationResult:
    status: Literal["confirmed", "already_confirmed"]
    task_ids: tuple[str, ...]


RESUMABLE_EVIDENCE = {"collection_resume_allowed": True}


@dataclass(frozen=True)
class _PreparedSource:
    candidate: Mapping[str, Any]
    task: Mapping[str, str]
    is_cache_alias: bool
    registration: dict[str, Any]


class CollectionTranscriptionService:
    """Register collection upload tasks without starting provider work."""

    def __init__(
        self,
        repository,
        cache_manager,
        *,
        quote_repository=None,
        quote_refresher=None,
        concurrency_controller=None,
        cloud_dispatcher=None,
    ) -> None:
        self.repository = repository
        self.cache_manager = cache_manager
        self.quote_repository = quote_repository
        self.quote_refresher = quote_refresher
        self.concurrency_controller = concurrency_controller
        self.cloud_dispatcher = cloud_dispatcher

    def get_cloud_quote_snapshot(
        self, collection_id: str, *, owner_user_id: str
    ) -> CollectionQuoteSnapshot:
        """Build one fail-closed view of the collection's current cloud quotes."""
        collection = self.repository.get_collection(collection_id)
        if not collection or collection.get("owner_user_id") != owner_user_id:
            raise ValueError("collection_not_found")
        if collection.get("transcription_strategy") != "cloud":
            raise ValueError("invalid_collection_transcription_strategy")
        if self.quote_repository is None:
            raise RuntimeError("cloud_quote_repository_required")

        sources = [
            source
            for source in self.repository.get_sources(collection_id)
            if source.get("source_type") == "video"
        ]
        cache_hit_count = 0
        items: list[CollectionQuoteItem] = []
        failures: list[dict] = []
        preparing = False
        refresh_required = False

        for source in sources:
            task_id = str(source["task_id"])
            task = self.cache_manager.get_task_by_id(task_id) or {}
            task_status = task.get("status")
            progress = task.get("progress") or {}
            evidence = progress.get("evidence") or {}

            if task_status == "success":
                if evidence.get("cache_hit") is True:
                    cache_hit_count += 1
                continue
            if task_status == "canceled":
                continue

            try:
                quote = self.quote_repository.get(task_id)
            except CloudQuoteConflict as exc:
                if str(exc) != "quote_not_found":
                    raise
                quote = None

            if task_status == "failed" and quote is None:
                failures.append(
                    {
                        "source_id": source["id"],
                        "task_id": task_id,
                        "title": source["title"],
                        "message": task.get("error_message") or "cloud_quote_preflight_failed",
                    }
                )
                continue

            if quote is None:
                if task_status in {"queued", "processing"}:
                    preparing = True
                elif task_status == "awaiting_cloud_confirmation":
                    refresh_required = True
                continue

            if quote.status in {
                "confirmed_queued",
                "confirming",
                "consumed",
                "local_selected",
                "local_queued",
                "canceled",
                "failed",
                "expired",
            }:
                continue
            if quote.status == "refresh_required":
                refresh_required = True
                continue
            if quote.status != "pending" or task_status != "awaiting_cloud_confirmation":
                refresh_required = True
                continue

            progress_quote = evidence.get("cloud_quote") or {}
            raw_task_id = progress_quote.get("task_id")
            raw_token = progress_quote.get("quote_token")
            raw_cost = progress_quote.get("max_cost_cny")
            try:
                progress_cost = Decimal(str(raw_cost))
            except (InvalidOperation, TypeError, ValueError):
                progress_cost = None
            if (
                quote.task_id != task_id
                or (raw_task_id is not None and raw_task_id != task_id)
                or not isinstance(raw_token, str)
                or not raw_token
                or progress_cost is None
                or not progress_cost.is_finite()
                or progress_cost != quote.max_cost
                or (
                    progress.get("stage") is not None
                    and progress.get("stage") != "awaiting_cloud_confirmation"
                )
            ):
                refresh_required = True
                continue
            items.append(
                CollectionQuoteItem(
                    task_id=task_id,
                    source_id=str(source["id"]),
                    title=str(source["title"]),
                    quote_token=raw_token,
                    duration_seconds=quote.duration_seconds,
                    billable_seconds=int(quote.billable_seconds),
                    max_cost_cny=quote.max_cost,
                )
            )

        if failures:
            state = "failed"
            items = []
        elif preparing:
            state = "preparing"
        elif refresh_required:
            state = "refresh_required"
        elif items:
            state = "ready"
        else:
            state = "empty"
        return CollectionQuoteSnapshot(
            state=state,
            video_count=len(sources),
            cache_hit_count=cache_hit_count,
            pending_count=len(items),
            duration_seconds=sum(
                (item.duration_seconds for item in items), Decimal("0")
            ),
            billable_seconds=sum(item.billable_seconds for item in items),
            max_cost_cny=sum((item.max_cost_cny for item in items), Decimal("0")),
            transcription_revision=int(collection.get("transcription_revision") or 0),
            items=tuple(items),
            failures=tuple(failures),
        )

    def refresh_collection_cloud_quotes(
        self, collection_id: str, *, owner_user_id: str
    ) -> CollectionQuoteRefreshResult:
        """Refresh only repository-marked stale quotes in this collection."""
        self.get_cloud_quote_snapshot(
            collection_id, owner_user_id=owner_user_id
        )
        if self.quote_refresher is None:
            raise RuntimeError("cloud_quote_refresher_required")

        stale_sources: list[tuple[dict, object]] = []
        for source in self.repository.get_sources(collection_id):
            if source.get("source_type") != "video":
                continue
            task_id = str(source["task_id"])
            task = self.cache_manager.get_task_by_id(task_id) or {}
            if task.get("status") != "awaiting_cloud_confirmation":
                continue
            try:
                quote = self.quote_repository.get(task_id)
            except CloudQuoteConflict as exc:
                if str(exc) == "quote_not_found":
                    continue
                raise
            if quote.status == "refresh_required":
                stale_sources.append((source, quote))

        failures: list[dict] = []
        for source, quote in stale_sources:
            try:
                self.quote_refresher(quote.task_id)
            except Exception as exc:
                failures.append(
                    {
                        "source_id": source["id"],
                        "task_id": quote.task_id,
                        "title": source["title"],
                        "message": str(exc) or type(exc).__name__,
                    }
                )
        if failures:
            return CollectionQuoteRefreshResult(
                snapshot=None, failures=tuple(failures)
            )
        return CollectionQuoteRefreshResult(
            snapshot=self.get_cloud_quote_snapshot(
                collection_id, owner_user_id=owner_user_id
            ),
            failures=(),
        )

    def confirm_collection_cloud_quotes(
        self,
        collection_id: str,
        *,
        owner_user_id: str,
        transcription_revision: object,
        confirmations: Sequence[CloudQuoteConfirmation | Mapping[str, object]],
        accepted_total: object,
        cloud_dispatcher=None,
    ) -> CollectionQuoteConfirmationResult:
        """Confirm an unchanged full collection quote list or replay it safely."""
        if self.quote_repository is None:
            raise RuntimeError("cloud_quote_repository_required")
        revision = self._parse_revision(transcription_revision)
        accepted = self._parse_nonnegative_decimal(
            accepted_total, error="invalid_collection_cloud_quote_total"
        )
        requested = tuple(
            self._parse_confirmation(confirmation) for confirmation in confirmations
        )
        if accepted != sum(
            (confirmation.accepted_max_cost for confirmation in requested), Decimal("0")
        ):
            raise ValueError("invalid_collection_cloud_quote_total")

        def validate_scope(connection, current):
            self._validate_quote_confirmation_scope(
                connection,
                collection_id=collection_id,
                owner_user_id=owner_user_id,
                transcription_revision=revision,
                confirmations=current,
            )
            task_ids = tuple(item.task_id for item in current)
            placeholders = ",".join("?" for _ in task_ids)
            connection.execute(
                f"""UPDATE task_status
                SET status='queued', progress_json=NULL, error_message=NULL,
                    completed_at=NULL
                WHERE status='awaiting_cloud_confirmation'
                    AND task_id IN ({placeholders})""",
                task_ids,
            )

        queued, created = self.quote_repository.confirm_many_and_queue(
            requested, scope_validator=validate_scope
        )
        if created:
            collection = self.repository.get_collection(collection_id)
            if self.concurrency_controller is not None and collection is not None:
                self.concurrency_controller.update_soft_limits(
                    cloud=int(collection["transcription_concurrency"])
                )
            dispatcher = cloud_dispatcher or self.cloud_dispatcher
            if dispatcher is not None:
                for quote in queued:
                    try:
                        notified = dispatcher.notify(quote.task_id)
                        if notified is False:
                            logger.warning("Cloud dispatcher did not accept queued task {}", quote.task_id)
                    except Exception as exc:
                        logger.warning("Could not notify cloud dispatcher for {}: {}", quote.task_id, exc)
        return CollectionQuoteConfirmationResult(
            status="confirmed" if created else "already_confirmed",
            task_ids=tuple(quote.task_id for quote in queued),
        )

    def stop_collection(
        self, collection_id: str, *, owner_user_id: str
    ) -> CollectionStopResult:
        """Stop only collection work that has not reached a provider."""
        collection = self._get_owned_video_collection(
            collection_id, owner_user_id=owner_user_id
        )
        stopped_count = 0
        in_flight_count = 0
        strategy = collection["transcription_strategy"]

        for source in self.repository.get_sources(collection_id):
            if source.get("source_type") != "video":
                continue
            task_id = str(source["task_id"])
            task = self.cache_manager.get_task_by_id(task_id) or {}
            status = task.get("status")
            if status in {"success", "no_transcript", "failed", "canceled"}:
                continue
            if strategy == "cloud":
                stopped, in_flight = self._stop_cloud_task(task_id)
            else:
                stopped, in_flight = self._stop_local_task(task_id)
            stopped_count += int(stopped)
            in_flight_count += int(in_flight)

        self._wake_stop_waiters()
        return CollectionStopResult(
            collection=self.repository.get_collection(collection_id) or collection,
            stopped_count=stopped_count,
            in_flight_count=in_flight_count,
        )

    def continue_collection(
        self,
        collection_id: str,
        *,
        owner_user_id: str,
        strategy: TranscriptionStrategy,
        requested_concurrency: int,
    ) -> CollectionStartResult:
        """Create fresh tasks for source rows explicitly stopped by this collection."""
        validate_transcription_selection(strategy, requested_concurrency)
        self._get_owned_video_collection(collection_id, owner_user_id=owner_user_id)
        self.repository.update_transcription_preferences(
            collection_id,
            strategy=strategy,
            requested_concurrency=requested_concurrency,
        )

        launches: list[SourceLaunch] = []
        for source in self.repository.get_sources(collection_id):
            if source.get("source_type") != "video":
                continue
            old_task_id = str(source["task_id"])
            old_task = self.cache_manager.get_task_by_id(old_task_id) or {}
            if not self._is_resumable_source_task(old_task):
                continue
            media_id = old_task.get("media_id")
            file_path = old_task.get("source_file_path")
            display_url = old_task.get("url")
            if not all(isinstance(value, str) and value for value in (media_id, file_path, display_url)):
                logger.warning(
                    "Cannot continue collection source {} because its local identity is incomplete",
                    source["id"],
                )
                continue
            task = self.cache_manager.create_task(
                url=display_url,
                use_speaker_recognition=bool(old_task.get("use_speaker_recognition")),
                platform=str(old_task.get("platform") or "generic"),
                media_id=media_id,
                owner_user_id=owner_user_id,
                source_file_path=file_path,
            )
            if not self.repository.replace_source_task_if_current(
                source["id"],
                expected_task_id=old_task_id,
                task_id=task["task_id"],
                view_token=task["view_token"],
            ):
                self._cancel_new_task(task["task_id"], force=True)
                continue
            launches.append(
                SourceLaunch(
                    source_id=str(source["id"]),
                    task_id=str(task["task_id"]),
                    file_path=file_path,
                    original_name=str(source["title"]),
                    display_url=display_url,
                    media_id=media_id,
                    strategy=strategy,
                )
            )

        effective = resolve_effective_concurrency(
            strategy, requested_concurrency, pending_count=len(launches)
        )
        if (
            strategy == "local"
            and effective is not None
            and self.concurrency_controller is not None
        ):
            self.concurrency_controller.update_soft_limits(local=effective)
        return CollectionStartResult(
            sources=tuple(self.repository.get_sources(collection_id)),
            launches=tuple(launches),
            cache_hit_count=0,
            requested_concurrency=requested_concurrency,
            effective_concurrency=effective,
        )

    def _get_owned_video_collection(
        self, collection_id: str, *, owner_user_id: str
    ) -> dict:
        collection = self.repository.get_collection(collection_id)
        if not collection or collection.get("owner_user_id") != owner_user_id:
            raise ValueError("collection_not_found")
        if collection.get("collection_type") != "video_course":
            raise ValueError("invalid_collection_transcription_strategy")
        return collection

    def _stop_local_task(self, task_id: str) -> tuple[bool, bool]:
        def cancel() -> None:
            self._mark_task_resumable_canceled(task_id)

        if self.concurrency_controller is None:
            cancel()
            return True, False
        stopped = self.concurrency_controller.cancel_if_not_active(
            "local", owner_prefix=f"local:{task_id}:", on_cancel=cancel
        )
        return stopped, not stopped

    def _stop_cloud_task(self, task_id: str) -> tuple[bool, bool]:
        if self.quote_repository is None:
            self._mark_task_resumable_canceled(task_id)
            return True, False
        try:
            quote = self.quote_repository.get(task_id)
        except CloudQuoteConflict as exc:
            if str(exc) != "quote_not_found":
                raise
            self._mark_task_resumable_canceled(task_id)
            return True, False
        if quote.status == "consumed":
            return False, True
        if self.quote_repository.cancel(task_id):
            self._mark_task_resumable_canceled(task_id)
            return True, False
        return False, True

    def _mark_task_resumable_canceled(self, task_id: str) -> None:
        self.cache_manager.update_task_status(
            task_id,
            "canceled",
            error_message="用户停止合集解析",
            terminal_evidence=RESUMABLE_EVIDENCE,
        )

    @staticmethod
    def _is_resumable_canceled(task: Mapping[str, Any]) -> bool:
        evidence = (task.get("progress") or {}).get("evidence") or {}
        return (
            task.get("status") == "canceled"
            and evidence.get("collection_resume_allowed") is True
        )

    @classmethod
    def _is_resumable_source_task(cls, task: Mapping[str, Any]) -> bool:
        """Allow explicit recovery of tasks rejected by the old quote cap."""
        if cls._is_resumable_canceled(task):
            return True
        if task.get("status") != "failed":
            return False
        error_message = str(task.get("error_message") or "").strip()
        return error_message in {
            "本地转录失败: budget_exceeded",
            "云端报价准备失败: budget_exceeded",
        }

    def _wake_stop_waiters(self) -> None:
        if self.concurrency_controller is not None:
            self.concurrency_controller.wake_waiters()
        if self.cloud_dispatcher is not None:
            self.cloud_dispatcher.notify()

    @staticmethod
    def _parse_nonnegative_decimal(value: object, *, error: str) -> Decimal:
        if isinstance(value, bool):
            raise ValueError(error)
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(error) from None
        if not parsed.is_finite() or parsed < 0:
            raise ValueError(error)
        return parsed

    @classmethod
    def _parse_confirmation(
        cls, confirmation: CloudQuoteConfirmation | Mapping[str, object]
    ) -> CloudQuoteConfirmation:
        if isinstance(confirmation, CloudQuoteConfirmation):
            task_id = confirmation.task_id
            token = confirmation.token
            accepted_max_cost = confirmation.accepted_max_cost
        elif isinstance(confirmation, Mapping):
            task_id = confirmation.get("task_id")
            token = confirmation.get("token")
            accepted_max_cost = confirmation.get("accepted_max_cost")
        else:
            raise ValueError("invalid_collection_cloud_quote_confirmation")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("invalid_collection_cloud_quote_confirmation")
        if not isinstance(token, str) or not token:
            raise ValueError("invalid_collection_cloud_quote_confirmation")
        return CloudQuoteConfirmation(
            task_id=task_id,
            token=token,
            accepted_max_cost=cls._parse_nonnegative_decimal(
                accepted_max_cost, error="invalid_cloud_quote_amount"
            ),
        )

    @staticmethod
    def _parse_revision(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("invalid_collection_transcription_revision")
        return value

    def _validate_quote_confirmation_scope(
        self,
        connection,
        *,
        collection_id: str,
        owner_user_id: str,
        transcription_revision: int,
        confirmations: Sequence[CloudQuoteConfirmation],
    ) -> None:
        suffix = (
            " FOR UPDATE"
            if getattr(self.quote_repository.database, "dialect", "sqlite") == "postgres"
            else ""
        )
        collection = connection.execute(
            "SELECT * FROM learning_collections WHERE id=?" + suffix,
            (collection_id,),
        ).fetchone()
        if (
            collection is None
            or collection["owner_user_id"] != owner_user_id
            or collection["transcription_strategy"] != "cloud"
            or int(collection["transcription_revision"]) != transcription_revision
        ):
            raise CloudQuoteConflict("collection_cloud_quote_changed")
        source_rows = connection.execute(
            """SELECT task_id FROM learning_collection_sources
            WHERE collection_id=? AND source_type='video'
            ORDER BY position, created_at""" + suffix,
            (collection_id,),
        ).fetchall()
        source_ids = tuple(row["task_id"] for row in source_rows)
        if not source_ids:
            raise CloudQuoteConflict("collection_cloud_quote_changed")
        placeholders = ",".join("?" for _ in source_ids)
        quote_rows = connection.execute(
            "SELECT task_id, status FROM cloud_quotes WHERE task_id IN ("
            + placeholders
            + ")"
            + suffix,
            source_ids,
        ).fetchall()
        quotes_by_task = {row["task_id"]: row["status"] for row in quote_rows}
        active_ids: set[str] = set()
        for task_id in source_ids:
            task = self.cache_manager.get_task_by_id(task_id) or {}
            task_status = task.get("status")
            quote_status = quotes_by_task.get(task_id)
            if task_status in {"success", "canceled"}:
                continue
            if quote_status == "pending" and task_status != "awaiting_cloud_confirmation":
                raise CloudQuoteConflict("collection_cloud_quote_changed")
            if quote_status == "confirmed_queued" and task_status not in {
                "awaiting_cloud_confirmation",
                "queued",
                "processing",
            }:
                raise CloudQuoteConflict("collection_cloud_quote_changed")
            if quote_status not in {"pending", "confirmed_queued"}:
                raise CloudQuoteConflict("collection_cloud_quote_changed")
            active_ids.add(task_id)
        confirmed_ids = {confirmation.task_id for confirmation in confirmations}
        if confirmed_ids != active_ids:
            raise CloudQuoteConflict("collection_cloud_quote_changed")

    def start_sources(
        self,
        *,
        collection_id: str,
        candidates: Sequence[Mapping[str, Any]],
        owner_user_id: str,
        strategy: TranscriptionStrategy,
        requested_concurrency: int,
        use_speaker_recognition: bool,
    ) -> CollectionStartResult:
        validate_transcription_selection(strategy, requested_concurrency)
        sources_by_id: dict[str, dict] = {}
        launches: list[SourceLaunch] = []
        cache_hit_count = 0
        created_task_ids: list[str] = []
        prepared_sources: list[_PreparedSource] = []

        try:
            for candidate in candidates:
                existing = self.repository.get_source_by_content_hash(
                    collection_id, str(candidate["content_sha256"])
                )
                reusable_task, reusable_cache = self._successful_cache(
                    media_id=str(candidate["media_id"]),
                    use_speaker_recognition=use_speaker_recognition,
                )
                is_cache_alias = reusable_task is not None
                if is_cache_alias:
                    task = self.cache_manager.create_cache_alias_task(
                        url=str(candidate["display_url"]),
                        reusable_view_token=str(reusable_task["view_token"]),
                        use_speaker_recognition=use_speaker_recognition,
                        platform="generic",
                        media_id=str(candidate["media_id"]),
                        owner_user_id=owner_user_id,
                    )
                else:
                    task = self.cache_manager.create_task(
                        url=str(candidate["display_url"]),
                        use_speaker_recognition=use_speaker_recognition,
                        platform="generic",
                        media_id=str(candidate["media_id"]),
                        owner_user_id=owner_user_id,
                        source_file_path=str(candidate["file_path"]),
                    )
                created_task_ids.append(task["task_id"])
                if is_cache_alias:
                    self._complete_cache_alias(
                        task_id=task["task_id"],
                        candidate=candidate,
                        reusable_task=reusable_task,
                        reusable_cache=reusable_cache,
                    )
                registration = {
                    "task_id": task["task_id"],
                    "view_token": task["view_token"],
                    "title": str(candidate["original_name"]),
                    "source_type": str(candidate["source_type"]),
                    "position": int(candidate["position"]),
                    "content_sha256": str(candidate["content_sha256"]),
                    "is_cache_alias": is_cache_alias,
                }
                if (
                    existing
                    and is_cache_alias
                    and not self._source_has_complete_cache(existing)
                ):
                    registration.update(
                        replace_source_id=existing["id"],
                        replace_task_id=existing["task_id"],
                    )
                prepared_sources.append(
                    _PreparedSource(
                        candidate=candidate,
                        task=task,
                        is_cache_alias=is_cache_alias,
                        registration=registration,
                    )
                )
            registrations = self.repository.register_source_batch(
                collection_id,
                [prepared.registration for prepared in prepared_sources],
            )
        except Exception:
            self._cancel_prepared_tasks(created_task_ids)
            raise

        for prepared, registration in zip(prepared_sources, registrations):
            candidate = prepared.candidate
            task = prepared.task
            source = registration["source"]
            owns_task = registration["outcome"] in {"inserted", "replaced"}
            sources_by_id[source["id"]] = {
                **source,
                "size": candidate.get("size", 0),
                "reused": prepared.is_cache_alias,
            }
            if not owns_task:
                self._cancel_task_after_commit(task["task_id"], force=True)
                continue
            if prepared.is_cache_alias:
                cache_hit_count += 1
                continue
            launches.append(
                SourceLaunch(
                    source_id=source["id"],
                    task_id=task["task_id"],
                    file_path=str(candidate["file_path"]),
                    original_name=str(candidate["original_name"]),
                    display_url=str(candidate["display_url"]),
                    media_id=str(candidate["media_id"]),
                    strategy=strategy,
                )
            )

        sources = sorted(
            sources_by_id.values(),
            key=lambda item: (
                int(item.get("position") or 0),
                item.get("created_at") or "",
            ),
        )
        effective = resolve_effective_concurrency(
            strategy,
            requested_concurrency,
            pending_count=len(launches),
        )
        return CollectionStartResult(
            sources=tuple(sources),
            launches=tuple(launches),
            cache_hit_count=cache_hit_count,
            requested_concurrency=requested_concurrency,
            effective_concurrency=effective,
        )

    def _successful_cache(
        self, *, media_id: str, use_speaker_recognition: bool
    ) -> tuple[dict | None, dict | None]:
        task = self.cache_manager.get_existing_task_by_media(
            "generic", media_id, use_speaker_recognition
        )
        if not task or task.get("status") != "success":
            return None, None
        cache = self.cache_manager.get_cache(
            platform="generic",
            media_id=media_id,
            use_speaker_recognition=use_speaker_recognition,
            exact_speaker_match=True,
        )
        if not self.cache_manager.cache_has_final_artifacts(cache):
            return None, None
        return task, cache

    def _complete_cache_alias(
        self,
        *,
        task_id: str,
        candidate: Mapping[str, Any],
        reusable_task: Mapping[str, Any],
        reusable_cache: Mapping[str, Any],
    ) -> None:
        self.cache_manager.update_task_status(
            task_id,
            "success",
            platform="generic",
            media_id=str(candidate["media_id"]),
            title=str(candidate["original_name"]),
            author=(
                reusable_task.get("author")
                or reusable_cache.get("author")
                or "本地上传"
            ),
            cache_id=reusable_task.get("cache_id") or reusable_cache.get("id"),
            source_file_path=str(candidate["file_path"]),
            terminal_evidence={
                "cache_hit": True,
                "source_task_id": reusable_task["task_id"],
            },
        )

    def _cancel_prepared_tasks(self, task_ids: Sequence[str]) -> None:
        for task_id in task_ids:
            try:
                self._cancel_new_task(task_id, force=True)
            except Exception as exc:
                logger.error(
                    "Failed to cancel collection task after batch rollback: {} ({})",
                    task_id,
                    exc,
                )

    def _cancel_task_after_commit(self, task_id: str, *, force: bool) -> None:
        try:
            self._cancel_new_task(task_id, force=force)
        except Exception as exc:
            logger.warning(
                "Failed to cancel unreferenced collection task after batch commit: "
                "{} ({})",
                task_id,
                exc,
            )

    def _source_has_complete_cache(self, source: Mapping[str, Any]) -> bool:
        task = self.cache_manager.get_task_by_id(str(source["task_id"])) or {}
        if task.get("status") != "success":
            return False
        media_id = task.get("media_id")
        platform = task.get("platform")
        if not media_id or not platform:
            return False
        cache = self.cache_manager.get_cache(
            platform=platform,
            media_id=media_id,
            use_speaker_recognition=bool(task.get("use_speaker_recognition")),
            exact_speaker_match=True,
        )
        return self.cache_manager.cache_has_final_artifacts(cache)

    def _cancel_new_task(self, task_id: str, *, force: bool = False) -> None:
        self.cache_manager.update_task_status(
            task_id,
            "canceled",
            force=force,
            error_message="合集内相同内容已存在",
        )


def validate_transcription_selection(
    strategy: str,
    requested: int,
) -> None:
    """Validate a requested strategy and its process-wide concurrency."""
    if strategy not in STRATEGY_HARD_LIMITS:
        raise ValueError("invalid_transcription_strategy")
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise ValueError("invalid_transcription_concurrency")
    if not 1 <= requested <= STRATEGY_HARD_LIMITS[strategy]:
        raise ValueError(f"invalid_{strategy}_transcription_concurrency")


def default_requested_concurrency(strategy: str, visible_count: int) -> int:
    """Return the requested default without applying runtime pending counts."""
    if strategy == "local":
        return 1
    if strategy == "cloud":
        return min(5, max(1, int(visible_count)))
    raise ValueError("invalid_transcription_strategy")


def resolve_effective_concurrency(
    strategy: str,
    requested: int,
    *,
    pending_count: int,
) -> int | None:
    """Clamp a valid request to work that can actually be scheduled."""
    validate_transcription_selection(strategy, requested)
    if pending_count <= 0:
        return None
    return min(requested, pending_count)
