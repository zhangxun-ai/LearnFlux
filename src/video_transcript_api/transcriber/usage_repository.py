"""SQLite authority for remote ASR usage and recovery state."""

from __future__ import annotations

import os
import json
import sqlite3
from collections.abc import Collection
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .control_database import SQLiteControlDatabase


class UsageRepositoryError(Exception):
    """A safe repository error whose string form never includes raw details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NewASRAttempt:
    """Immutable inputs reserved before a remote ASR submission."""

    task_id: str
    model: str
    estimated_quantity: Decimal
    unit_price: Decimal
    estimated_cost: Decimal
    owner_key: str
    sample_sha256: str
    platform: str
    media_id: str
    output_name: str
    continuation_json: str | None = None


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """Public, redacted representation of an ASR usage event."""

    id: str
    attempt_no: int
    idempotency_key: str
    task_id: str
    step: str
    provider: str
    model: str
    estimated_quantity: str
    reported_quantity: str | None
    unit: str
    currency: str
    unit_price: str
    estimated_cost: str
    calculated_cost: str | None
    billed_cost: str | None
    remote_status: str
    materialization_status: str
    elapsed_seconds: str | None
    error_code: str | None
    owner_key: str
    sample_sha256: str
    platform: str
    media_id: str
    output_name: str
    lease_owner: str | None
    lease_expires_at: str | None
    lease_heartbeat_at: str | None
    continuation_json: str | None
    postprocess_key: str | None
    postprocess_status: str | None
    created_at: str
    updated_at: str

    @property
    def status(self) -> str:
        """Derive the external status without persisting a third status column."""
        if self.remote_status == "succeeded":
            return {
                "pending": "remote_succeeded",
                "failed": "materialization_failed",
                "succeeded": "succeeded",
            }.get(self.materialization_status, self.remote_status)
        if self.remote_status == "result_expired":
            return "remote_result_expired"
        return self.remote_status

    def serialize(self) -> dict[str, object]:
        """Return only public fields."""
        return {
            field: getattr(self, field)
            for field in UsageEvent.__dataclass_fields__
            if field != "continuation_json"
        } | {"status": self.status}


@dataclass(frozen=True, slots=True)
class RecoveryUsageEvent(UsageEvent):
    """Private recovery view containing the remote provider task identifier."""

    provider_task_id: str | None


_PUBLIC_COLUMNS = tuple(UsageEvent.__dataclass_fields__)
_TERMINAL_REMOTE_STATUSES = {"failed", "result_expired", "closed_unreconciled"}
REMOTE_CAPACITY_STATUSES = {
    "submitting",
    "submitted",
    "polling_unknown",
    "submission_unknown",
}
_ALLOWED_ERROR_CODES = {
    "provider_failed",
    "media_changed_before_submit",
    "local_preflight_failed",
    "upload_failed",
    "submission_timeout",
    "polling_timeout",
    "materialization_failed",
    "result_expired",
    "reported_usage_exceeds_reservation",
    "closed_unreconciled",
}


def _decimal_text(value: Decimal | str | int) -> str:
    decimal = Decimal(value)
    if not decimal.is_finite() or decimal < 0:
        raise UsageRepositoryError("invalid_decimal")
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _validated_continuation(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
        raise UsageRepositoryError("invalid_continuation")
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        raise UsageRepositoryError("invalid_continuation") from None
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise UsageRepositoryError("invalid_continuation")
    forbidden = {
        "credential",
        "api_key",
        "authorization",
        "webhook",
        "signed_url",
        "source_path",
        "local_path",
        "provider_response",
    }
    def contains_forbidden_key(item: object) -> bool:
        if isinstance(item, dict):
            return any(
                str(key).lower() in forbidden
                or contains_forbidden_key(nested)
                for key, nested in item.items()
            )
        if isinstance(item, list):
            return any(contains_forbidden_key(nested) for nested in item)
        return False

    if contains_forbidden_key(payload):
        raise UsageRepositoryError("invalid_continuation")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _time_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise UsageRepositoryError("invalid_time")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class UsageEventRepository:
    """Persist ASR usage events in the selected control database."""

    def __init__(self, db_path: str | os.PathLike[str] | object) -> None:
        if hasattr(db_path, "connect") and hasattr(db_path, "transaction"):
            self.database = db_path
            self.db_path = getattr(db_path, "path", None)
        else:
            self.database = SQLiteControlDatabase(db_path)
            self.db_path = str(db_path)
        self._initialize()

    def _connect(self):
        return self.database.connect()

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY,
                    attempt_no INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    step TEXT NOT NULL DEFAULT 'asr',
                    provider TEXT NOT NULL DEFAULT 'aliyun',
                    model TEXT NOT NULL,
                    estimated_quantity TEXT NOT NULL,
                    reported_quantity TEXT,
                    unit TEXT NOT NULL DEFAULT 'audio_second',
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    unit_price TEXT NOT NULL,
                    estimated_cost TEXT NOT NULL,
                    calculated_cost TEXT,
                    billed_cost TEXT,
                    remote_status TEXT NOT NULL,
                    materialization_status TEXT NOT NULL,
                    elapsed_seconds TEXT,
                    error_code TEXT,
                    owner_key TEXT NOT NULL,
                    provider_task_id TEXT,
                    sample_sha256 TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    media_id TEXT NOT NULL,
                    output_name TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    lease_heartbeat_at TEXT,
                    continuation_json TEXT,
                    postprocess_key TEXT,
                    postprocess_status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_usage_events_task_attempt
                ON usage_events(task_id, step, attempt_no)
                """
            )

    def reserve_attempt(
        self, attempt: NewASRAttempt, *, new_paid_attempt: bool = False
    ) -> UsageEvent:
        """Reserve one paid attempt, serializing concurrent first delivery."""
        with self.database.transaction() as connection:
            return self._reserve_attempt_on(
                connection, attempt, new_paid_attempt=new_paid_attempt
            )

    def _reserve_attempt_on(
        self, connection, attempt: NewASRAttempt, *, new_paid_attempt: bool = False
    ) -> UsageEvent:
        required = {
            "task_id": attempt.task_id,
            "platform": attempt.platform,
            "media_id": attempt.media_id,
            "sample_sha256": attempt.sample_sha256,
        }
        for field, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise UsageRepositoryError(f"missing_{field}")
        output_name = attempt.output_name
        if (
            not output_name
            or output_name in {".", ".."}
            or os.path.isabs(output_name)
            or "/" in output_name
            or "\\" in output_name
        ):
            raise UsageRepositoryError("invalid_output_name")

        estimated_quantity = _decimal_text(attempt.estimated_quantity)
        unit_price = _decimal_text(attempt.unit_price)
        estimated_cost = _decimal_text(attempt.estimated_cost)
        continuation_json = _validated_continuation(attempt.continuation_json)
        latest = connection.execute(
            """
            SELECT * FROM usage_events
            WHERE task_id = ? AND step = 'asr'
            ORDER BY attempt_no DESC LIMIT 1
            """,
            (attempt.task_id,),
        ).fetchone()
        if latest is not None:
            is_terminal = latest["remote_status"] in _TERMINAL_REMOTE_STATUSES
            if not is_terminal:
                if new_paid_attempt:
                    raise UsageRepositoryError("attempt_already_active")
                if latest["continuation_json"] != continuation_json:
                    raise UsageRepositoryError("continuation_identity_conflict")
                return self._public_event(latest)
            if not new_paid_attempt:
                raise UsageRepositoryError("new_paid_attempt_required")
            attempt_no = latest["attempt_no"] + 1
        else:
            attempt_no = 1

        idempotency_key = sha256(
            f"{attempt.task_id}:asr:{attempt_no}:aliyun:{attempt.model}".encode()
        ).hexdigest()
        event_id = str(uuid4())
        now = _utc_now()
        connection.execute(
            """
            INSERT INTO usage_events (
                id, attempt_no, idempotency_key, task_id, step, provider,
                model, estimated_quantity, unit, currency, unit_price,
                estimated_cost, remote_status, materialization_status,
                owner_key, sample_sha256, platform, media_id, output_name,
                continuation_json, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, 'asr', 'aliyun', ?, ?, 'audio_second', 'CNY',
                ?, ?, 'reserved', 'pending', ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                event_id,
                attempt_no,
                idempotency_key,
                attempt.task_id,
                attempt.model,
                estimated_quantity,
                unit_price,
                estimated_cost,
                attempt.owner_key,
                attempt.sample_sha256,
                attempt.platform,
                attempt.media_id,
                attempt.output_name,
                continuation_json,
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM usage_events WHERE id = ?", (event_id,)
        ).fetchone()
        return self._public_event(row)

    @staticmethod
    def _public_event(row: sqlite3.Row) -> UsageEvent:
        return UsageEvent(**{column: row[column] for column in _PUBLIC_COLUMNS})

    @staticmethod
    def _validate_error_code(error_code: str | None) -> None:
        if error_code is not None and error_code not in _ALLOWED_ERROR_CODES:
            raise UsageRepositoryError("invalid_error_code")

    def record_remote_failure(
        self,
        event_id: str,
        lease_owner: str,
        *,
        now: datetime,
        error_code: str | None,
    ) -> bool:
        """Record a claimed remote failure while its lease is still active."""
        self._validate_error_code(error_code)
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'failed',
                    materialization_status = 'not_applicable',
                    error_code = ?, lease_owner = NULL,
                    lease_expires_at = NULL, lease_heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ?
                    AND remote_status IN ('submitting', 'submitted', 'polling_unknown')
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (error_code, now_text, event_id, lease_owner, now_text),
            )
            return cursor.rowcount == 1

    def get_event(self, event_id: str) -> UsageEvent:
        """Read a public event without the provider task identifier."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM usage_events WHERE id = ?", (event_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise UsageRepositoryError("event_not_found")
        return self._public_event(row)

    def find_latest_event_by_task_id(self, task_id: str) -> UsageEvent | None:
        """Return the latest ASR attempt, including terminal failures."""
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM usage_events
                WHERE task_id = ? AND step = 'asr'
                ORDER BY attempt_no DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        return self._public_event(row) if row is not None else None

    def claim_submission(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Claim a reserved submission exactly once."""
        if not lease_owner:
            raise UsageRepositoryError("invalid_lease_owner")
        now_text = _time_text(now)
        expires_text = _time_text(now + timedelta(seconds=60))
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'submitting', lease_owner = ?,
                    lease_expires_at = ?, lease_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND remote_status = 'reserved'
                """,
                (
                    lease_owner,
                    expires_text,
                    now_text,
                    now_text,
                    event_id,
                ),
            )
            return cursor.rowcount == 1

    def heartbeat_lease(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Extend a live lease while its owner is doing recoverable work."""
        now_text = _time_text(now)
        expires_text = _time_text(now + timedelta(seconds=60))
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET lease_expires_at = ?, lease_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND (
                    remote_status IN ('submitting', 'submitted', 'polling_unknown')
                    OR (
                        remote_status = 'succeeded'
                        AND materialization_status IN ('pending', 'failed')
                    )
                )
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    expires_text,
                    now_text,
                    now_text,
                    event_id,
                    lease_owner,
                    now_text,
                ),
            )
            return cursor.rowcount == 1

    def heartbeat_submission(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Backward-compatible alias for the generic lease heartbeat."""
        return self.heartbeat_lease(event_id, lease_owner, now=now)

    def record_submitted(
        self,
        event_id: str,
        lease_owner: str,
        *,
        now: datetime,
        provider_task_id: str,
    ) -> bool:
        """Atomically persist the private task ID and submitted state."""
        if not provider_task_id:
            raise UsageRepositoryError("invalid_provider_task_id")
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET provider_task_id = ?, remote_status = 'submitted', updated_at = ?
                WHERE id = ? AND remote_status = 'submitting'
                    AND lease_owner = ? AND lease_expires_at > ?
                    AND provider_task_id IS NULL
                """,
                (
                    provider_task_id,
                    now_text,
                    event_id,
                    lease_owner,
                    now_text,
                ),
            )
            return cursor.rowcount == 1

    def claim_recovery(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Claim expired or unowned polling/materialization recovery work."""
        if not lease_owner:
            raise UsageRepositoryError("invalid_lease_owner")
        now_text = _time_text(now)
        expires_text = _time_text(now + timedelta(seconds=60))
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET lease_owner = ?, lease_expires_at = ?,
                    lease_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND (
                    remote_status IN ('submitted', 'polling_unknown')
                    OR (
                        remote_status = 'succeeded'
                        AND materialization_status IN ('pending', 'failed')
                    )
                ) AND (
                    (lease_owner IS NULL AND lease_expires_at IS NULL)
                    OR lease_expires_at <= ?
                )
                """,
                (
                    lease_owner,
                    expires_text,
                    now_text,
                    now_text,
                    event_id,
                    now_text,
                ),
            )
            return cursor.rowcount == 1

    def get_recovery_event(self, event_id: str) -> RecoveryUsageEvent:
        """Read the private event view used only by recovery workers."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM usage_events WHERE id = ?", (event_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise UsageRepositoryError("event_not_found")
        values = {column: row[column] for column in _PUBLIC_COLUMNS}
        return RecoveryUsageEvent(
            **values, provider_task_id=row["provider_task_id"]
        )

    def find_recoverable_event_by_task_id(
        self, task_id: str
    ) -> RecoveryUsageEvent | None:
        """Find the active poll-only work for one re-entered LearnFlux task."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM usage_events
                WHERE task_id = ? AND step = 'asr' AND (
                    remote_status IN ('submitted', 'polling_unknown')
                    OR (
                        remote_status = 'succeeded'
                        AND materialization_status IN ('pending', 'failed')
                    )
                )
                ORDER BY attempt_no DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return RecoveryUsageEvent(
            **{column: row[column] for column in _PUBLIC_COLUMNS},
            provider_task_id=row["provider_task_id"],
        )

    def list_recoverable_events(self) -> list[RecoveryUsageEvent]:
        """Return only same-task polling or materialization recovery work."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM usage_events
                WHERE remote_status IN ('submitted', 'polling_unknown')
                    OR (
                        remote_status = 'succeeded'
                        AND materialization_status IN ('pending', 'failed')
                    )
                ORDER BY created_at, attempt_no, id
                """
            ).fetchall()
        return [
            RecoveryUsageEvent(
                **{column: row[column] for column in _PUBLIC_COLUMNS},
                provider_task_id=row["provider_task_id"],
            )
            for row in rows
        ]

    def list_remote_capacity_attempt_ids(self) -> list[str]:
        """Return attempts that may still occupy provider-side capacity."""
        placeholders = ",".join("?" for _ in REMOTE_CAPACITY_STATUSES)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT id FROM usage_events
                WHERE remote_status IN ({placeholders})
                ORDER BY created_at, attempt_no, id""",
                tuple(sorted(REMOTE_CAPACITY_STATUSES)),
            ).fetchall()
        return [row["id"] for row in rows]

    def remote_attempt_occupies_capacity(self, event_id: str) -> bool:
        """Check one event against the durable provider-capacity states."""
        placeholders = ",".join("?" for _ in REMOTE_CAPACITY_STATUSES)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""SELECT 1 FROM usage_events
                WHERE id=? AND remote_status IN ({placeholders})""",
                (event_id, *sorted(REMOTE_CAPACITY_STATUSES)),
            ).fetchone()
        return row is not None

    def fail_orphan_reserved(
        self,
        *,
        created_before: datetime,
        excluded_event_ids: Collection[str] = (),
    ) -> list[UsageEvent]:
        """Fail only pre-startup reservations that never reached submission."""
        cutoff = _time_text(created_before)
        excluded_ids = tuple(dict.fromkeys(excluded_event_ids))
        exclusion_sql = ""
        parameters: tuple[object, ...] = (cutoff,)
        if excluded_ids:
            placeholders = ",".join("?" for _ in excluded_ids)
            exclusion_sql = f" AND id NOT IN ({placeholders})"
            parameters = (cutoff, *excluded_ids)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""SELECT id FROM usage_events
                WHERE remote_status='reserved' AND created_at < ?
                    {exclusion_sql}
                ORDER BY created_at, attempt_no, id""",
                parameters,
            ).fetchall()
            event_ids = [row["id"] for row in rows]
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                connection.execute(
                    f"""UPDATE usage_events
                    SET remote_status='failed',
                        materialization_status='not_applicable',
                        error_code='local_preflight_failed', updated_at=?
                    WHERE remote_status='reserved'
                        AND id IN ({placeholders})""",
                    (cutoff, *event_ids),
                )
                updated_rows = connection.execute(
                    f"SELECT * FROM usage_events WHERE id IN ({placeholders})",
                    event_ids,
                ).fetchall()
                by_id = {row["id"]: self._public_event(row) for row in updated_rows}
                events = [by_id[event_id] for event_id in event_ids]
            else:
                events = []
            connection.commit()
            return events
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def next_submission_lease_expiry(
        self, *, now: datetime | None = None
    ) -> datetime | None:
        """Return the nearest live submit lease that needs a timed wake-up."""
        current = now or datetime.now(UTC)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT MIN(lease_expires_at) AS expiry FROM usage_events
                WHERE remote_status='submitting'
                    AND provider_task_id IS NULL
                    AND lease_expires_at > ?""",
                (_time_text(current),),
            ).fetchone()
        return datetime.fromisoformat(row["expiry"]) if row and row["expiry"] else None

    def freeze_stale_submissions(self, *, now: datetime) -> int:
        """Atomically freeze all expired submissions that lack a task ID."""
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'submission_unknown',
                    materialization_status = 'not_applicable',
                    error_code = 'submission_timeout',
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL, updated_at = ?
                WHERE remote_status = 'submitting'
                    AND provider_task_id IS NULL
                    AND lease_expires_at <= ?
                """,
                (now_text, now_text),
            )
            return cursor.rowcount

    def freeze_claimed_submission_unknown(
        self,
        event_id: str,
        lease_owner: str,
        *,
        error_code: str | None,
        now: datetime,
    ) -> bool:
        """Freeze an indeterminate submit while its current lease is valid."""
        self._validate_error_code(error_code)
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'submission_unknown',
                    materialization_status = 'not_applicable', error_code = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND remote_status = 'submitting'
                    AND provider_task_id IS NULL
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (error_code, now_text, event_id, lease_owner, now_text),
            )
            return cursor.rowcount == 1

    def freeze_submission_unknown(
        self, event_id: str, *, error_code: str | None, now: datetime
    ) -> bool:
        """Freeze a stale submission when no provider task ID was obtained."""
        self._validate_error_code(error_code)
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'submission_unknown',
                    materialization_status = 'not_applicable', error_code = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND remote_status = 'submitting'
                    AND provider_task_id IS NULL
                    AND lease_expires_at <= ?
                """,
                (error_code, now_text, event_id, now_text),
            )
            return cursor.rowcount == 1

    def mark_polling_unknown(
        self,
        event_id: str,
        lease_owner: str,
        *,
        now: datetime,
        error_code: str | None,
    ) -> bool:
        """Retain a provider task ID when polling cannot establish a result."""
        self._validate_error_code(error_code)
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'polling_unknown',
                    materialization_status = 'pending', error_code = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ? AND remote_status IN ('submitted', 'polling_unknown')
                    AND provider_task_id IS NOT NULL
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (error_code, now_text, event_id, lease_owner, now_text),
            )
            return cursor.rowcount == 1

    def mark_result_expired(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Record that a claimed provider result can no longer be recovered."""
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'result_expired',
                    materialization_status = 'failed',
                    error_code = 'result_expired',
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND (
                    remote_status IN ('submitted', 'polling_unknown')
                    OR (
                        remote_status = 'succeeded'
                        AND materialization_status IN ('pending', 'failed')
                    )
                )
                    AND provider_task_id IS NOT NULL
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (now_text, event_id, lease_owner, now_text),
            )
            return cursor.rowcount == 1

    def close_submission_unknown(self, event_id: str) -> bool:
        """Manually close an unreconciled submission with no provider task ID."""
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET remote_status = 'closed_unreconciled',
                    materialization_status = 'not_applicable',
                    error_code = 'closed_unreconciled',
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND remote_status = 'submission_unknown'
                    AND provider_task_id IS NULL
                """,
                (_utc_now(), event_id),
            )
            return cursor.rowcount == 1

    def record_remote_success(
        self,
        event_id: str,
        lease_owner: str,
        *,
        now: datetime,
        reported_quantity: Decimal,
        elapsed_seconds: Decimal,
    ) -> bool:
        """Record actual usage and calculate exact Decimal cost."""
        quantity_text = _decimal_text(reported_quantity)
        elapsed_text = _decimal_text(elapsed_seconds)
        now_text = _time_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT unit_price, estimated_quantity FROM usage_events
                WHERE id = ? AND remote_status IN ('submitted', 'polling_unknown')
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (event_id, lease_owner, now_text),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            calculated_cost = _decimal_text(
                Decimal(quantity_text) * Decimal(row["unit_price"])
            )
            error_code = (
                "reported_usage_exceeds_reservation"
                if Decimal(quantity_text) > Decimal(row["estimated_quantity"])
                else None
            )
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET reported_quantity = ?, calculated_cost = ?,
                    elapsed_seconds = ?, remote_status = 'succeeded',
                    materialization_status = 'pending', error_code = ?,
                    updated_at = ?
                WHERE id = ? AND remote_status IN ('submitted', 'polling_unknown')
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    quantity_text,
                    calculated_cost,
                    elapsed_text,
                    error_code,
                    now_text,
                    event_id,
                    lease_owner,
                    now_text,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def record_materialization_failed(
        self,
        event_id: str,
        lease_owner: str,
        *,
        now: datetime,
        error_code: str | None,
    ) -> bool:
        """Mark local result materialization failed without changing usage."""
        self._validate_error_code(error_code)
        now_text = _time_text(now)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET materialization_status = 'failed', error_code = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL, updated_at = ?
                WHERE id = ? AND remote_status = 'succeeded'
                    AND materialization_status IN ('pending', 'failed')
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (error_code, now_text, event_id, lease_owner, now_text),
            )
            return cursor.rowcount == 1

    def record_materialization_succeeded(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Complete materialization and atomically create its stable outbox key."""
        postprocess_key = sha256(
            f"{event_id}:postprocess:v1".encode()
        ).hexdigest()
        now_text = _time_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT reported_quantity, estimated_quantity
                FROM usage_events
                WHERE id = ? AND remote_status = 'succeeded'
                    AND materialization_status IN ('pending', 'failed')
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (event_id, lease_owner, now_text),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            error_code = (
                "reported_usage_exceeds_reservation"
                if row["reported_quantity"] is not None
                and Decimal(row["reported_quantity"])
                > Decimal(row["estimated_quantity"])
                else None
            )
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET materialization_status = 'succeeded', error_code = ?,
                    postprocess_key = COALESCE(postprocess_key, ?),
                    postprocess_status = COALESCE(postprocess_status, 'pending'),
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ? AND remote_status = 'succeeded'
                    AND materialization_status IN ('pending', 'failed')
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    error_code,
                    postprocess_key,
                    now_text,
                    event_id,
                    lease_owner,
                    now_text,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def claim_postprocess(
        self,
        event_id: str,
        lease_owner: str = "legacy-postprocess",
        *,
        now: datetime | None = None,
    ) -> bool:
        """Claim pending or expired postprocess work with a 60-second lease."""
        if not lease_owner:
            raise UsageRepositoryError("invalid_lease_owner")
        current = now or datetime.now(UTC)
        now_text = _time_text(current)
        expires_text = _time_text(current + timedelta(seconds=60))
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events SET postprocess_status = 'processing',
                    lease_owner = ?, lease_expires_at = ?,
                    lease_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND materialization_status = 'succeeded'
                    AND (
                        postprocess_status = 'pending'
                        OR (
                            postprocess_status = 'processing'
                            AND lease_expires_at <= ?
                        )
                    )
                """,
                (
                    lease_owner,
                    expires_text,
                    now_text,
                    now_text,
                    event_id,
                    now_text,
                ),
            )
            return cursor.rowcount == 1

    def heartbeat_postprocess(
        self, event_id: str, lease_owner: str, *, now: datetime
    ) -> bool:
        """Keep one postprocess claim alive during an external LLM call."""
        now_text = _time_text(now)
        expires_text = _time_text(now + timedelta(seconds=60))
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events SET lease_expires_at = ?,
                    lease_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND postprocess_status = 'processing'
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    expires_text,
                    now_text,
                    now_text,
                    event_id,
                    lease_owner,
                    now_text,
                ),
            )
            return cursor.rowcount == 1

    def complete_postprocess(
        self,
        event_id: str,
        lease_owner: str = "legacy-postprocess",
        *,
        now: datetime | None = None,
    ) -> bool:
        """Complete postprocess only for the current unexpired owner."""
        current = now or datetime.now(UTC)
        now_text = _time_text(current)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET postprocess_status = 'completed', lease_owner = NULL,
                    lease_expires_at = NULL, lease_heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ? AND postprocess_status = 'processing'
                    AND lease_owner = ? AND lease_expires_at > ?
                """,
                (now_text, event_id, lease_owner, now_text),
            )
            return cursor.rowcount == 1

    def list_pending_postprocess(
        self, *, now: datetime | None = None
    ) -> list[UsageEvent]:
        """List pending and expired-processing outbox rows for redelivery."""
        now_text = _time_text(now or datetime.now(UTC))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM usage_events
                WHERE materialization_status = 'succeeded'
                    AND continuation_json IS NOT NULL
                    AND (
                        postprocess_status = 'pending'
                        OR (
                            postprocess_status = 'processing'
                            AND lease_expires_at <= ?
                        )
                    )
                ORDER BY created_at, attempt_no, id
                """,
                (now_text,),
            ).fetchall()
        return [self._public_event(row) for row in rows]

    def list_protected_task_ids(
        self,
        *,
        now: datetime | None = None,
        retention_days: int = 30,
    ) -> set[str]:
        """Return LearnFlux tasks that generic recovery must not fail."""
        current = now or datetime.now(UTC)
        cutoff = _time_text(current - timedelta(days=retention_days))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT task_id FROM usage_events
                WHERE remote_status IN (
                    'reserved', 'submitting', 'submitted', 'polling_unknown'
                )
                OR (
                    remote_status = 'succeeded'
                    AND (
                        materialization_status IN ('pending', 'failed')
                        OR COALESCE(postprocess_status, 'pending') != 'completed'
                    )
                )
                OR (
                    remote_status IN (
                        'submission_unknown', 'closed_unreconciled',
                        'result_expired'
                    )
                    AND updated_at >= ?
                )
                """,
                (cutoff,),
            ).fetchall()
        return {row["task_id"] for row in rows}

    def list_protected_snapshot_roots(
        self,
        temp_root: str | os.PathLike[str],
        *,
        now: datetime | None = None,
        retention_days: int = 30,
    ) -> set[Path]:
        """Return exact attempt roots still inside state-specific retention."""
        current = now or datetime.now(UTC)
        cutoff = _time_text(current - timedelta(days=retention_days))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT task_id, attempt_no FROM usage_events
                WHERE (
                    remote_status IN (
                        'reserved', 'submitting', 'submitted', 'polling_unknown'
                    )
                    OR (
                        remote_status = 'succeeded'
                        AND materialization_status IN ('pending', 'failed')
                    )
                    OR remote_status IN (
                        'submission_unknown', 'closed_unreconciled',
                        'result_expired'
                    )
                )
                AND created_at >= ?
                """,
                (cutoff,),
            ).fetchall()
        base = Path(temp_root) / "remote_asr"
        return {
            base
            / sha256(row["task_id"].encode("utf-8")).hexdigest()
            / str(row["attempt_no"])
            for row in rows
        }
