import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..utils.logging import setup_logger

logger = setup_logger("content_marks")


class ContentMarkRepository:
    """SQLite repository for whole-content marks."""

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
                logger.warning("WAL mode not supported for content marks")
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
                CREATE TABLE IF NOT EXISTS content_marks (
                    id TEXT PRIMARY KEY,
                    user_key TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_key, owner_type, owner_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_content_marks_owner
                ON content_marks(owner_type, owner_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_content_marks_user_updated
                ON content_marks(user_key, updated_at DESC)
                """
            )

    def mark(self, owner_type: str, owner_id: str, user_key: str) -> dict[str, Any]:
        owner_type = self._clean(owner_type)
        owner_id = self._clean(owner_id)
        user_key = self._clean(user_key)
        if not owner_type or not owner_id or not user_key:
            raise ValueError("owner_type, owner_id and user_key are required")

        mark_id = uuid.uuid4().hex
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO content_marks (id, user_key, owner_type, owner_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_key, owner_type, owner_id)
                DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (mark_id, user_key, owner_type, owner_id),
            )
        existing = self.get_mark(owner_type, owner_id, user_key)
        if existing is None:
            raise RuntimeError("content mark was not saved")
        return existing

    def unmark(self, owner_type: str, owner_id: str, user_key: str) -> bool:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM content_marks
                WHERE owner_type = ? AND owner_id = ? AND user_key = ?
                """,
                (self._clean(owner_type), self._clean(owner_id), self._clean(user_key)),
            )
            return cursor.rowcount > 0

    def get_mark(
        self, owner_type: str, owner_id: str, user_key: str
    ) -> dict[str, Any] | None:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM content_marks
                WHERE owner_type = ? AND owner_id = ? AND user_key = ?
                """,
                (self._clean(owner_type), self._clean(owner_id), self._clean(user_key)),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def is_marked(self, owner_type: str, owner_id: str, user_key: str) -> bool:
        return self.get_mark(owner_type, owner_id, user_key) is not None

    @staticmethod
    def _clean(value: str | None) -> str:
        return (value or "").strip()
