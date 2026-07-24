"""Durable task and upload control state for transcription ingress."""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from .cloud_quote_repository import CloudQuoteRepository, NewCloudQuote
from .control_database import PostgresControlDatabase, SQLiteControlDatabase
from .usage_repository import NewASRAttempt, UsageEventRepository
from ..utils.task_progress import build_progress


class ControlStoreConflict(RuntimeError):
    """A fail-closed state conflict represented by a safe code."""


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ControlStoreConflict("invalid_time")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _safe_payload(payload: Mapping[str, object]) -> str:
    if not isinstance(payload, Mapping) or payload.get("version") != 1:
        raise ControlStoreConflict("invalid_job_payload")
    forbidden = {
        "credential",
        "api_key",
        "authorization",
        "webhook",
        "signed_url",
        "source_path",
        "local_path",
        "provider_response",
        "remote_task_id",
    }

    def contains_forbidden(value: object) -> bool:
        if isinstance(value, Mapping):
            return any(
                str(key).lower() in forbidden or contains_forbidden(nested)
                for key, nested in value.items()
            )
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        return False

    if contains_forbidden(payload):
        raise ControlStoreConflict("invalid_job_payload")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 65536:
        raise ControlStoreConflict("invalid_job_payload")
    return encoded


@dataclass(frozen=True, slots=True)
class TranscriptionJob:
    task_id: str
    owner_user_id: str
    source_kind: str
    source_ref: str
    strategy: str
    payload_json: str
    status: str
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UploadSession:
    id: str
    owner_user_id: str
    object_key: str
    status: str
    max_bytes: int
    actual_bytes: int | None
    expires_at: datetime
    task_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QuoteBackedReservedAttempt:
    """Minimal durable inputs for resuming one consumed cloud quote."""

    event_id: str
    task_id: str
    attempt_no: int
    media_ref: str
    media_sha256: str
    duration_seconds: Decimal
    max_cost: Decimal
    continuation_json: str | None


class _TranscriptionControlStore:
    """Shared task delivery and upload-session behavior for one database."""

    def __init__(self, database, *, lease_seconds: int = 60) -> None:
        self.database = database
        self.lease_seconds = lease_seconds
        self._initialize()
        self.quote_repository = CloudQuoteRepository(database)
        self.usage_repository = UsageEventRepository(database)

    def _initialize(self) -> None:
        with self.database.transaction() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_status (
                    task_id TEXT PRIMARY KEY,
                    view_token TEXT NOT NULL,
                    url TEXT NOT NULL,
                    owner_user_id TEXT,
                    status TEXT NOT NULL,
                    platform TEXT,
                    media_id TEXT,
                    use_speaker_recognition INTEGER NOT NULL DEFAULT 0,
                    download_url TEXT,
                    title TEXT,
                    author TEXT,
                    cache_id INTEGER,
                    error_message TEXT,
                    progress_json TEXT,
                    source_file_path TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transcription_jobs (
                    task_id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_sessions (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    object_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    max_bytes INTEGER NOT NULL,
                    actual_bytes INTEGER,
                    expires_at TEXT NOT NULL,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create_task(
        self,
        *,
        url: str,
        use_speaker_recognition: bool = False,
        download_url: str | None = None,
        platform: str | None = None,
        media_id: str | None = None,
        force_new_view_token: bool = False,
        owner_user_id: str | None = None,
    ) -> dict[str, str]:
        del force_new_view_token
        task_id = str(uuid.uuid4())
        view_token = secrets.token_urlsafe(24)
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO task_status
                (task_id, view_token, url, owner_user_id, status, platform,
                 media_id, use_speaker_recognition, download_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    view_token,
                    url,
                    owner_user_id,
                    platform,
                    media_id,
                    int(use_speaker_recognition),
                    download_url,
                    _iso(now),
                    _iso(now),
                ),
            )
        return {"task_id": task_id, "view_token": view_token}

    def update_task_status(self, task_id: str, status: str, **fields) -> None:
        allowed = {
            "platform",
            "media_id",
            "title",
            "author",
            "cache_id",
            "download_url",
            "error_message",
            "source_file_path",
        }
        assignments = ["status=?", "updated_at=?"]
        parameters: list[object] = [status, _iso(datetime.now(UTC))]
        for name in allowed:
            value = fields.get(name)
            if value is not None:
                assignments.append(f"{name}=?")
                parameters.append(value)
        if status in {"success", "failed", "canceled"}:
            assignments.append("completed_at=?")
            parameters.append(_iso(datetime.now(UTC)))
        parameters.append(task_id)
        force = bool(fields.get("force", False))
        terminal_guard = "" if force else " AND status NOT IN ('success','failed','canceled')"
        with self.database.transaction() as connection:
            connection.execute(
                f"UPDATE task_status SET {', '.join(assignments)} WHERE task_id=?{terminal_guard}",
                tuple(parameters),
            )

    def get_task_by_id(self, task_id: str) -> dict[str, object] | None:
        return self.get_task(task_id)

    def update_task_progress(
        self,
        task_id: str,
        *,
        stage: str,
        stage_label: str | None = None,
        fraction: float | None = None,
        basis: str = "stage_transition",
        confidence: str = "low",
        evidence: dict | None = None,
        eta_seconds: int | None = None,
        message: str | None = None,
    ) -> dict[str, object]:
        progress = build_progress(
            stage=stage,
            stage_label=stage_label,
            fraction=fraction,
            basis=basis,
            confidence=confidence,
            evidence=evidence,
            eta_seconds=eta_seconds,
            message=message,
        )
        now = _iso(datetime.now(UTC))
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE task_status SET progress_json=?, updated_at=?
                WHERE task_id=? AND status NOT IN ('success','failed','canceled')""",
                (json.dumps(progress, ensure_ascii=False), now, task_id),
            )
        return progress

    def get_task_by_view_token(self, view_token: str) -> dict[str, object] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                """SELECT * FROM task_status WHERE view_token=?
                ORDER BY CASE status
                    WHEN 'success' THEN 1
                    WHEN 'processing' THEN 2
                    WHEN 'calibrating' THEN 3
                    WHEN 'awaiting_cloud_confirmation' THEN 4
                    WHEN 'queued' THEN 5
                    WHEN 'failed' THEN 6
                    ELSE 7 END,
                    created_at DESC
                LIMIT 1""",
                (view_token,),
            ).fetchone()
        finally:
            connection.close()
        return self._task_from_row(row) if row is not None else None

    def create_link_job(
        self,
        *,
        task_id: str,
        view_token: str,
        owner_user_id: str,
        source_url: str,
        strategy: str,
        payload: Mapping[str, object],
        now: datetime,
    ) -> TranscriptionJob:
        if strategy not in {"local", "cloud"}:
            raise ControlStoreConflict("invalid_strategy")
        payload_json = _safe_payload(payload)
        now_text = _iso(now)
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO task_status
                (task_id, view_token, url, owner_user_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                (task_id, view_token, source_url, owner_user_id, now_text, now_text),
            )
            connection.execute(
                """INSERT INTO transcription_jobs
                (task_id, owner_user_id, source_kind, source_ref, strategy,
                 payload_json, status, created_at, updated_at)
                VALUES (?, ?, 'remote_url', ?, ?, ?, 'queued', ?, ?)""",
                (
                    task_id,
                    owner_user_id,
                    source_url,
                    strategy,
                    payload_json,
                    now_text,
                    now_text,
                ),
            )
        return self.get_job(task_id)  # type: ignore[return-value]

    def create_upload_session(
        self,
        *,
        session_id: str,
        owner_user_id: str,
        object_key: str,
        max_bytes: int,
        expires_at: datetime,
        now: datetime,
    ) -> UploadSession:
        if max_bytes <= 0 or not object_key or object_key.startswith("/") or ".." in object_key.split("/"):
            raise ControlStoreConflict("invalid_upload_session")
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO upload_sessions
                (id, owner_user_id, object_key, status, max_bytes, expires_at,
                 created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)""",
                (
                    session_id,
                    owner_user_id,
                    object_key,
                    max_bytes,
                    _iso(expires_at),
                    _iso(now),
                    _iso(now),
                ),
            )
        return self.get_upload_session(session_id)

    def consume_upload_session_and_create_job(
        self,
        *,
        session_id: str,
        owner_user_id: str,
        actual_bytes: int,
        task_id: str,
        view_token: str,
        strategy: str,
        payload: Mapping[str, object],
        now: datetime,
    ) -> TranscriptionJob:
        if strategy not in {"local", "cloud"}:
            raise ControlStoreConflict("invalid_strategy")
        payload_json = _safe_payload(payload)
        now_text = _iso(now)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM upload_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise ControlStoreConflict("upload_session_not_found")
            if row["owner_user_id"] != owner_user_id:
                raise ControlStoreConflict("upload_owner_mismatch")
            if row["status"] == "consumed":
                existing = connection.execute(
                    "SELECT * FROM transcription_jobs WHERE task_id = ?",
                    (row["task_id"],),
                ).fetchone()
                if existing is None:
                    raise ControlStoreConflict("upload_session_inconsistent")
                return self._job_from_row(existing)
            if _parse_time(row["expires_at"]) <= now.astimezone(UTC):
                raise ControlStoreConflict("upload_session_expired")
            if actual_bytes <= 0:
                raise ControlStoreConflict("upload_empty")
            if actual_bytes > row["max_bytes"]:
                raise ControlStoreConflict("upload_too_large")
            connection.execute(
                """INSERT INTO task_status
                (task_id, view_token, url, owner_user_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                (
                    task_id,
                    view_token,
                    f"object://{row['object_key']}",
                    owner_user_id,
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                """INSERT INTO transcription_jobs
                (task_id, owner_user_id, source_kind, source_ref, strategy,
                 payload_json, status, created_at, updated_at)
                VALUES (?, ?, 'object', ?, ?, ?, 'queued', ?, ?)""",
                (
                    task_id,
                    owner_user_id,
                    row["object_key"],
                    strategy,
                    payload_json,
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                """UPDATE upload_sessions
                SET status='consumed', actual_bytes=?, task_id=?, updated_at=?
                WHERE id=? AND status='pending'""",
                (actual_bytes, task_id, now_text, session_id),
            )
        return self.get_job(task_id)  # type: ignore[return-value]

    def claim_next_job(self, owner: str, *, now: datetime) -> TranscriptionJob | None:
        if not owner:
            raise ControlStoreConflict("invalid_lease_owner")
        now_text = _iso(now)
        expires_text = _iso(now + timedelta(seconds=self.lease_seconds))
        with self.database.transaction() as connection:
            claim_suffix = (
                " FOR UPDATE SKIP LOCKED"
                if self.database.dialect == "postgres"
                else ""
            )
            row = connection.execute(
                """SELECT * FROM transcription_jobs
                WHERE status='queued'
                   OR (status='leased' AND lease_expires_at <= ?)
                ORDER BY created_at, task_id LIMIT 1""" + claim_suffix,
                (now_text,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE transcription_jobs
                SET status='leased', lease_owner=?, lease_expires_at=?,
                    attempt_count=attempt_count+1, updated_at=?
                WHERE task_id=?""",
                (owner, expires_text, now_text, row["task_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM transcription_jobs WHERE task_id=?", (row["task_id"],)
            ).fetchone()
            return self._job_from_row(claimed)

    def heartbeat_job(self, task_id: str, owner: str, *, now: datetime) -> bool:
        with self.database.transaction() as connection:
            updated = connection.execute(
                """UPDATE transcription_jobs
                SET lease_expires_at=?, updated_at=?
                WHERE task_id=? AND status='leased' AND lease_owner=?
                  AND lease_expires_at > ?""",
                (
                    _iso(now + timedelta(seconds=self.lease_seconds)),
                    _iso(now),
                    task_id,
                    owner,
                    _iso(now),
                ),
            )
            return updated.rowcount == 1

    def create_quote_and_wait(
        self,
        quote: NewCloudQuote,
        *,
        token: str,
        lease_owner: str,
        now: datetime,
    ):
        """Create a quote and release the matching content-worker lease."""
        with self.database.transaction() as connection:
            created = self.quote_repository._create_on(
                connection, quote, token=token, now=now
            )
            updated = connection.execute(
                """UPDATE transcription_jobs
                SET status='waiting_confirmation', lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status='leased' AND lease_owner=?""",
                (_iso(now), quote.task_id, lease_owner),
            )
            if updated.rowcount != 1:
                raise ControlStoreConflict("job_not_leased")
            connection.execute(
                """UPDATE task_status SET status='waiting_confirmation', updated_at=?
                WHERE task_id=?""",
                (_iso(now), quote.task_id),
            )
            return created

    def confirm_quote_and_handoff(
        self,
        task_id: str,
        token: str,
        accepted_max_cost: Decimal,
        *,
        now: datetime,
    ):
        """Confirm one quote and durably hand its existing job to dispatch."""
        with self.database.transaction() as connection:
            quote, created = self.quote_repository._confirm_and_queue_on(
                connection,
                task_id,
                token,
                accepted_max_cost,
                now=now,
            )
            updated = connection.execute(
                """UPDATE transcription_jobs
                SET status='provider_handoff', lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status='waiting_confirmation'""",
                (_iso(now), task_id),
            )
            if not updated.rowcount:
                row = connection.execute(
                    "SELECT status FROM transcription_jobs WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if row is None or row["status"] != "provider_handoff":
                    raise ControlStoreConflict("job_not_waiting_confirmation")
            connection.execute(
                """UPDATE task_status SET status='provider_handoff', updated_at=?
                WHERE task_id=?""",
                (_iso(now), task_id),
            )
            return quote, created

    def reserve_attempt_and_consume_quote(
        self,
        attempt: NewASRAttempt,
        *,
        new_paid_attempt: bool = False,
        now: datetime | None = None,
    ):
        """Reserve/reuse one usage attempt and consume its quote atomically."""
        transition_time = now or datetime.now(UTC)
        with self.database.transaction() as connection:
            event = self.usage_repository._reserve_attempt_on(
                connection,
                attempt,
                new_paid_attempt=new_paid_attempt,
            )
            self.quote_repository._mark_consumed_on(
                connection,
                attempt.task_id,
                attempt_no=event.attempt_no,
                now=transition_time,
            )
            return event

    def list_quote_backed_reserved(
        self, *, created_before: datetime
    ) -> list[QuoteBackedReservedAttempt]:
        """Return old reservations backed by their consumed quote."""
        connection = self.database.connect()
        try:
            rows = connection.execute(
                """SELECT u.id AS event_id, u.task_id, u.attempt_no,
                    q.media_ref, q.media_sha256, q.duration_seconds,
                    q.max_cost, u.continuation_json
                FROM usage_events AS u
                JOIN cloud_quotes AS q ON q.task_id = u.task_id
                WHERE u.step = 'asr'
                    AND u.remote_status = 'reserved'
                    AND u.created_at < ?
                    AND q.status = 'consumed'
                    AND q.attempt_no = u.attempt_no
                ORDER BY u.created_at, u.attempt_no, u.id""",
                (_iso(created_before),),
            ).fetchall()
        finally:
            connection.close()
        return [
            QuoteBackedReservedAttempt(
                event_id=row["event_id"],
                task_id=row["task_id"],
                attempt_no=row["attempt_no"],
                media_ref=row["media_ref"],
                media_sha256=row["media_sha256"],
                duration_seconds=Decimal(row["duration_seconds"]),
                max_cost=Decimal(row["max_cost"]),
                continuation_json=row["continuation_json"],
            )
            for row in rows
        ]

    def complete_job(self, task_id: str, owner: str, *, now: datetime) -> bool:
        with self.database.transaction() as connection:
            updated = connection.execute(
                """UPDATE transcription_jobs
                SET status='completed', lease_owner=NULL, lease_expires_at=NULL,
                    updated_at=?
                WHERE task_id=? AND status='leased' AND lease_owner=?""",
                (_iso(now), task_id, owner),
            )
            if updated.rowcount:
                connection.execute(
                    "UPDATE task_status SET status='success', updated_at=? WHERE task_id=?",
                    (_iso(now), task_id),
                )
            return updated.rowcount == 1

    def get_job(self, task_id: str) -> TranscriptionJob | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE task_id=?", (task_id,)
            ).fetchone()
        finally:
            connection.close()
        return self._job_from_row(row) if row is not None else None

    def get_task(self, task_id: str) -> dict[str, object] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM task_status WHERE task_id=?", (task_id,)
            ).fetchone()
        finally:
            connection.close()
        return self._task_from_row(row) if row is not None else None

    def get_upload_session(self, session_id: str) -> UploadSession:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM upload_sessions WHERE id=?", (session_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ControlStoreConflict("upload_session_not_found")
        return self._upload_from_row(row)

    def clear_contract_tables(self) -> None:
        """Clear only Iteration 6 control rows for isolated contract tests."""
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM usage_events")
            connection.execute("DELETE FROM cloud_quotes")
            connection.execute("DELETE FROM upload_sessions")
            connection.execute("DELETE FROM transcription_jobs")
            connection.execute("DELETE FROM task_status")

    def close(self) -> None:
        self.database.close()

    @staticmethod
    def _job_from_row(row) -> TranscriptionJob:
        return TranscriptionJob(
            task_id=row["task_id"],
            owner_user_id=row["owner_user_id"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            strategy=row["strategy"],
            payload_json=row["payload_json"],
            status=row["status"],
            lease_owner=row["lease_owner"],
            lease_expires_at=(
                _parse_time(row["lease_expires_at"])
                if row["lease_expires_at"]
                else None
            ),
            attempt_count=row["attempt_count"],
            created_at=_parse_time(row["created_at"]),
            updated_at=_parse_time(row["updated_at"]),
        )

    @staticmethod
    def _task_from_row(row) -> dict[str, object]:
        task = dict(row)
        progress = task.get("progress_json")
        if isinstance(progress, str):
            try:
                task["progress_json"] = json.loads(progress)
            except (TypeError, ValueError):
                task["progress_json"] = None
        return task

    @staticmethod
    def _upload_from_row(row) -> UploadSession:
        return UploadSession(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            object_key=row["object_key"],
            status=row["status"],
            max_bytes=row["max_bytes"],
            actual_bytes=row["actual_bytes"],
            expires_at=_parse_time(row["expires_at"]),
            task_id=row["task_id"],
            created_at=_parse_time(row["created_at"]),
            updated_at=_parse_time(row["updated_at"]),
        )


class SQLiteTranscriptionControlStore(_TranscriptionControlStore):
    """SQLite authority for local transcription control state."""

    def __init__(self, path: str | Path, *, lease_seconds: int = 60) -> None:
        super().__init__(SQLiteControlDatabase(path), lease_seconds=lease_seconds)


class PostgresTranscriptionControlStore(_TranscriptionControlStore):
    """PostgreSQL authority for SaaS transcription control state."""

    def __init__(self, dsn: str, *, lease_seconds: int = 60) -> None:
        super().__init__(PostgresControlDatabase(dsn), lease_seconds=lease_seconds)
