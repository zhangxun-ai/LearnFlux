"""Short-lived media references for retrying ASR without another download."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .control_database import SQLiteControlDatabase


class ASRRetryConflict(ValueError):
    """A safe retry-state error."""


@dataclass(frozen=True)
class ASRRetryRecord:
    task_id: str
    media_ref: str
    media_sha256: str
    continuation_json: str
    state: str
    expires_at: str


class ASRRetryRepository:
    """Keep media separate from cloud pricing and atomically claim retries."""

    def __init__(self, database, *, clock=lambda: datetime.now(UTC)):
        self.database = database if hasattr(database, "transaction") else SQLiteControlDatabase(database)
        self.clock = clock
        with self.database.transaction() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS asr_retry_media (
                    task_id TEXT PRIMARY KEY,
                    media_ref TEXT NOT NULL,
                    media_sha256 TEXT NOT NULL,
                    continuation_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def save(self, task_id: str, media_ref: str, sha256: str, continuation: str):
        now = self.clock()
        with self.database.transaction() as connection:
            connection.execute("""
                INSERT INTO asr_retry_media VALUES (?, ?, ?, ?, 'ready', ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    media_ref=excluded.media_ref,
                    media_sha256=excluded.media_sha256,
                    continuation_json=excluded.continuation_json,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
            """, (task_id, media_ref, sha256, continuation,
                  (now + timedelta(hours=24)).isoformat(), now.isoformat()))
        return self.get(task_id)

    def get(self, task_id: str) -> ASRRetryRecord:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM asr_retry_media WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None or row["state"] == "finished":
            raise ASRRetryConflict("retry_media_unavailable")
        if datetime.fromisoformat(row["expires_at"]) <= self.clock():
            raise ASRRetryConflict("retry_media_expired")
        return ASRRetryRecord(**{key: row[key] for key in ASRRetryRecord.__dataclass_fields__})

    def claim(self, task_id: str) -> ASRRetryRecord:
        record = self.get(task_id)
        with self.database.transaction() as connection:
            changed = connection.execute(
                "UPDATE asr_retry_media SET state='claimed', updated_at=? "
                "WHERE task_id=? AND state='ready' AND expires_at>?",
                (self.clock().isoformat(), task_id, self.clock().isoformat()),
            ).rowcount
        if changed != 1:
            raise ASRRetryConflict("retry_already_started")
        return record

    def release(self, task_id: str) -> None:
        self._set_state(task_id, "ready")

    def finish(self, task_id: str) -> None:
        self._set_state(task_id, "finished")

    def _set_state(self, task_id: str, state: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE asr_retry_media SET state=?, updated_at=? WHERE task_id=?",
                (state, self.clock().isoformat(), task_id),
            )

    def recover_failed_claims(self) -> None:
        """Make prior-process failed tasks retryable after orphan recovery."""
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE asr_retry_media SET state='ready', updated_at=? "
                "WHERE state='claimed' AND task_id IN "
                "(SELECT task_id FROM task_status WHERE status='failed')",
                (self.clock().isoformat(),),
            )
