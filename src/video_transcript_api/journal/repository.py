import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..utils.logging import setup_logger

logger = setup_logger("journal_repository")


class JournalRepository:
    """SQLite repository for Focus Studio journal entries and AI reviews."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(str(self.db_path))
            self._local.connection.row_factory = sqlite3.Row
            try:
                self._local.connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                logger.warning("WAL mode not supported for journal repository")
        return self._local.connection

    @contextmanager
    def _get_cursor(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def close(self):
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
            del self._local.connection

    def _init_database(self):
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, entry_date, entry_type)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_journal_entries_user_date
                ON journal_entries(user_id, entry_date DESC, updated_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS journal_reviews (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    range_start TEXT NOT NULL,
                    range_end TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    model TEXT NOT NULL,
                    reasoning_effort TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_journal_reviews_user_created
                ON journal_reviews(user_id, created_at DESC)
                """
            )

    def upsert_entry(
        self,
        user_id: str,
        entry_date: str,
        entry_type: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        entry_id = uuid.uuid4().hex
        clean_title = (title or "").strip()
        clean_body = body or ""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO journal_entries
                    (id, user_id, entry_date, entry_type, title, body)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, entry_date, entry_type)
                DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (entry_id, user_id, entry_date, entry_type, clean_title, clean_body),
            )
        return self.get_entry(user_id, entry_date, entry_type) or {
            "id": entry_id,
            "user_id": user_id,
            "entry_date": entry_date,
            "entry_type": entry_type,
            "title": clean_title,
            "body": clean_body,
        }

    def get_entry(
        self,
        user_id: str,
        entry_date: str,
        entry_type: str,
    ) -> dict[str, Any] | None:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM journal_entries
                WHERE user_id = ? AND entry_date = ? AND entry_type = ?
                """,
                (user_id, entry_date, entry_type),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def list_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        entry_type: str | None = None,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if start_date:
            clauses.append("entry_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("entry_date <= ?")
            params.append(end_date)
        if entry_type:
            clauses.append("entry_type = ?")
            params.append(entry_type)
        params.append(max(1, min(int(limit), 200)))

        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM journal_entries
                WHERE {" AND ".join(clauses)}
                ORDER BY entry_date DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]

    def create_review(
        self,
        user_id: str,
        range_start: str,
        range_end: str,
        question: str,
        answer: str,
        model: str,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        review_id = uuid.uuid4().hex
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO journal_reviews
                    (id, user_id, range_start, range_end, question, answer, model, reasoning_effort)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    user_id,
                    range_start,
                    range_end,
                    (question or "").strip(),
                    (answer or "").strip(),
                    model,
                    reasoning_effort,
                ),
            )
        return self.get_review(review_id, user_id) or {
            "id": review_id,
            "user_id": user_id,
            "range_start": range_start,
            "range_end": range_end,
            "question": question,
            "answer": answer,
            "model": model,
            "reasoning_effort": reasoning_effort,
        }

    def get_review(self, review_id: str, user_id: str) -> dict[str, Any] | None:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM journal_reviews
                WHERE id = ? AND user_id = ?
                """,
                (review_id, user_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def list_reviews(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM journal_reviews
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, max(1, min(int(limit), 100))),
            )
            return [dict(row) for row in cursor.fetchall()]
