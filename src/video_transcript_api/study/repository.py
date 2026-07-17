import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import setup_logger

logger = setup_logger("study_repository")


class StudyRepository:
    """SQLite repository for context-isolated Study notes."""

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
                    owner_user_id TEXT,
                    collection_id TEXT,
                    source_id TEXT,
                    time_seconds REAL,
                    body TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("PRAGMA table_info(study_notes)")
            columns = {row[1] for row in cursor.fetchall()}
            for column in ("owner_user_id", "collection_id", "source_id"):
                if column not in columns:
                    cursor.execute(f"ALTER TABLE study_notes ADD COLUMN {column} TEXT")
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_study_notes_context
                ON study_notes(view_token, owner_user_id, collection_id, source_id, created_at)
                """
            )

    def create_note(
        self,
        view_token: str,
        time_seconds: Optional[float],
        body: str,
        *,
        owner_user_id: str = "",
        collection_id: str = "",
        source_id: str = "",
    ) -> dict[str, Any]:
        note_id = uuid.uuid4().hex
        clean_body = (body or "").strip()
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO study_notes (
                    id, view_token, owner_user_id, collection_id, source_id, time_seconds, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    view_token,
                    owner_user_id,
                    collection_id,
                    source_id,
                    time_seconds,
                    clean_body,
                ),
            )
        return self.get_note(
            note_id,
            view_token,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        ) or {"id": note_id, "view_token": view_token, "time_seconds": time_seconds, "body": clean_body}

    def get_note(
        self,
        note_id: str,
        view_token: str,
        *,
        owner_user_id: str = "",
        collection_id: str = "",
        source_id: str = "",
    ) -> Optional[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM study_notes
                WHERE id = ? AND view_token = ?
                  AND COALESCE(owner_user_id, '') = ?
                  AND COALESCE(collection_id, '') = ?
                  AND COALESCE(source_id, '') = ?
                """,
                (note_id, view_token, owner_user_id, collection_id, source_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def list_notes(
        self,
        view_token: str,
        *,
        owner_user_id: str = "",
        collection_id: str = "",
        source_id: str = "",
    ) -> list[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM study_notes
                WHERE view_token = ?
                  AND COALESCE(owner_user_id, '') = ?
                  AND COALESCE(collection_id, '') = ?
                  AND COALESCE(source_id, '') = ?
                ORDER BY COALESCE(time_seconds, 999999999), created_at
                """,
                (view_token, owner_user_id, collection_id, source_id),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_note(
        self,
        note_id: str,
        view_token: str,
        body: str,
        time_seconds: Optional[float],
        *,
        owner_user_id: str = "",
        collection_id: str = "",
        source_id: str = "",
    ) -> Optional[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE study_notes
                SET body = ?, time_seconds = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND view_token = ?
                  AND COALESCE(owner_user_id, '') = ?
                  AND COALESCE(collection_id, '') = ?
                  AND COALESCE(source_id, '') = ?
                """,
                (
                    (body or "").strip(),
                    time_seconds,
                    note_id,
                    view_token,
                    owner_user_id,
                    collection_id,
                    source_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_note(
            note_id,
            view_token,
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            source_id=source_id,
        )

    def delete_note(
        self,
        note_id: str,
        view_token: str,
        *,
        owner_user_id: str = "",
        collection_id: str = "",
        source_id: str = "",
    ) -> bool:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM study_notes
                WHERE id = ? AND view_token = ?
                  AND COALESCE(owner_user_id, '') = ?
                  AND COALESCE(collection_id, '') = ?
                  AND COALESCE(source_id, '') = ?
                """,
                (note_id, view_token, owner_user_id, collection_id, source_id),
            )
            return cursor.rowcount > 0
