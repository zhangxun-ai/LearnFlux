import datetime
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..transcriber.control_database import SQLiteControlDatabase
from ..utils.logging import setup_logger
from ..utils.task_progress import build_progress
from ..utils.task_status import TaskStatus
from .identity import normalize_collection_identity_field

logger = setup_logger("learning_collections")

COLLECTION_TYPES = {"video_course", "document_topic"}
SOURCE_TYPES_BY_COLLECTION = {
    "video_course": {"video"},
    "document_topic": {"document"},
}


class _ConnectionCursor:
    """Cursor-shaped facade for control database connection adapters."""

    def __init__(self, connection: object):
        self.connection = connection
        self._result = None

    def execute(self, statement: str, parameters=None):
        self._result = (
            self.connection.execute(statement)
            if parameters is None
            else self.connection.execute(statement, parameters)
        )
        return self

    @property
    def rowcount(self) -> int:
        return int(getattr(self._result, "rowcount", 0))

    def fetchone(self):
        return self._result.fetchone()

    def fetchall(self):
        return self._result.fetchall()


def _row_value(row: object, key: str, index: int):
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _read_legacy_rows(
    connection: sqlite3.Connection, table_name: str
) -> List[Dict[str, Any]]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if not exists:
        return []
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table_name}")]


class LearningCollectionRepository:
    """Repository for topic-level learning collections."""

    def __init__(self, db_path: str | Path | object):
        if hasattr(db_path, "connect") and hasattr(db_path, "transaction"):
            self.database = db_path
            raw_path = getattr(db_path, "path", None)
            self.db_path = Path(raw_path) if raw_path else None
            self._owns_database = False
        else:
            self.database = SQLiteControlDatabase(db_path)
            self.db_path = Path(db_path)
            self._owns_database = True
        self._init_database()

    @contextmanager
    def _get_cursor(self, *, write: bool = False):
        if write:
            with self.database.transaction() as connection:
                yield _ConnectionCursor(connection)
            return

        connection = self.database.connect()
        try:
            yield _ConnectionCursor(connection)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        else:
            if connection.in_transaction:
                connection.commit()
        finally:
            connection.close()

    def close(self):
        if self._owns_database:
            self.database.close()

    def _init_database(self):
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_collections (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT,
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
                    transcription_strategy TEXT NOT NULL DEFAULT 'local',
                    transcription_concurrency INTEGER NOT NULL DEFAULT 1,
                    transcription_revision INTEGER NOT NULL DEFAULT 0,
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
                    content_sha256 TEXT,
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_collection_summary_jobs (
                    job_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'queued',
                    phase TEXT NOT NULL DEFAULT 'queued',
                    worker_id TEXT NOT NULL DEFAULT '',
                    attempt INTEGER NOT NULL DEFAULT 0,
                    total_modules INTEGER NOT NULL DEFAULT 0,
                    completed_modules INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    started_at TIMESTAMP,
                    heartbeat_at TIMESTAMP,
                    lease_until TIMESTAMP,
                    deadline_seconds INTEGER NOT NULL DEFAULT 720,
                    deadline_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (collection_id) REFERENCES learning_collections(id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_summary_jobs_status
                ON learning_collection_summary_jobs(status, created_at)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_collection_summary_modules (
                    job_id TEXT NOT NULL,
                    module_index INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    source_numbers TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'queued',
                    markdown TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (job_id, module_index),
                    FOREIGN KEY (job_id) REFERENCES learning_collection_summary_jobs(job_id)
                )
                """
            )
        self._migrate_database()

    def _migrate_database(self):
        with self._get_cursor(write=True) as cursor:
            columns = self._table_columns(cursor, "learning_collections")
            migrations = [
                ("creator_name", "TEXT NOT NULL DEFAULT ''"),
                ("description", "TEXT NOT NULL DEFAULT ''"),
                ("import_method", "TEXT NOT NULL DEFAULT ''"),
                ("tags", "TEXT NOT NULL DEFAULT ''"),
                ("exported_at", "TIMESTAMP"),
                ("owner_user_id", "TEXT"),
                ("transcription_strategy", "TEXT NOT NULL DEFAULT 'local'"),
                ("transcription_concurrency", "INTEGER NOT NULL DEFAULT 1"),
                ("transcription_revision", "INTEGER NOT NULL DEFAULT 0"),
            ]
            for name, definition in migrations:
                if name not in columns:
                    cursor.execute(
                        f"ALTER TABLE learning_collections ADD COLUMN {name} {definition}"
                    )
            source_columns = self._table_columns(
                cursor, "learning_collection_sources"
            )
            if "content_sha256" not in source_columns:
                cursor.execute(
                    "ALTER TABLE learning_collection_sources "
                    "ADD COLUMN content_sha256 TEXT"
                )
            summary_job_columns = self._table_columns(
                cursor, "learning_collection_summary_jobs"
            )
            if "deadline_seconds" not in summary_job_columns:
                cursor.execute(
                    "ALTER TABLE learning_collection_summary_jobs "
                    "ADD COLUMN deadline_seconds INTEGER NOT NULL DEFAULT 720"
                )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    uq_learning_sources_collection_content_sha256
                ON learning_collection_sources(collection_id, content_sha256)
                WHERE content_sha256 IS NOT NULL
                """
            )
            # Hard uniqueness: one collection per owner + creator + title.
            # IFNULL keeps legacy NULL owners in the same identity space as ''.
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    uq_learning_collections_owner_creator_title
                ON learning_collections(
                    IFNULL(owner_user_id, ''),
                    creator_name,
                    title
                )
                """
            )

    def _table_columns(self, cursor, table_name: str) -> set[str]:
        if getattr(self.database, "dialect", "sqlite") == "postgres":
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = ?
                """,
                (table_name,),
            )
            return {_row_value(row, "column_name", 0) for row in cursor.fetchall()}
        cursor.execute(f"PRAGMA table_info({table_name})")
        return {_row_value(row, "name", 1) for row in cursor.fetchall()}

    @staticmethod
    def _delete_summary_job_records(cursor, collection_id: str) -> None:
        cursor.execute(
            """
            DELETE FROM learning_collection_summary_modules
            WHERE job_id IN (
                SELECT job_id FROM learning_collection_summary_jobs
                WHERE collection_id = ?
            )
            """,
            (collection_id,),
        )
        cursor.execute(
            "DELETE FROM learning_collection_summary_jobs WHERE collection_id = ?",
            (collection_id,),
        )

    def import_legacy_sqlite_if_target_empty(
        self, legacy_db_path: str | Path
    ) -> Dict[str, Any]:
        """Copy legacy collection rows into an empty PostgreSQL authority.

        The import is intentionally additive and refuses to merge into a target
        that already contains collections.
        """
        if getattr(self.database, "dialect", "sqlite") != "postgres":
            return {"status": "skipped_non_postgres"}

        legacy_path = Path(legacy_db_path)
        if not legacy_path.exists():
            return {"status": "skipped_no_legacy_database"}

        legacy_connection = sqlite3.connect(str(legacy_path))
        legacy_connection.row_factory = sqlite3.Row
        try:
            collections = _read_legacy_rows(
                legacy_connection, "learning_collections"
            )
            if not collections:
                return {"status": "skipped_no_legacy_collections"}
            sources = _read_legacy_rows(
                legacy_connection, "learning_collection_sources"
            )
            knowledge_maps = _read_legacy_rows(
                legacy_connection, "learning_collection_knowledge_maps"
            )
        finally:
            legacy_connection.close()

        now = datetime.datetime.utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM learning_collections")
            target_count = int(_row_value(cursor.fetchone(), "count", 0))
            if target_count:
                return {
                    "status": "refused_target_not_empty",
                    "target_collections": target_count,
                }

            collection_ids = {row["id"] for row in collections}
            imported_sources = [
                row for row in sources if row.get("collection_id") in collection_ids
            ]
            imported_maps = [
                row
                for row in knowledge_maps
                if row.get("collection_id") in collection_ids
            ]
            for row in collections:
                cursor.execute(
                    """
                    INSERT INTO learning_collections (
                        id, owner_user_id, title, creator_name, collection_type,
                        goal, description, import_method, tags, exported_at,
                        status, summary_status, summary_markdown,
                        transcription_strategy, transcription_concurrency,
                        transcription_revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row.get("owner_user_id"),
                        row.get("title") or "",
                        row.get("creator_name") or "",
                        row.get("collection_type") or "video_course",
                        row.get("goal") or "",
                        row.get("description") or "",
                        row.get("import_method") or "",
                        row.get("tags") or "",
                        row.get("exported_at"),
                        row.get("status") or "draft",
                        row.get("summary_status") or "not_started",
                        row.get("summary_markdown"),
                        row.get("transcription_strategy") or "local",
                        int(row.get("transcription_concurrency") or 1),
                        int(row.get("transcription_revision") or 0),
                        row.get("created_at") or now,
                        row.get("updated_at") or now,
                    ),
                )
            for row in imported_sources:
                cursor.execute(
                    """
                    INSERT INTO learning_collection_sources (
                        id, collection_id, task_id, view_token, title,
                        source_type, content_sha256, position, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["collection_id"],
                        row.get("task_id") or "",
                        row.get("view_token") or "",
                        row.get("title") or "",
                        row.get("source_type") or "video",
                        row.get("content_sha256"),
                        int(row.get("position") or 1),
                        row.get("created_at") or now,
                    ),
                )
            for row in imported_maps:
                cursor.execute(
                    """
                    INSERT INTO learning_collection_knowledge_maps (
                        id, collection_id, scope, source_id, status, map_json,
                        model, error_message, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["collection_id"],
                        row.get("scope") or "collection",
                        row.get("source_id") or "",
                        row.get("status") or "success",
                        row.get("map_json") or "{}",
                        row.get("model") or "",
                        row.get("error_message") or "",
                        row.get("created_at") or now,
                        row.get("updated_at") or now,
                    ),
                )

        return {
            "status": "imported",
            "collections": len(collections),
            "sources": len(imported_sources),
            "knowledge_maps": len(imported_maps),
        }

    def create_collection(
        self,
        title: str,
        creator_name: str,
        collection_type: str,
        goal: str = "",
        description: str = "",
        import_method: str = "",
        tags: str = "",
        owner_user_id: str = "",
        transcription_strategy: str = "local",
        transcription_concurrency: int = 1,
    ) -> Dict[str, Any]:
        title = normalize_collection_identity_field(title)
        creator_name = normalize_collection_identity_field(creator_name)
        collection_type = (collection_type or "").strip()
        goal = (goal or "").strip()
        description = (description or "").strip()
        import_method = (import_method or "").strip()
        tags = (tags or "").strip()
        owner_user_id = (owner_user_id or "").strip()

        if not title:
            raise ValueError("title is required")
        if not creator_name:
            raise ValueError("creator_name is required")
        if collection_type not in COLLECTION_TYPES:
            raise ValueError("collection_type must be video_course or document_topic")

        # Race-safe reuse under the unique identity index.
        existing = self.find_collection_by_identity(
            creator_name=creator_name,
            title=title,
            owner_user_id=owner_user_id,
        )
        if existing:
            detail = self.get_collection_detail(existing["id"])
            detail["created"] = False
            detail["reused"] = True
            return detail

        collection_id = uuid.uuid4().hex
        try:
            with self._get_cursor(write=True) as cursor:
                cursor.execute(
                    """
                    INSERT INTO learning_collections
                    (id, owner_user_id, title, creator_name, collection_type, goal,
                     description, import_method, tags, transcription_strategy,
                     transcription_concurrency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        collection_id,
                        owner_user_id or None,
                        title,
                        creator_name,
                        collection_type,
                        goal,
                        description,
                        import_method,
                        tags,
                        transcription_strategy,
                        transcription_concurrency,
                    ),
                )
        except Exception as exc:
            # Concurrent create of the same identity: return the winner.
            message = str(exc).lower()
            if "unique" in message or "uq_learning_collections_owner_creator_title" in message:
                existing = self.find_collection_by_identity(
                    creator_name=creator_name,
                    title=title,
                    owner_user_id=owner_user_id,
                )
                if existing:
                    detail = self.get_collection_detail(existing["id"])
                    detail["created"] = False
                    detail["reused"] = True
                    return detail
            raise
        detail = self.get_collection_detail(collection_id)
        detail["created"] = True
        detail["reused"] = False
        return detail

    def update_transcription_preferences(
        self,
        collection_id: str,
        *,
        strategy: str,
        requested_concurrency: int,
    ) -> Dict[str, Any]:
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collections
                SET transcription_strategy = ?,
                    transcription_concurrency = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (strategy, requested_concurrency, collection_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        return self.get_collection_detail(collection_id)

    def find_collection_by_identity(
        self,
        *,
        creator_name: str,
        title: str,
        owner_user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the newest collection with the same creator + title (and owner)."""
        creator_name = normalize_collection_identity_field(creator_name)
        title = normalize_collection_identity_field(title)
        if not creator_name or not title:
            return None
        where = ["c.creator_name = ?", "c.title = ?"]
        params: List[Any] = [creator_name, title]
        if owner_user_id is not None:
            where.append("IFNULL(c.owner_user_id, '') = ?")
            params.append((owner_user_id or "").strip())
        params.append(1)
        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT c.*
                FROM learning_collections c
                WHERE {' AND '.join(where)}
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                tuple(params),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_collections(
        self,
        limit: int = 50,
        creator_name: Optional[str] = None,
        title: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        collection_type: Optional[str] = None,
        owner_user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        where = []
        params: List[Any] = []
        if owner_user_id is not None:
            where.append("c.owner_user_id = ?")
            params.append(owner_user_id.strip())
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

    def get_filter_options(self, owner_user_id: Optional[str] = None) -> Dict[str, Any]:
        owner_where = " AND owner_user_id = ?" if owner_user_id is not None else ""
        params = (owner_user_id.strip(),) if owner_user_id is not None else ()
        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT creator_name
                FROM learning_collections
                WHERE TRIM(creator_name) != ''{owner_where}
                ORDER BY creator_name ASC
                """,
                params,
            )
            creator_names = [row["creator_name"] for row in cursor.fetchall()]
            cursor.execute(
                f"""
                SELECT DISTINCT title
                FROM learning_collections
                WHERE TRIM(title) != ''{owner_where}
                ORDER BY title ASC
                """,
                params,
            )
            titles = [row["title"] for row in cursor.fetchall()]
            cursor.execute(
                f"""
                SELECT creator_name, title
                FROM learning_collections
                WHERE TRIM(creator_name) != ''
                  AND TRIM(title) != ''{owner_where}
                ORDER BY creator_name ASC, title ASC
                """,
                params,
            )
            titles_by_creator: Dict[str, List[str]] = {}
            for row in cursor.fetchall():
                creator = row["creator_name"]
                title = row["title"]
                bucket = titles_by_creator.setdefault(creator, [])
                if title not in bucket:
                    bucket.append(title)
        return {
            "creator_names": creator_names,
            "titles": titles,
            "titles_by_creator": titles_by_creator,
        }

    def assign_unowned_collections(self, owner_user_id: str) -> int:
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collections
                SET owner_user_id = ?
                WHERE owner_user_id IS NULL OR TRIM(owner_user_id) = ''
                """,
                ((owner_user_id or "").strip(),),
            )
            return cursor.rowcount

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
        content_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        collection = self.get_collection(collection_id)
        if not collection:
            raise ValueError("collection not found")

        allowed = SOURCE_TYPES_BY_COLLECTION[collection["collection_type"]]
        if source_type not in allowed:
            raise ValueError(
                f"{collection['collection_type']} collection only accepts {sorted(allowed)}"
            )

        source_id = uuid.uuid4().hex
        with self._get_cursor(write=True) as cursor:
            if position is None:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(position), 0) + 1 AS next_position
                    FROM learning_collection_sources
                    WHERE collection_id = ?
                    """,
                    (collection_id,),
                )
                position = int(cursor.fetchone()["next_position"])
            if position is not None:
                cursor.execute(
                    """
                    UPDATE learning_collection_sources
                    SET position = position + 1
                    WHERE collection_id = ? AND position >= ?
                    """,
                    (collection_id, int(position)),
                )
            cursor.execute(
                """
                INSERT INTO learning_collection_sources
                (id, collection_id, task_id, view_token, title, source_type,
                 content_sha256, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    collection_id,
                    task_id,
                    view_token,
                    title,
                    source_type,
                    content_sha256,
                    int(position),
                ),
            )
            cursor.execute(
                """
                UPDATE learning_collections
                SET status = 'processing',
                    summary_status = 'not_started',
                    summary_markdown = NULL,
                    exported_at = NULL,
                    transcription_revision = transcription_revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (collection_id,),
            )
            self._delete_summary_job_records(cursor, collection_id)
            cursor.execute(
                """
                DELETE FROM learning_collection_knowledge_maps
                WHERE collection_id = ? AND scope = 'collection'
                """,
                (collection_id,),
            )
        return self.get_source(source_id)

    def get_source_by_content_hash(
        self, collection_id: str, content_sha256: str
    ) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM learning_collection_sources
                WHERE collection_id = ? AND content_sha256 = ?
                LIMIT 1
                """,
                (collection_id, content_sha256),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def backfill_source_content_hash(
        self,
        source_id: str,
        *,
        expected_task_id: str,
        content_sha256: str,
    ) -> Dict[str, Any]:
        """Attach a verified full hash to one legacy source without replacing it."""
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT * FROM learning_collection_sources
                WHERE id = ? AND task_id = ?
                """,
                (source_id, expected_task_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("source changed during legacy reconciliation")
            source = dict(row)
            stored_hash = source.get("content_sha256")
            if stored_hash:
                if stored_hash != content_sha256:
                    raise ValueError("source hash changed during legacy reconciliation")
                return source
            cursor.execute(
                """
                UPDATE learning_collection_sources
                SET content_sha256 = ?
                WHERE id = ? AND task_id = ? AND content_sha256 IS NULL
                """,
                (content_sha256, source_id, expected_task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("source changed during legacy reconciliation")
        return self.get_source(source_id)

    def register_source_batch(
        self,
        collection_id: str,
        entries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Register one upload batch and invalidate derived state atomically.

        The collection revision advances once per committed insert or task
        replacement. Conflicts keep the source currently stored unless the
        caller supplied an exact source/task snapshot for a CAS replacement.
        """
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                "SELECT * FROM learning_collections WHERE id = ?",
                (collection_id,),
            )
            collection_row = cursor.fetchone()
            if not collection_row:
                raise ValueError("collection not found")
            collection = dict(collection_row)
            allowed = SOURCE_TYPES_BY_COLLECTION[collection["collection_type"]]
            task_status_columns = self._table_columns(cursor, "task_status")
            for entry in entries:
                if entry["source_type"] not in allowed:
                    raise ValueError(
                        f"{collection['collection_type']} collection only accepts "
                        f"{sorted(allowed)}"
                    )

            results: List[Dict[str, Any]] = []
            replaced_source_ids: List[str] = []
            change_count = 0
            for entry in entries:
                content_sha256 = str(entry["content_sha256"])
                cursor.execute(
                    """
                    SELECT * FROM learning_collection_sources
                    WHERE collection_id = ? AND content_sha256 = ?
                    LIMIT 1
                    """,
                    (collection_id, content_sha256),
                )
                current_row = cursor.fetchone()
                current = dict(current_row) if current_row else None

                expected_source_id = entry.get("replace_source_id")
                expected_task_id = entry.get("replace_task_id")
                replace_source_id = None
                replace_task_id = None
                if (
                    current
                    and expected_source_id
                    and expected_task_id
                    and current["id"] == expected_source_id
                    and current["task_id"] == expected_task_id
                ):
                    replace_source_id = expected_source_id
                    replace_task_id = expected_task_id
                elif current and entry.get("is_cache_alias"):
                    current_status = self._task_status_for_registration(
                        cursor,
                        current["task_id"],
                        columns=task_status_columns,
                    )
                    if current_status != TaskStatus.SUCCESS:
                        replace_source_id = current["id"]
                        replace_task_id = current["task_id"]

                if replace_source_id and replace_task_id:
                    cursor.execute(
                        """
                        UPDATE learning_collection_sources
                        SET task_id = ?, view_token = ?
                        WHERE id = ? AND task_id = ?
                        """,
                        (
                            entry["task_id"],
                            entry["view_token"],
                            replace_source_id,
                            replace_task_id,
                        ),
                    )
                    if cursor.rowcount == 1:
                        self._cancel_replaced_task_if_queued(
                            cursor,
                            replace_task_id,
                            columns=task_status_columns,
                        )
                        cursor.execute(
                            "SELECT * FROM learning_collection_sources WHERE id = ?",
                            (replace_source_id,),
                        )
                        source = dict(cursor.fetchone())
                        results.append(
                            {
                                "source": source,
                                "outcome": "replaced",
                                "previous_task_id": current["task_id"],
                                "previous_view_token": current["view_token"],
                            }
                        )
                        replaced_source_ids.append(source["id"])
                        change_count += 1
                        continue

                if current:
                    results.append({"source": current, "outcome": "existing"})
                    continue

                source_id = uuid.uuid4().hex
                position = entry.get("position")
                if position is None:
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(position), 0) + 1 AS next_position
                        FROM learning_collection_sources
                        WHERE collection_id = ?
                        """,
                        (collection_id,),
                    )
                    position = int(cursor.fetchone()["next_position"])
                position = int(position)
                cursor.execute(
                    """
                    INSERT INTO learning_collection_sources
                    (id, collection_id, task_id, view_token, title, source_type,
                     content_sha256, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        source_id,
                        collection_id,
                        entry["task_id"],
                        entry["view_token"],
                        entry["title"],
                        entry["source_type"],
                        content_sha256,
                        position,
                    ),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        SELECT * FROM learning_collection_sources
                        WHERE collection_id = ? AND content_sha256 = ?
                        LIMIT 1
                        """,
                        (collection_id, content_sha256),
                    )
                    conflict_row = cursor.fetchone()
                    if not conflict_row:
                        raise RuntimeError(
                            "collection_source_unique_conflict_without_row"
                        )
                    results.append(
                        {"source": dict(conflict_row), "outcome": "existing"}
                    )
                    continue

                cursor.execute(
                    """
                    UPDATE learning_collection_sources
                    SET position = position + 1
                    WHERE collection_id = ? AND id != ? AND position >= ?
                    """,
                    (collection_id, source_id, position),
                )
                cursor.execute(
                    "SELECT * FROM learning_collection_sources WHERE id = ?",
                    (source_id,),
                )
                results.append(
                    {"source": dict(cursor.fetchone()), "outcome": "inserted"}
                )
                change_count += 1

            if change_count:
                cursor.execute(
                    """
                    UPDATE learning_collections
                    SET status = 'processing',
                        summary_status = 'not_started',
                        summary_markdown = NULL,
                        exported_at = NULL,
                        transcription_revision = transcription_revision + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (change_count, collection_id),
                )
                self._delete_summary_job_records(cursor, collection_id)
                cursor.execute(
                    """
                    DELETE FROM learning_collection_knowledge_maps
                    WHERE collection_id = ? AND scope = 'collection'
                    """,
                    (collection_id,),
                )
                for source_id in replaced_source_ids:
                    cursor.execute(
                        """
                        DELETE FROM learning_collection_knowledge_maps
                        WHERE collection_id = ? AND scope = 'source'
                          AND source_id = ?
                        """,
                        (collection_id, source_id),
                    )
            for result in results:
                cursor.execute(
                    "SELECT * FROM learning_collection_sources WHERE id = ?",
                    (result["source"]["id"],),
                )
                result["source"] = dict(cursor.fetchone())
            return results

    @staticmethod
    def _task_status_for_registration(
        cursor: _ConnectionCursor,
        task_id: str,
        *,
        columns: set[str],
    ) -> Optional[str]:
        """Read the current source task status from the shared control DB."""
        if "status" not in columns:
            raise RuntimeError("task_status_schema_missing")
        cursor.execute(
            "SELECT status FROM task_status WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        return str(_row_value(row, "status", 0)) if row else None

    @staticmethod
    def _cancel_replaced_task_if_queued(
        cursor: _ConnectionCursor,
        task_id: str,
        *,
        columns: set[str],
    ) -> None:
        """Cancel a replaced queued task inside the source CAS transaction."""
        if not columns:
            raise RuntimeError("task_status_schema_missing")
        required = {
            "status",
            "error_message",
            "progress_json",
            "completed_at",
        }
        if not required.issubset(columns):
            missing = sorted(required - columns)
            raise RuntimeError(
                "task_status_schema_incompatible:" + ",".join(missing)
            )
        if not {"updated_at", "last_heartbeat_at"}.intersection(columns):
            raise RuntimeError("task_status_schema_incompatible:timestamp")

        cursor.execute(
            "SELECT status FROM task_status WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        if not row or _row_value(row, "status", 0) != TaskStatus.QUEUED:
            return

        timestamp_column = None
        if "updated_at" in columns:
            timestamp_column = "updated_at"
        elif "last_heartbeat_at" in columns:
            timestamp_column = "last_heartbeat_at"
        timestamp_assignment = f", {timestamp_column} = CURRENT_TIMESTAMP"
        error_message = "被同内容成功缓存替代"
        progress = build_progress(
            stage="canceled",
            stage_label="任务已取消",
            basis="task_canceled",
            confidence="high",
            message=error_message,
        )
        cursor.execute(
            f"""
            UPDATE task_status
            SET status = ?, error_message = ?, progress_json = ?,
                completed_at = CURRENT_TIMESTAMP{timestamp_assignment}
            WHERE task_id = ? AND status = ?
            """,
            (
                TaskStatus.CANCELED,
                error_message,
                json.dumps(progress, ensure_ascii=False),
                task_id,
                TaskStatus.QUEUED,
            ),
        )
        if cursor.rowcount == 1:
            return

        cursor.execute(
            "SELECT status FROM task_status WHERE task_id = ?",
            (task_id,),
        )
        current = cursor.fetchone()
        if current and _row_value(current, "status", 0) == TaskStatus.QUEUED:
            raise RuntimeError("queued_task_cancel_not_applied")

    def replace_source_task_if_current(
        self,
        source_id: str,
        *,
        expected_task_id: str,
        task_id: str,
        view_token: str,
    ) -> bool:
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT collection_id
                FROM learning_collection_sources
                WHERE id = ?
                """,
                (source_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            collection_id = row["collection_id"]
            cursor.execute(
                """
                UPDATE learning_collection_sources
                SET task_id = ?, view_token = ?
                WHERE id = ? AND task_id = ?
                """,
                (task_id, view_token, source_id, expected_task_id),
            )
            if cursor.rowcount == 0:
                return False
            cursor.execute(
                """
                UPDATE learning_collections
                SET transcription_revision = transcription_revision + 1,
                    status = 'processing',
                    summary_status = 'not_started',
                    summary_markdown = NULL,
                    exported_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (collection_id,),
            )
            self._delete_summary_job_records(cursor, collection_id)
            cursor.execute(
                """
                DELETE FROM learning_collection_knowledge_maps
                WHERE collection_id = ?
                  AND (scope = 'collection' OR (scope = 'source' AND source_id = ?))
                """,
                (collection_id, source_id),
            )
            return True

    def update_source_task(
        self,
        source_id: str,
        task_id: str,
        view_token: str,
    ) -> Dict[str, Any]:
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT collection_id FROM learning_collection_sources
                WHERE id = ?
                """,
                (source_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("source not found")
            collection_id = row["collection_id"]
            cursor.execute(
                """
                UPDATE learning_collection_sources
                SET task_id = ?, view_token = ?
                WHERE id = ?
                """,
                (task_id, view_token, source_id),
            )
            cursor.execute(
                """
                UPDATE learning_collections
                SET status = 'processing',
                    summary_status = 'not_started',
                    summary_markdown = NULL,
                    exported_at = NULL,
                    transcription_revision = transcription_revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (collection_id,),
            )
            self._delete_summary_job_records(cursor, collection_id)
            cursor.execute(
                """
                DELETE FROM learning_collection_knowledge_maps
                WHERE collection_id = ?
                  AND (scope = 'collection' OR (scope = 'source' AND source_id = ?))
                """,
                (collection_id, source_id),
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

    def get_source_with_collection_by_view_token(
        self, view_token: str
    ) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    s.*,
                    c.title AS collection_title,
                    c.creator_name AS collection_creator_name,
                    c.collection_type AS collection_type
                FROM learning_collection_sources s
                JOIN learning_collections c ON c.id = s.collection_id
                WHERE s.view_token = ?
                LIMIT 1
                """,
                (view_token,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_collection_detail(self, collection_id: str) -> Optional[Dict[str, Any]]:
        collection = self.get_collection(collection_id)
        if not collection:
            return None
        collection["sources"] = self.get_sources(collection_id)
        return collection

    def enqueue_summary_job(
        self,
        collection_id: str,
        *,
        deadline_seconds: int = 600,
    ) -> Dict[str, Any]:
        """Replace the terminal job for a collection with one durable queued job."""
        now = _utcnow()
        job_id = uuid.uuid4().hex
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                "SELECT job_id FROM learning_collection_summary_jobs WHERE collection_id = ?",
                (collection_id,),
            )
            existing = cursor.fetchone()
            if existing:
                previous_job_id = _row_value(existing, "job_id", 0)
                cursor.execute(
                    "DELETE FROM learning_collection_summary_modules WHERE job_id = ?",
                    (previous_job_id,),
                )
                cursor.execute(
                    "DELETE FROM learning_collection_summary_jobs WHERE job_id = ?",
                    (previous_job_id,),
                )
            cursor.execute(
                """
                INSERT INTO learning_collection_summary_jobs (
                    job_id, collection_id, status, phase, deadline_seconds,
                    progress_message, created_at, updated_at
                ) VALUES (?, ?, 'queued', 'queued', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    collection_id,
                    max(1, int(deadline_seconds)),
                    "Waiting for summary worker",
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            cursor.execute(
                """
                UPDATE learning_collections
                SET summary_status = 'processing', updated_at = ?
                WHERE id = ?
                """,
                (now.isoformat(), collection_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        return self.get_summary_job(collection_id)

    def get_summary_job(self, collection_id: str) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM learning_collection_summary_jobs
                WHERE collection_id = ?
                """,
                (collection_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def get_summary_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM learning_collection_summary_jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def requeue_summary_job(
        self,
        job_id: str,
        *,
        deadline_seconds: int,
    ) -> bool:
        """Retry one failed job while preserving successful module checkpoints."""
        now = _utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT status
                FROM learning_collection_summary_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            job_row = cursor.fetchone()
            if not job_row or _row_value(job_row, "status", 0) != "failed":
                return False
            cursor.execute(
                """
                UPDATE learning_collection_summary_modules
                SET status = 'queued', error_message = '', started_at = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE job_id = ? AND status != 'success'
                """,
                (now, job_id),
            )
            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS completed
                FROM learning_collection_summary_modules
                WHERE job_id = ?
                """,
                (job_id,),
            )
            count_row = cursor.fetchone()
            total = int(_row_value(count_row, "total", 0) or 0)
            completed = int(_row_value(count_row, "completed", 1) or 0)
            phase = "modules" if total else "queued"
            message = (
                f"Resuming from module {completed}/{total}"
                if total
                else "Waiting for summary worker"
            )
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET status = 'queued', phase = ?, worker_id = '',
                    deadline_seconds = ?, deadline_at = NULL,
                    total_modules = ?, completed_modules = ?,
                    progress_message = ?, error_message = '', started_at = NULL,
                    completed_at = NULL, heartbeat_at = NULL, lease_until = NULL,
                    updated_at = ?
                WHERE job_id = ? AND status = 'failed'
                """,
                (
                    phase,
                    max(1, int(deadline_seconds)),
                    total,
                    completed,
                    message,
                    now,
                    job_id,
                ),
            )
            requeued = cursor.rowcount == 1
            if requeued:
                cursor.execute(
                    """
                    UPDATE learning_collections
                    SET summary_status = 'processing', updated_at = ?
                    WHERE id = (
                        SELECT collection_id
                        FROM learning_collection_summary_jobs
                        WHERE job_id = ?
                    )
                    """,
                    (now, job_id),
                )
        return requeued

    @staticmethod
    def _renew_summary_job_deadline(cursor, job_id: str, now: datetime.datetime) -> None:
        cursor.execute(
            """
            SELECT deadline_seconds
            FROM learning_collection_summary_jobs
            WHERE job_id = ? AND status = 'running'
            """,
            (job_id,),
        )
        row = cursor.fetchone()
        if not row:
            return
        deadline_seconds = int(_row_value(row, "deadline_seconds", 0) or 720)
        deadline_at = now + datetime.timedelta(seconds=max(1, deadline_seconds))
        cursor.execute(
            """
            UPDATE learning_collection_summary_jobs
            SET deadline_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (deadline_at.isoformat(), job_id),
        )

    def claim_next_summary_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Atomically lease the oldest queued summary job to one worker."""
        now = _utcnow()
        lease_until = now + datetime.timedelta(seconds=max(1, int(lease_seconds)))
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT job_id, deadline_seconds FROM learning_collection_summary_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return None
            job_id = _row_value(row, "job_id", 0)
            deadline_seconds = int(_row_value(row, "deadline_seconds", 1) or 720)
            deadline_at = now + datetime.timedelta(seconds=max(1, deadline_seconds))
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET status = 'running', worker_id = ?, attempt = attempt + 1,
                    started_at = COALESCE(started_at, ?), heartbeat_at = ?,
                    lease_until = ?, deadline_at = ?,
                    progress_message = 'Summary worker started',
                    updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (
                    worker_id,
                    now.isoformat(),
                    now.isoformat(),
                    lease_until.isoformat(),
                    deadline_at.isoformat(),
                    now.isoformat(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            cursor.execute(
                "SELECT * FROM learning_collection_summary_jobs WHERE job_id = ?",
                (job_id,),
            )
            claimed = cursor.fetchone()
        return dict(claimed) if claimed else None

    def heartbeat_summary_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 60,
    ) -> bool:
        now = _utcnow()
        lease_until = now + datetime.timedelta(seconds=max(1, int(lease_seconds)))
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET heartbeat_at = ?, lease_until = ?, updated_at = ?
                WHERE job_id = ? AND worker_id = ? AND status = 'running'
                """,
                (
                    now.isoformat(),
                    lease_until.isoformat(),
                    now.isoformat(),
                    job_id,
                    worker_id,
                ),
            )
            return cursor.rowcount == 1

    def update_summary_job_progress(
        self,
        job_id: str,
        *,
        phase: str,
        message: str,
    ) -> None:
        now = _utcnow()
        with self._get_cursor(write=True) as cursor:
            self._renew_summary_job_deadline(cursor, job_id, now)
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET phase = ?, progress_message = ?, heartbeat_at = ?, updated_at = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (phase, message, now.isoformat(), now.isoformat(), job_id),
            )

    def save_summary_plan(
        self,
        job_id: str,
        modules: List[Dict[str, Any]],
    ) -> None:
        now = _utcnow()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                "DELETE FROM learning_collection_summary_modules WHERE job_id = ?",
                (job_id,),
            )
            for fallback_index, module in enumerate(modules):
                module_index = int(module.get("index", fallback_index))
                cursor.execute(
                    """
                    INSERT INTO learning_collection_summary_modules (
                        job_id, module_index, title, role, rationale,
                        source_numbers, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
                    """,
                    (
                        job_id,
                        module_index,
                        str(module.get("title") or ""),
                        str(module.get("role") or ""),
                        str(module.get("rationale") or ""),
                        json.dumps(module.get("source_numbers") or []),
                        now.isoformat(),
                    ),
                )
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET phase = 'modules', total_modules = ?, completed_modules = 0,
                    progress_message = ?, heartbeat_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    len(modules),
                    f"Generating module 0/{len(modules)}",
                    now.isoformat(),
                    now.isoformat(),
                    job_id,
                ),
            )
            self._renew_summary_job_deadline(cursor, job_id, now)

    def list_summary_modules(self, job_id: str) -> List[Dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM learning_collection_summary_modules
                WHERE job_id = ?
                ORDER BY module_index ASC
                """,
                (job_id,),
            )
            rows = cursor.fetchall()
        modules = []
        for row in rows:
            module = dict(row)
            try:
                module["source_numbers"] = json.loads(module.get("source_numbers") or "[]")
            except (TypeError, ValueError):
                module["source_numbers"] = []
            module["index"] = int(module.get("module_index") or 0)
            modules.append(module)
        return modules

    def mark_summary_module_running(self, job_id: str, module_index: int) -> None:
        now = _utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_modules
                SET status = 'running', error_message = '', started_at = ?, updated_at = ?
                WHERE job_id = ? AND module_index = ? AND status != 'success'
                """,
                (now, now, job_id, int(module_index)),
            )

    def complete_summary_module(
        self,
        job_id: str,
        module_index: int,
        markdown: str,
    ) -> None:
        now = _utcnow()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_modules
                SET status = 'success', markdown = ?, error_message = '',
                    completed_at = ?, updated_at = ?
                WHERE job_id = ? AND module_index = ?
                """,
                (
                    markdown,
                    now.isoformat(),
                    now.isoformat(),
                    job_id,
                    int(module_index),
                ),
            )
            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS completed
                FROM learning_collection_summary_modules
                WHERE job_id = ?
                """,
                (job_id,),
            )
            count_row = cursor.fetchone()
            total = int(_row_value(count_row, "total", 0) or 0)
            completed = int(_row_value(count_row, "completed", 1) or 0)
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET total_modules = ?, completed_modules = ?, progress_message = ?,
                    heartbeat_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    total,
                    completed,
                    f"Generating module {completed}/{total}",
                    now.isoformat(),
                    now.isoformat(),
                    job_id,
                ),
            )
            self._renew_summary_job_deadline(cursor, job_id, now)

    def fail_summary_module(
        self,
        job_id: str,
        module_index: int,
        error_message: str,
    ) -> None:
        now = _utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_modules
                SET status = 'failed', error_message = ?, completed_at = ?, updated_at = ?
                WHERE job_id = ? AND module_index = ?
                """,
                (str(error_message), now, now, job_id, int(module_index)),
            )

    def complete_summary_job(self, job_id: str) -> None:
        now = _utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET status = 'success', phase = 'completed', worker_id = '',
                    progress_message = 'Summary completed', error_message = '',
                    completed_at = ?, heartbeat_at = ?, lease_until = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (now, now, now, job_id),
            )

    def fail_summary_job(self, job_id: str, error_message: str) -> None:
        now = _utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET status = 'failed', phase = 'failed', worker_id = '',
                    progress_message = 'Summary failed', error_message = ?,
                    completed_at = ?, heartbeat_at = ?, lease_until = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (str(error_message), now, now, now, job_id),
            )

    def fail_expired_summary_job(self, collection_id: str) -> bool:
        """Fail one running job only when its persisted lease has expired."""
        now = _utcnow().isoformat()
        error_message = "Summary worker heartbeat expired. Please retry."
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collection_summary_jobs
                SET status = 'failed', phase = 'failed', worker_id = '',
                    progress_message = 'Summary interrupted', error_message = ?,
                    completed_at = ?, heartbeat_at = ?, lease_until = NULL,
                    updated_at = ?
                WHERE collection_id = ? AND status = 'running'
                  AND lease_until IS NOT NULL AND lease_until <= ?
                """,
                (
                    error_message,
                    now,
                    now,
                    now,
                    collection_id,
                    now,
                ),
            )
            expired = cursor.rowcount == 1
            if expired:
                cursor.execute(
                    """
                    UPDATE learning_collections
                    SET summary_status = 'failed', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, collection_id),
                )
        return expired

    def recover_interrupted_summary_jobs(self) -> Dict[str, int]:
        """Requeue durable jobs and fail legacy processing rows without a job."""
        now = _utcnow().isoformat()
        requeued_jobs = 0
        legacy_failed = 0
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT job_id FROM learning_collection_summary_jobs
                WHERE status = 'running'
                """
            )
            running_job_ids = [
                _row_value(row, "job_id", 0) for row in cursor.fetchall()
            ]
            for job_id in running_job_ids:
                cursor.execute(
                    """
                    UPDATE learning_collection_summary_modules
                    SET status = 'queued', error_message = '', updated_at = ?
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (now, job_id),
                )
                cursor.execute(
                    """
                    UPDATE learning_collection_summary_jobs
                    SET status = 'queued', worker_id = '', lease_until = NULL,
                        progress_message = 'Resuming after service restart', updated_at = ?
                    WHERE job_id = ? AND status = 'running'
                    """,
                    (now, job_id),
                )
                requeued_jobs += cursor.rowcount

            cursor.execute(
                """
                SELECT c.id
                FROM learning_collections c
                LEFT JOIN learning_collection_summary_jobs j
                  ON j.collection_id = c.id
                WHERE c.summary_status = 'processing' AND j.job_id IS NULL
                """
            )
            legacy_collection_ids = [
                _row_value(row, "id", 0) for row in cursor.fetchall()
            ]
            for collection_id in legacy_collection_ids:
                job_id = uuid.uuid4().hex
                error_message = "Summary interrupted by service restart. Please retry."
                cursor.execute(
                    """
                    INSERT INTO learning_collection_summary_jobs (
                        job_id, collection_id, status, phase, progress_message,
                        error_message, completed_at, created_at, updated_at
                    ) VALUES (?, ?, 'failed', 'failed', 'Summary interrupted', ?, ?, ?, ?)
                    """,
                    (job_id, collection_id, error_message, now, now, now),
                )
                cursor.execute(
                    """
                    UPDATE learning_collections
                    SET summary_status = 'failed', updated_at = ? WHERE id = ?
                    """,
                    (now, collection_id),
                )
                legacy_failed += 1
        return {"requeued_jobs": requeued_jobs, "legacy_failed": legacy_failed}

    def mark_summary_processing(self, collection_id: str) -> Dict[str, Any]:
        """Persist in-flight generation so clients can recover after navigation."""
        now = _utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collections
                SET summary_status = 'processing',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, collection_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        return self.get_collection_detail(collection_id)

    def mark_summary_failed(self, collection_id: str, error_message: str = "") -> Dict[str, Any]:
        """Mark generation failed without wiping a previously successful markdown."""
        now = datetime.datetime.utcnow().isoformat()
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                UPDATE learning_collections
                SET summary_status = CASE
                        WHEN summary_markdown IS NOT NULL AND TRIM(summary_markdown) != ''
                        THEN 'success'
                        ELSE 'failed'
                    END,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, collection_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        detail = self.get_collection_detail(collection_id)
        if error_message:
            detail["summary_error"] = error_message
        return detail

    def save_summary(
        self, collection_id: str, markdown: str, description: str = ""
    ) -> Dict[str, Any]:
        now = datetime.datetime.utcnow().isoformat()
        description = (description or "").strip()
        with self._get_cursor(write=True) as cursor:
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
        with self._get_cursor(write=True) as cursor:
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

    def delete_collection(self, collection_id: str) -> Dict[str, Any]:
        """Delete a collection and its sources/maps. Does not delete transcript cache."""
        collection = self.get_collection(collection_id)
        if not collection:
            raise ValueError("collection not found")
        with self._get_cursor(write=True) as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS source_count
                FROM learning_collection_sources
                WHERE collection_id = ?
                """,
                (collection_id,),
            )
            source_count = int(cursor.fetchone()["source_count"] or 0)
            cursor.execute(
                """
                DELETE FROM learning_collection_knowledge_maps
                WHERE collection_id = ?
                """,
                (collection_id,),
            )
            cursor.execute(
                """
                DELETE FROM learning_collection_sources
                WHERE collection_id = ?
                """,
                (collection_id,),
            )
            cursor.execute(
                """
                DELETE FROM learning_collection_summary_modules
                WHERE job_id IN (
                    SELECT job_id FROM learning_collection_summary_jobs
                    WHERE collection_id = ?
                )
                """,
                (collection_id,),
            )
            cursor.execute(
                """
                DELETE FROM learning_collection_summary_jobs
                WHERE collection_id = ?
                """,
                (collection_id,),
            )
            cursor.execute(
                """
                DELETE FROM learning_collections
                WHERE id = ?
                """,
                (collection_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError("collection not found")
        return {
            "id": collection_id,
            "title": collection.get("title") or "",
            "creator_name": collection.get("creator_name") or "",
            "deleted": True,
            "source_count": source_count,
        }

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
        with self._get_cursor(write=True) as cursor:
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
