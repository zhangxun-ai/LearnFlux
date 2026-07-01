import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import setup_logger

logger = setup_logger("study_repository")


class StudyRepository:
    """SQLite repository for local study-mode notes and lightweight session state."""

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
                logger.warning("WAL mode not supported for study repository")
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
                CREATE TABLE IF NOT EXISTS study_notes (
                    id TEXT PRIMARY KEY,
                    view_token TEXT NOT NULL,
                    time_seconds REAL,
                    body TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_study_notes_view_token
                ON study_notes(view_token, created_at)
                """
            )

    def create_note(
        self,
        view_token: str,
        time_seconds: Optional[float],
        body: str,
    ) -> dict[str, Any]:
        note_id = uuid.uuid4().hex
        clean_body = (body or "").strip()
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO study_notes (id, view_token, time_seconds, body)
                VALUES (?, ?, ?, ?)
                """,
                (note_id, view_token, time_seconds, clean_body),
            )
        return self.get_note(note_id, view_token) or {
            "id": note_id,
            "view_token": view_token,
            "time_seconds": time_seconds,
            "body": clean_body,
        }

    def get_note(self, note_id: str, view_token: str) -> Optional[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM study_notes
                WHERE id = ? AND view_token = ?
                """,
                (note_id, view_token),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def list_notes(self, view_token: str) -> list[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM study_notes
                WHERE view_token = ?
                ORDER BY COALESCE(time_seconds, 999999999), created_at
                """,
                (view_token,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_note(
        self,
        note_id: str,
        view_token: str,
        body: str,
        time_seconds: Optional[float],
    ) -> Optional[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE study_notes
                SET body = ?, time_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND view_token = ?
                """,
                ((body or "").strip(), time_seconds, note_id, view_token),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_note(note_id, view_token)

    def delete_note(self, note_id: str, view_token: str) -> bool:
        with self._get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM study_notes WHERE id = ? AND view_token = ?",
                (note_id, view_token),
            )
            return cursor.rowcount > 0
