import datetime
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.logging import setup_logger

logger = setup_logger("learning_collections")

COLLECTION_TYPES = {"video_course", "document_topic"}
SOURCE_TYPES_BY_COLLECTION = {
    "video_course": {"video"},
    "document_topic": {"document"},
}


class LearningCollectionRepository:
    """SQLite repository for topic-level learning collections."""

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
                logger.warning("WAL mode not supported for learning collections")
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
                CREATE TABLE IF NOT EXISTS learning_collections (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    collection_type TEXT NOT NULL,
                    goal TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    summary_status TEXT NOT NULL DEFAULT 'not_started',
                    summary_markdown TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_collection_sources (
                    id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    view_token TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (collection_id) REFERENCES learning_collections(id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_sources_collection
                ON learning_collection_sources(collection_id, position)
                """
            )

    def create_collection(
        self, title: str, collection_type: str, goal: str = ""
    ) -> Dict[str, Any]:
        title = (title or "").strip()
        collection_type = (collection_type or "").strip()
        goal = (goal or "").strip()

        if not title:
            raise ValueError("title is required")
        if collection_type not in COLLECTION_TYPES:
            raise ValueError("collection_type must be video_course or document_topic")

        collection_id = uuid.uuid4().hex
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learning_collections
                (id, title, collection_type, goal)
                VALUES (?, ?, ?, ?)
                """,
                (collection_id, title, collection_type, goal),
            )
        return self.get_collection_detail(collection_id)

    def list_collections(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT c.*, COUNT(s.id) AS source_count
                FROM learning_collections c
                LEFT JOIN learning_collection_sources s ON s.collection_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_collection(self, collection_id: str) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM learning_collections WHERE id = ?",
                (collection_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_source(
        self,
        collection_id: str,
        task_id: str,
        view_token: str,
        title: str,
        source_type: str,
        position: Optional[int] = None,
    ) -> Dict[str, Any]:
        collection = self.get_collection(collection_id)
        if not collection:
            raise ValueError("collection not found")

        allowed = SOURCE_TYPES_BY_COLLECTION[collection["collection_type"]]
        if source_type not in allowed:
            raise ValueError(
                f"{collection['collection_type']} collection only accepts {sorted(allowed)}"
            )

        if position is None:
            position = self._next_source_position(collection_id)

        source_id = uuid.uuid4().hex
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learning_collection_sources
                (id, collection_id, task_id, view_token, title, source_type, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    collection_id,
                    task_id,
                    view_token,
                    title,
                    source_type,
                    int(position),
                ),
            )
            cursor.execute(
                """
                UPDATE learning_collections
                SET status = 'processing', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (collection_id,),
            )
        return self.get_source(source_id)

    def _next_source_position(self, collection_id: str) -> int:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1 AS next_position
                FROM learning_collection_sources
                WHERE collection_id = ?
                """,
                (collection_id,),
            )
            return int(cursor.fetchone()["next_position"])

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM learning_collection_sources WHERE id = ?",
                (source_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_sources(self, collection_id: str) -> List[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM learning_collection_sources
                WHERE collection_id = ?
                ORDER BY position ASC, created_at ASC
                """,
                (collection_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_collection_detail(self, collection_id: str) -> Optional[Dict[str, Any]]:
        collection = self.get_collection(collection_id)
        if not collection:
            return None
        collection["sources"] = self.get_sources(collection_id)
        return collection

    def save_summary(self, collection_id: str, markdown: str) -> Dict[str, Any]:
        now = datetime.datetime.utcnow().isoformat()
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE learning_collections
                SET summary_markdown = ?,
                    summary_status = 'success',
                    status = 'summarized',
                    updated_at = ?
                WHERE id = ?
                """,
                (markdown, now, collection_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        return self.get_collection_detail(collection_id)
