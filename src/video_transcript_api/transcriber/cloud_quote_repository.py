"""Persistent, fail-closed authorization records for cloud ASR quotes."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Collection, Iterator, Mapping

from psycopg import IntegrityError as PostgresIntegrityError

from .control_database import SQLiteControlDatabase


class CloudQuoteConflict(RuntimeError):
    """The requested quote transition is no longer valid."""


LOCAL_SELECTION_LEASE_SECONDS = 3700


@dataclass(frozen=True)
class NewCloudQuote:
    task_id: str
    media_ref: str
    media_sha256: str
    duration_seconds: Decimal
    billable_seconds: int
    model: str
    unit_price: Decimal
    max_cost: Decimal
    continuation_json: str | None = None


@dataclass(frozen=True)
class CloudQuote:
    task_id: str
    media_ref: str
    media_sha256: str
    duration_seconds: Decimal
    billable_seconds: int
    model: str
    unit_price: Decimal
    max_cost: Decimal
    status: str
    expires_at: datetime
    token: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempt_no: int | None = None
    continuation_json: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CloudQuoteRepository:
    def __init__(self, db_path: str | Path | object, *, clock: Callable[[], datetime] = _utc_now):
        if hasattr(db_path, "connect") and hasattr(db_path, "transaction"):
            self.database = db_path
            self.db_path = getattr(db_path, "path", None)
        else:
            self.database = SQLiteControlDatabase(db_path)
            self.db_path = str(db_path)
        self.clock = clock
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[object]:
        connection = self.database.connect()
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        else:
            if connection.in_transaction:
                connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cloud_quotes (
                    task_id TEXT PRIMARY KEY,
                    media_ref TEXT NOT NULL,
                    media_sha256 TEXT NOT NULL,
                    duration_seconds TEXT NOT NULL,
                    billable_seconds INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    unit_price TEXT NOT NULL,
                    max_cost TEXT NOT NULL,
                    status TEXT NOT NULL,
                    token_hash TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempt_no INTEGER,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                    ,continuation_json TEXT
                )
                """
            )

    def create(self, quote: NewCloudQuote, *, token: str | None = None) -> CloudQuote:
        token = token or secrets.token_urlsafe(32)
        now = self.clock()
        with self._connection() as connection:
            return self._create_on(connection, quote, token=token, now=now)

    def _create_on(
        self, connection, quote: NewCloudQuote, *, token: str, now: datetime
    ) -> CloudQuote:
        expires_at = now + timedelta(minutes=30)
        try:
            connection.execute(
                """INSERT INTO cloud_quotes VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, NULL, ?, ?, ?, ?)""",
                (
                    quote.task_id, quote.media_ref, quote.media_sha256,
                    str(quote.duration_seconds), quote.billable_seconds, quote.model,
                    str(quote.unit_price), str(quote.max_cost), _token_hash(token),
                    _iso(expires_at), _iso(now), _iso(now), quote.continuation_json,
                ),
            )
        except (sqlite3.IntegrityError, PostgresIntegrityError) as exc:
            raise CloudQuoteConflict("quote_already_exists") from exc
        row = connection.execute(
            "SELECT * FROM cloud_quotes WHERE task_id=?", (quote.task_id,)
        ).fetchone()
        created = self._from_row(row)
        return CloudQuote(**{**created.__dict__, "token": token})

    def get(self, task_id: str) -> CloudQuote:
        now = self.clock()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM cloud_quotes WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise CloudQuoteConflict("quote_not_found")
            if row["status"] == "pending" and _parse_time(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE cloud_quotes SET status='refresh_required', token_hash=NULL, updated_at=? WHERE task_id=?",
                    (_iso(now), task_id),
                )
                row = connection.execute(
                    "SELECT * FROM cloud_quotes WHERE task_id = ?", (task_id,)
                ).fetchone()
        return self._from_row(row)

    def claim_confirmation(
        self, task_id: str, token: str, accepted_max_cost: Decimal, owner: str
    ) -> CloudQuote:
        now = self.clock()
        lease_until = now + timedelta(seconds=60)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)).fetchone()
            self._verify(row, token, accepted_max_cost)
            if row["status"] == "pending":
                connection.execute(
                    "UPDATE cloud_quotes SET status='confirming', lease_owner=?, lease_expires_at=?, updated_at=? WHERE task_id=?",
                    (owner, _iso(lease_until), _iso(now), task_id),
                )
            elif row["status"] == "confirming":
                lease_expiry = _parse_time(row["lease_expires_at"])
                if lease_expiry <= now:
                    connection.execute(
                        "UPDATE cloud_quotes SET lease_owner=?, lease_expires_at=?, updated_at=? WHERE task_id=?",
                        (owner, _iso(lease_until), _iso(now), task_id),
                    )
            elif row["status"] != "consumed":
                raise CloudQuoteConflict("quote_not_confirmable")
            row = connection.execute("SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)).fetchone()
        return self._from_row(row)

    def confirm_and_queue(
        self,
        task_id: str,
        token: str,
        accepted_max_cost: Decimal,
    ) -> tuple[CloudQuote, bool]:
        """Persist one user-authorized queue item without starting cloud work."""
        now = self.clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._confirm_and_queue_on(
                connection,
                task_id,
                token,
                accepted_max_cost,
                now=now,
            )

    def _confirm_and_queue_on(
        self,
        connection,
        task_id: str,
        token: str,
        accepted_max_cost: Decimal,
        *,
        now: datetime,
    ) -> tuple[CloudQuote, bool]:
        row = connection.execute(
            "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
        ).fetchone()
        self._verify(row, token, accepted_max_cost, now=now)
        created = row["status"] == "pending"
        if created:
            connection.execute(
                """UPDATE cloud_quotes
                SET status='confirmed_queued', lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status='pending'""",
                (_iso(now), task_id),
            )
        elif row["status"] != "confirmed_queued":
            raise CloudQuoteConflict("quote_not_confirmable")
        row = connection.execute(
            "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
        ).fetchone()
        return self._from_row(row), created

    def claim_queued(
        self, task_id: str, owner: str, *, lease_seconds: int = 60
    ) -> CloudQuote:
        """Atomically lease one already-confirmed queue item to the dispatcher."""
        now = self.clock()
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE cloud_quotes
                SET status='confirming', lease_owner=?, lease_expires_at=?, updated_at=?
                WHERE task_id=? AND status='confirmed_queued'""",
                (owner, _iso(lease_until), _iso(now), task_id),
            )
            if not updated.rowcount:
                raise CloudQuoteConflict("quote_not_queued")
            row = connection.execute(
                "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._from_row(row)

    def list_confirmed_queued(self) -> list[str]:
        """Return durable queue ids in stable creation order."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT task_id FROM cloud_quotes
                WHERE status='confirmed_queued'
                ORDER BY created_at, task_id"""
            ).fetchall()
        return [row["task_id"] for row in rows]

    def cancel(self, task_id: str) -> bool:
        """Stop a quote before it can start or resume a cloud ASR attempt."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE cloud_quotes
                SET status='canceled', token_hash=NULL, lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status IN (
                    'pending', 'refresh_required', 'confirmed_queued', 'confirming',
                    'local_selected', 'local_queued'
                )""",
                (_iso(self.clock()), task_id),
            )
        return bool(updated.rowcount)

    def requeue_expired_leases(self, *, now: datetime | None = None) -> list[str]:
        """Recover dispatcher claims only after their short lease expires."""
        now = now or self.clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT task_id FROM cloud_quotes
                WHERE status='confirming' AND lease_expires_at <= ?
                ORDER BY created_at, task_id""",
                (_iso(now),),
            ).fetchall()
            task_ids = [row["task_id"] for row in rows]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    f"""UPDATE cloud_quotes
                    SET status='confirmed_queued', lease_owner=NULL,
                        lease_expires_at=NULL, updated_at=?
                    WHERE status='confirming' AND task_id IN ({placeholders})""",
                    (_iso(now), *task_ids),
                )
        return task_ids

    def next_lease_expiry(self) -> datetime | None:
        """Return the nearest live dispatcher lease expiry, if any."""
        now = self.clock()
        with self._connection() as connection:
            row = connection.execute(
                """SELECT MIN(lease_expires_at) AS expiry FROM cloud_quotes
                WHERE status='confirming' AND lease_expires_at > ?""",
                (_iso(now),),
            ).fetchone()
        return _parse_time(row["expiry"]) if row and row["expiry"] else None

    def requeue_claim(self, task_id: str, owner: str) -> bool:
        """Conditionally undo a claim when executor submission fails."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE cloud_quotes
                SET status='confirmed_queued', lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status='confirming' AND lease_owner=?""",
                (_iso(self.clock()), task_id, owner),
            )
        return bool(updated.rowcount)

    def fail_claim(self, task_id: str, owner: str) -> bool:
        """Finish one claimed quote after a definitive local execution failure."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE cloud_quotes
                SET status='failed', token_hash=NULL, lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status='confirming' AND lease_owner=?""",
                (_iso(self.clock()), task_id, owner),
            )
        return bool(updated.rowcount)

    def mark_consumed(self, task_id: str, *, attempt_no: int) -> CloudQuote:
        with self._connection() as connection:
            return self._mark_consumed_on(
                connection, task_id, attempt_no=attempt_no, now=self.clock()
            )

    def _mark_consumed_on(
        self, connection, task_id: str, *, attempt_no: int, now: datetime
    ) -> CloudQuote:
        updated = connection.execute(
            "UPDATE cloud_quotes SET status='consumed', attempt_no=?, token_hash=NULL, lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE task_id=? AND status IN ('confirming','consumed')",
            (attempt_no, _iso(now), task_id),
        )
        if not updated.rowcount:
            raise CloudQuoteConflict("quote_not_confirming")
        row = connection.execute(
            "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
        ).fetchone()
        return self._from_row(row)

    def require_refresh(self, task_id: str) -> CloudQuote:
        with self._connection() as connection:
            updated = connection.execute(
                "UPDATE cloud_quotes SET status='refresh_required', token_hash=NULL, "
                "lease_owner=NULL, lease_expires_at=NULL, updated_at=? "
                "WHERE task_id=? AND status='confirming'",
                (_iso(self.clock()), task_id),
            )
            if not updated.rowcount:
                raise CloudQuoteConflict("quote_not_confirming")
        return self.get(task_id)

    def refresh(self, quote: NewCloudQuote, *, old_token: str, new_token: str | None = None) -> CloudQuote:
        new_token = new_token or secrets.token_urlsafe(32)
        now = self.clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM cloud_quotes WHERE task_id=?", (quote.task_id,)).fetchone()
            if row is None:
                raise CloudQuoteConflict("quote_not_found")
            old_matches = row["token_hash"] == _token_hash(old_token)
            expired_pending = row["status"] == "pending" and _parse_time(row["expires_at"]) <= now
            if not old_matches and not (row["status"] == "refresh_required" and row["token_hash"] is None):
                raise CloudQuoteConflict("quote_token_mismatch")
            if not expired_pending and row["status"] != "refresh_required":
                raise CloudQuoteConflict("quote_not_refreshable")
            connection.execute(
                """UPDATE cloud_quotes SET media_ref=?, media_sha256=?, duration_seconds=?,
                billable_seconds=?, model=?, unit_price=?, max_cost=?, status='pending',
                token_hash=?, lease_owner=NULL, lease_expires_at=NULL, attempt_no=NULL,
                expires_at=?, updated_at=? WHERE task_id=?""",
                (quote.media_ref, quote.media_sha256, str(quote.duration_seconds),
                 quote.billable_seconds, quote.model, str(quote.unit_price), str(quote.max_cost),
                 _token_hash(new_token), _iso(now + timedelta(minutes=30)), _iso(now), quote.task_id),
            )
        return self._get_with_token(quote.task_id, new_token)

    def refresh_required(self, quote: NewCloudQuote, *, new_token: str | None = None) -> CloudQuote:
        """Replace a quote only after its old token has been invalidated."""
        new_token = new_token or secrets.token_urlsafe(32)
        now = self.clock()
        with self._connection() as connection:
            updated = connection.execute(
                """UPDATE cloud_quotes SET media_ref=?, media_sha256=?, duration_seconds=?,
                billable_seconds=?, model=?, unit_price=?, max_cost=?, status='pending',
                token_hash=?, lease_owner=NULL, lease_expires_at=NULL, attempt_no=NULL,
                expires_at=?, updated_at=?, continuation_json=?
                WHERE task_id=? AND status='refresh_required'""",
                (quote.media_ref, quote.media_sha256, str(quote.duration_seconds),
                 quote.billable_seconds, quote.model, str(quote.unit_price), str(quote.max_cost),
                 _token_hash(new_token), _iso(now + timedelta(minutes=30)), _iso(now),
                 quote.continuation_json, quote.task_id),
            )
            if not updated.rowcount:
                raise CloudQuoteConflict("quote_not_refreshable")
        return self._get_with_token(quote.task_id, new_token)

    def claim_local(
        self,
        task_id: str,
        owner: str,
        *,
        now: datetime | None = None,
    ) -> tuple[CloudQuote, bool]:
        """Claim one local fallback; duplicates observe the existing handoff."""
        current = now or self.clock()
        lease_until = current + timedelta(seconds=LOCAL_SELECTION_LEASE_SECONDS)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise CloudQuoteConflict("quote_not_found")
            live_local = row["status"] in {"local_selected", "local_queued"}
            lease_expiry = (
                _parse_time(row["lease_expires_at"])
                if row["lease_expires_at"]
                else None
            )
            if live_local and (
                row["status"] == "local_queued"
                or (lease_expiry is not None and lease_expiry > current)
            ):
                return self._from_row(row), False
            claimable = row["status"] in {"pending", "refresh_required"} or (
                row["status"] == "local_selected"
                and (lease_expiry is None or lease_expiry <= current)
            )
            if not claimable:
                raise CloudQuoteConflict("quote_not_pending")
            connection.execute(
                """UPDATE cloud_quotes
                SET status='local_selected', token_hash=NULL, lease_owner=?,
                    lease_expires_at=?, updated_at=?
                WHERE task_id=?""",
                (owner, _iso(lease_until), _iso(current), task_id),
            )
            row = connection.execute(
                "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
            ).fetchone()
            return self._from_row(row), True

    def mark_local_queued(
        self, task_id: str, owner: str, *, now: datetime | None = None
    ) -> CloudQuote:
        """Persist executor handoff before local work is submitted."""
        current = now or self.clock()
        with self._connection() as connection:
            updated = connection.execute(
                """UPDATE cloud_quotes SET status='local_queued', updated_at=?
                WHERE task_id=? AND status='local_selected'
                    AND lease_owner=? AND lease_expires_at>?""",
                (_iso(current), task_id, owner, _iso(current)),
            )
            if not updated.rowcount:
                raise CloudQuoteConflict("local_claim_lost")
            row = connection.execute(
                "SELECT * FROM cloud_quotes WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._from_row(row)

    def release_local_queue(self, task_id: str, owner: str) -> bool:
        """Release a failed local preparation or executor handoff for retry."""
        with self._connection() as connection:
            updated = connection.execute(
                """UPDATE cloud_quotes
                SET status='local_selected', lease_owner=NULL,
                    lease_expires_at=NULL, updated_at=?
                WHERE task_id=? AND status IN ('local_selected','local_queued')
                    AND lease_owner=?""",
                (_iso(self.clock()), task_id, owner),
            )
        return bool(updated.rowcount)

    def list_stale_local_queued(
        self, *, created_before: datetime
    ) -> list[CloudQuote]:
        """List prior-process local handoffs without changing them."""
        cutoff = _iso(created_before)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM cloud_quotes
                WHERE status='local_queued' AND updated_at < ?
                ORDER BY updated_at, task_id""",
                (cutoff,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def reset_stale_local_queued(
        self,
        task_ids: Collection[str],
        *,
        created_before: datetime,
    ) -> list[str]:
        """Reset a validated subset of prior-process local handoffs."""
        candidates = tuple(dict.fromkeys(task_ids))
        if not candidates:
            return []
        cutoff = _iso(created_before)
        placeholders = ",".join("?" for _ in candidates)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""SELECT task_id FROM cloud_quotes
                WHERE status='local_queued' AND updated_at < ?
                    AND task_id IN ({placeholders})
                ORDER BY updated_at, task_id""",
                (cutoff, *candidates),
            ).fetchall()
            reset_ids = [row["task_id"] for row in rows]
            if reset_ids:
                reset_placeholders = ",".join("?" for _ in reset_ids)
                connection.execute(
                    f"""UPDATE cloud_quotes
                    SET status='local_selected', lease_owner=NULL,
                        lease_expires_at=NULL, updated_at=?
                    WHERE status='local_queued'
                        AND task_id IN ({reset_placeholders})""",
                    (cutoff, *reset_ids),
                )
        return reset_ids

    def expire_stale_unconfirmed(self, *, max_age: timedelta = timedelta(hours=24)) -> list[str]:
        """Expire unattended quotes before ordinary temp cleanup removes media."""
        cutoff = self.clock() - max_age
        now = self.clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT task_id FROM cloud_quotes
                WHERE status IN (
                    'pending', 'refresh_required', 'confirmed_queued', 'confirming'
                )
                  AND created_at <= ?
                """,
                (_iso(cutoff),),
            ).fetchall()
            task_ids = [row["task_id"] for row in rows]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    f"""UPDATE cloud_quotes
                    SET status='expired', token_hash=NULL, lease_owner=NULL,
                        lease_expires_at=NULL, updated_at=?
                    WHERE task_id IN ({placeholders})""",
                    (_iso(now), *task_ids),
                )
        return task_ids

    def reconcile_usage_attempts(self) -> list[str]:
        """Make durable usage allocation authoritative after process crashes."""
        now = self.clock()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT q.task_id, MAX(u.attempt_no) AS attempt_no
                FROM cloud_quotes q
                JOIN usage_events u ON u.task_id = q.task_id AND u.step = 'asr'
                WHERE q.status IN ('confirmed_queued', 'confirming')
                GROUP BY q.task_id
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE cloud_quotes
                    SET status='consumed', attempt_no=?, token_hash=NULL,
                        lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                    WHERE task_id=? AND status IN ('confirmed_queued', 'confirming')
                    """,
                    (row["attempt_no"], _iso(now), row["task_id"]),
                )
        return [row["task_id"] for row in rows]

    def _get_with_token(self, task_id: str, token: str) -> CloudQuote:
        quote = self.get(task_id)
        return CloudQuote(**{**quote.__dict__, "token": token})

    def _verify(
        self,
        row: Mapping[str, object] | None,
        token: str,
        amount: Decimal,
        *,
        now: datetime | None = None,
    ) -> None:
        if row is None:
            raise CloudQuoteConflict("quote_not_found")
        if row["token_hash"] != _token_hash(token):
            raise CloudQuoteConflict("quote_token_mismatch")
        if Decimal(row["max_cost"]) != amount:
            raise CloudQuoteConflict("quote_amount_mismatch")
        if _parse_time(row["expires_at"]) <= (now or self.clock()):
            raise CloudQuoteConflict("quote_expired")

    @staticmethod
    def _from_row(row: Mapping[str, object]) -> CloudQuote:
        return CloudQuote(
            task_id=row["task_id"], media_ref=row["media_ref"], media_sha256=row["media_sha256"],
            duration_seconds=Decimal(row["duration_seconds"]), billable_seconds=row["billable_seconds"],
            model=row["model"], unit_price=Decimal(row["unit_price"]), max_cost=Decimal(row["max_cost"]),
            status=row["status"], expires_at=_parse_time(row["expires_at"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=(
                _parse_time(row["lease_expires_at"])
                if row["lease_expires_at"]
                else None
            ),
            attempt_no=row["attempt_no"],
            continuation_json=row["continuation_json"],
        )
