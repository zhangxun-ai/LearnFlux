import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import setup_logger

logger = setup_logger("study_repository")


def _utf8_length(value: str) -> int:
    return len(value.encode("utf-8"))


def build_study_context_key(
    view_token: str,
    collection_id: str = "",
    source_id: str = "",
) -> str:
    """Build the stable server-side identity for one Study note document."""
    if bool(collection_id) != bool(source_id):
        raise ValueError("collection_id and source_id must be provided together")
    if collection_id and source_id:
        return (
            f"collection|{_utf8_length(collection_id)}|{collection_id}"
            f"|{_utf8_length(source_id)}|{source_id}"
        )
    return f"single|{_utf8_length(view_token)}|{view_token}"


class StudyRevisionConflict(Exception):
    """Raised when an optimistic Study write uses a stale revision."""

    def __init__(self, current: Optional[dict[str, Any]]):
        super().__init__("study revision conflict")
        self.current = current


class StudyRepository:
    """SQLite repository for context-isolated Study notes."""

    def __init__(self, db_path: str | object):
        self.database = db_path if hasattr(db_path, "transaction") else None
        self._is_postgres = getattr(self.database, "dialect", None) == "postgres"
        raw_path = getattr(db_path, "path", None) if self.database else db_path
        self.db_path = Path(raw_path) if raw_path else None
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_postgres:
            raise RuntimeError("postgres_connections_must_be_scoped")
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
        if self._is_postgres:
            with self.database.transaction() as conn:
                cursor = conn.cursor()
                try:
                    yield cursor
                finally:
                    cursor.close()
            return
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
        if self._is_postgres:
            return
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS study_note_documents (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    context_key TEXT NOT NULL,
                    current_view_token TEXT NOT NULL,
                    collection_id TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_user_id, context_key)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS obsidian_bindings (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    vault_id TEXT NOT NULL,
                    transcript_directory TEXT NOT NULL,
                    note_directory TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_user_id, scope_type, scope_id, vault_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS obsidian_source_sync (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    context_key TEXT NOT NULL,
                    current_view_token TEXT NOT NULL,
                    collection_id TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    transcript_relative_path TEXT,
                    transcript_synced_hash TEXT,
                    note_relative_path TEXT,
                    note_body_synced_hash TEXT,
                    note_managed_hash TEXT,
                    synced_at TIMESTAMP,
                    UNIQUE(owner_user_id, context_key)
                )
                """
            )

    @staticmethod
    def _fetch_context_row(
        cursor: sqlite3.Cursor,
        table: str,
        owner_user_id: str,
        context_key: str,
    ) -> Optional[dict[str, Any]]:
        cursor.execute(
            f"SELECT * FROM {table} WHERE owner_user_id = ? AND context_key = ?",
            (owner_user_id, context_key),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_or_create_note_document(
        self,
        *,
        owner_user_id: str,
        view_token: str,
        collection_id: str = "",
        source_id: str = "",
        claim_unowned_single_legacy: bool = False,
    ) -> dict[str, Any]:
        """Return one stable note document, migrating legacy note rows once."""
        context_key = build_study_context_key(view_token, collection_id, source_id)
        with self._get_cursor() as cursor:
            current = self._fetch_context_row(
                cursor, "study_note_documents", owner_user_id, context_key
            )
            if current:
                if current["current_view_token"] != view_token:
                    cursor.execute(
                        """
                        UPDATE study_note_documents
                        SET current_view_token = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE owner_user_id = ? AND context_key = ?
                        """,
                        (view_token, owner_user_id, context_key),
                    )
                    current["current_view_token"] = view_token
                return current

            if collection_id and source_id:
                cursor.execute(
                    """
                    SELECT body FROM study_notes
                    WHERE view_token = ? AND owner_user_id = ?
                      AND COALESCE(collection_id, '') = ?
                      AND COALESCE(source_id, '') = ?
                    ORDER BY COALESCE(time_seconds, 999999999), created_at
                    """,
                    (view_token, owner_user_id, collection_id, source_id),
                )
            elif claim_unowned_single_legacy:
                cursor.execute(
                    """
                    SELECT body FROM study_notes
                    WHERE view_token = ?
                      AND (owner_user_id = ? OR owner_user_id = '' OR owner_user_id IS NULL)
                      AND COALESCE(collection_id, '') = ''
                      AND COALESCE(source_id, '') = ''
                    ORDER BY COALESCE(time_seconds, 999999999), created_at
                    """,
                    (view_token, owner_user_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT body FROM study_notes
                    WHERE view_token = ? AND owner_user_id = ?
                      AND COALESCE(collection_id, '') = ''
                      AND COALESCE(source_id, '') = ''
                    ORDER BY COALESCE(time_seconds, 999999999), created_at
                    """,
                    (view_token, owner_user_id),
                )
            bodies = [
                str(row["body"]).strip()
                for row in cursor.fetchall()
                if str(row["body"] or "").strip()
            ]
            document_id = uuid.uuid4().hex
            cursor.execute(
                """
                INSERT INTO study_note_documents (
                    id, owner_user_id, context_key, current_view_token,
                    collection_id, source_id, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    owner_user_id,
                    context_key,
                    view_token,
                    collection_id,
                    source_id,
                    "\n\n".join(bodies),
                ),
            )
            return self._fetch_context_row(
                cursor, "study_note_documents", owner_user_id, context_key
            ) or {}

    def update_note_document(
        self,
        *,
        owner_user_id: str,
        view_token: str,
        body: str,
        expected_revision: int,
        collection_id: str = "",
        source_id: str = "",
    ) -> dict[str, Any]:
        context_key = build_study_context_key(view_token, collection_id, source_id)
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE study_note_documents
                SET body = ?, current_view_token = ?, revision = revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE owner_user_id = ? AND context_key = ? AND revision = ?
                """,
                (body or "", view_token, owner_user_id, context_key, expected_revision),
            )
            if cursor.rowcount == 0:
                current = self._fetch_context_row(
                    cursor, "study_note_documents", owner_user_id, context_key
                )
                raise StudyRevisionConflict(current)
            return self._fetch_context_row(
                cursor, "study_note_documents", owner_user_id, context_key
            ) or {}

    def get_obsidian_binding(
        self,
        *,
        owner_user_id: str,
        scope_type: str,
        scope_id: str,
        vault_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM obsidian_bindings
                WHERE owner_user_id = ? AND scope_type = ?
                  AND scope_id = ? AND vault_id = ?
                """,
                (owner_user_id, scope_type, scope_id, vault_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def save_obsidian_binding(
        self,
        *,
        owner_user_id: str,
        scope_type: str,
        scope_id: str,
        vault_id: str,
        transcript_directory: str,
        note_directory: str,
        expected_revision: Optional[int],
    ) -> dict[str, Any]:
        if scope_type not in {"collection", "single"}:
            raise ValueError("scope_type must be collection or single")
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM obsidian_bindings
                WHERE owner_user_id = ? AND scope_type = ?
                  AND scope_id = ? AND vault_id = ?
                """,
                (owner_user_id, scope_type, scope_id, vault_id),
            )
            row = cursor.fetchone()
            current = dict(row) if row else None
            if current is None:
                if expected_revision not in {None, 0}:
                    raise StudyRevisionConflict(None)
                cursor.execute(
                    """
                    INSERT INTO obsidian_bindings (
                        id, owner_user_id, scope_type, scope_id, vault_id,
                        transcript_directory, note_directory
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        owner_user_id,
                        scope_type,
                        scope_id,
                        vault_id,
                        transcript_directory,
                        note_directory,
                    ),
                )
            else:
                if expected_revision != current["revision"]:
                    raise StudyRevisionConflict(current)
                directories_changed = (
                    current["transcript_directory"] != transcript_directory
                    or current["note_directory"] != note_directory
                )
                cursor.execute(
                    """
                    UPDATE obsidian_bindings
                    SET transcript_directory = ?, note_directory = ?,
                        revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (transcript_directory, note_directory, current["id"]),
                )
                if directories_changed:
                    self._reset_sync_state_for_binding(
                        cursor,
                        owner_user_id=owner_user_id,
                        scope_type=scope_type,
                        scope_id=scope_id,
                    )
            cursor.execute(
                """
                SELECT * FROM obsidian_bindings
                WHERE owner_user_id = ? AND scope_type = ?
                  AND scope_id = ? AND vault_id = ?
                """,
                (owner_user_id, scope_type, scope_id, vault_id),
            )
            return dict(cursor.fetchone())

    @staticmethod
    def _reset_sync_state_for_binding(
        cursor: sqlite3.Cursor,
        *,
        owner_user_id: str,
        scope_type: str,
        scope_id: str,
    ) -> None:
        values = (
            "transcript_relative_path = NULL, transcript_synced_hash = NULL, "
            "note_relative_path = NULL, note_body_synced_hash = NULL, "
            "note_managed_hash = NULL, synced_at = NULL"
        )
        if scope_type == "collection":
            cursor.execute(
                f"""
                UPDATE obsidian_source_sync SET {values}
                WHERE owner_user_id = ? AND collection_id = ?
                """,
                (owner_user_id, scope_id),
            )
        else:
            context_key = build_study_context_key(scope_id)
            cursor.execute(
                f"""
                UPDATE obsidian_source_sync SET {values}
                WHERE owner_user_id = ? AND context_key = ?
                  AND collection_id = '' AND source_id = ''
                """,
                (owner_user_id, context_key),
            )

    def get_obsidian_source_sync(
        self,
        *,
        owner_user_id: str,
        view_token: str,
        collection_id: str = "",
        source_id: str = "",
    ) -> Optional[dict[str, Any]]:
        context_key = build_study_context_key(view_token, collection_id, source_id)
        with self._get_cursor() as cursor:
            return self._fetch_context_row(
                cursor, "obsidian_source_sync", owner_user_id, context_key
            )

    def update_obsidian_source_sync(
        self,
        *,
        owner_user_id: str,
        view_token: str,
        collection_id: str = "",
        source_id: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        allowed = {
            "transcript_relative_path",
            "transcript_synced_hash",
            "note_relative_path",
            "note_body_synced_hash",
            "note_managed_hash",
            "synced_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported sync fields: {', '.join(sorted(unknown))}")
        context_key = build_study_context_key(view_token, collection_id, source_id)
        with self._get_cursor() as cursor:
            current = self._fetch_context_row(
                cursor, "obsidian_source_sync", owner_user_id, context_key
            )
            if current is None:
                values = {key: fields.get(key) for key in allowed}
                cursor.execute(
                    """
                    INSERT INTO obsidian_source_sync (
                        id, owner_user_id, context_key, current_view_token,
                        collection_id, source_id, transcript_relative_path,
                        transcript_synced_hash, note_relative_path,
                        note_body_synced_hash, note_managed_hash, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        owner_user_id,
                        context_key,
                        view_token,
                        collection_id,
                        source_id,
                        values["transcript_relative_path"],
                        values["transcript_synced_hash"],
                        values["note_relative_path"],
                        values["note_body_synced_hash"],
                        values["note_managed_hash"],
                        values["synced_at"],
                    ),
                )
            else:
                assignments = ["current_view_token = ?"]
                parameters: list[Any] = [view_token]
                for key, value in fields.items():
                    assignments.append(f"{key} = ?")
                    parameters.append(value)
                parameters.append(current["id"])
                cursor.execute(
                    f"UPDATE obsidian_source_sync SET {', '.join(assignments)} WHERE id = ?",
                    parameters,
                )
            return self._fetch_context_row(
                cursor, "obsidian_source_sync", owner_user_id, context_key
            ) or {}

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
