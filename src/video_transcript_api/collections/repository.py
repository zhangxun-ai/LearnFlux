import datetime
import json
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
                    creator_name TEXT NOT NULL DEFAULT '',
                    collection_type TEXT NOT NULL,
                    goal TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    import_method TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    exported_at TIMESTAMP,
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_collection_knowledge_maps (
                    id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'success',
                    map_json TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (collection_id) REFERENCES learning_collections(id),
                    UNIQUE(collection_id, scope, source_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_maps_collection
                ON learning_collection_knowledge_maps(collection_id, scope, source_id)
                """
            )
        self._migrate_database()

    def _migrate_database(self):
        with self._get_cursor() as cursor:
            cursor.execute("PRAGMA table_info(learning_collections)")
            columns = {row[1] for row in cursor.fetchall()}
            migrations = [
                ("creator_name", "TEXT NOT NULL DEFAULT ''"),
                ("description", "TEXT NOT NULL DEFAULT ''"),
                ("import_method", "TEXT NOT NULL DEFAULT ''"),
                ("tags", "TEXT NOT NULL DEFAULT ''"),
                ("exported_at", "TIMESTAMP"),
            ]
            for name, definition in migrations:
                if name not in columns:
                    cursor.execute(
                        f"ALTER TABLE learning_collections ADD COLUMN {name} {definition}"
                    )

    def create_collection(
        self,
        title: str,
        creator_name: str,
        collection_type: str,
        goal: str = "",
        description: str = "",
        import_method: str = "",
        tags: str = "",
    ) -> Dict[str, Any]:
        title = (title or "").strip()
        creator_name = (creator_name or "").strip()
        collection_type = (collection_type or "").strip()
        goal = (goal or "").strip()
        description = (description or "").strip()
        import_method = (import_method or "").strip()
        tags = (tags or "").strip()

        if not title:
            raise ValueError("title is required")
        if not creator_name:
            raise ValueError("creator_name is required")
        if collection_type not in COLLECTION_TYPES:
            raise ValueError("collection_type must be video_course or document_topic")

        collection_id = uuid.uuid4().hex
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learning_collections
                (id, title, creator_name, collection_type, goal, description, import_method, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id,
                    title,
                    creator_name,
                    collection_type,
                    goal,
                    description,
                    import_method,
                    tags,
                ),
            )
        return self.get_collection_detail(collection_id)

    def list_collections(
        self,
        limit: int = 50,
        creator_name: Optional[str] = None,
        title: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        collection_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        where = []
        params: List[Any] = []
        if creator_name:
            where.append("c.creator_name = ?")
            params.append(creator_name.strip())
        if title:
            where.append("c.title = ?")
            params.append(title.strip())
        source_date_where = []
        if date_from:
            source_date_where.append("DATE(s_date.created_at) >= DATE(?)")
            params.append(date_from.strip())
        if date_to:
            source_date_where.append("DATE(s_date.created_at) <= DATE(?)")
            params.append(date_to.strip())
        if source_date_where:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM learning_collection_sources s_date
                    WHERE s_date.collection_id = c.id
                      AND {}
                )
                """.format(" AND ".join(source_date_where))
            )
        if collection_type:
            where.append("c.collection_type = ?")
            params.append(collection_type.strip())

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT c.*, COUNT(s.id) AS source_count
                FROM learning_collections c
                LEFT JOIN learning_collection_sources s ON s.collection_id = c.id
                {where_sql}
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (*params, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_filter_options(self) -> Dict[str, List[str]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT creator_name
                FROM learning_collections
                WHERE TRIM(creator_name) != ''
                ORDER BY creator_name ASC
                """
            )
            creator_names = [row["creator_name"] for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT DISTINCT title
                FROM learning_collections
                WHERE TRIM(title) != ''
                ORDER BY title ASC
                """
            )
            titles = [row["title"] for row in cursor.fetchall()]
        return {"creator_names": creator_names, "titles": titles}

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

    def save_summary(
        self, collection_id: str, markdown: str, description: str = ""
    ) -> Dict[str, Any]:
        now = datetime.datetime.utcnow().isoformat()
        description = (description or "").strip()
        with self._get_cursor() as cursor:
            if description:
                cursor.execute(
                    """
                    UPDATE learning_collections
                    SET summary_markdown = ?,
                        description = ?,
                        summary_status = 'success',
                        status = 'summarized',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (markdown, description, now, collection_id),
                )
            else:
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

    def mark_exported(self, collection_id: str) -> Dict[str, Any]:
        now = datetime.datetime.utcnow().isoformat()
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE learning_collections
                SET exported_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, collection_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        return self.get_collection_detail(collection_id)

    def save_knowledge_map(
        self,
        collection_id: str,
        scope: str,
        map_json: Dict[str, Any],
        source_id: Optional[str] = None,
        model: str = "",
        status: str = "success",
        error_message: str = "",
    ) -> Dict[str, Any]:
        collection = self.get_collection(collection_id)
        if not collection:
            raise ValueError("collection not found")
        source_key = source_id or ""
        if scope == "source":
            source = self.get_source(source_key)
            if not source or source["collection_id"] != collection_id:
                raise ValueError("source not found")
        elif scope != "collection":
            raise ValueError("scope must be collection or source")

        now = datetime.datetime.utcnow().isoformat()
        map_id = uuid.uuid4().hex
        encoded = json.dumps(map_json, ensure_ascii=False)
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learning_collection_knowledge_maps
                (id, collection_id, scope, source_id, status, map_json, model, error_message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id, scope, source_id) DO UPDATE SET
                    status = excluded.status,
                    map_json = excluded.map_json,
                    model = excluded.model,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    map_id,
                    collection_id,
                    scope,
                    source_key,
                    status,
                    encoded,
                    model or "",
                    error_message or "",
                    now,
                ),
            )
        return self.get_knowledge_map(collection_id, scope, source_id)

    def get_knowledge_map(
        self,
        collection_id: str,
        scope: str,
        source_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        source_key = source_id or ""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM learning_collection_knowledge_maps
                WHERE collection_id = ? AND scope = ? AND source_id = ?
                """,
                (collection_id, scope, source_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["map_json"] = json.loads(item.get("map_json") or "{}")
            except json.JSONDecodeError:
                item["map_json"] = {}
            return item
