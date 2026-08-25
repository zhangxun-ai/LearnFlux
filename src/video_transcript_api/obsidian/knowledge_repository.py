"""SQLite persistence isolated from legacy Study Obsidian tables."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..study.repository import build_study_context_key


class KnowledgeRevisionConflict(Exception):
    """Raised when an optimistic knowledge binding revision is stale."""


class ObsidianKnowledgeRepository:
    def __init__(self, db_path: str | Path | object):
        self.database = db_path if hasattr(db_path, "connect") else None
        raw_path = getattr(db_path, "path", None) if self.database else db_path
        self.db_path = str(raw_path) if raw_path else None
        self._initialize()

    @contextmanager
    def _connection(self):
        if self.database is not None:
            connection = self.database.connect()
        else:
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        if self.db_path:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS obsidian_knowledge_bindings (
                    id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL, vault_id TEXT NOT NULL, category TEXT NOT NULL,
                    collection_directory TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP, updated_at TIMESTAMP,
                    UNIQUE(owner_user_id, scope_type, scope_id, vault_id)
                );
                CREATE TABLE IF NOT EXISTS obsidian_knowledge_sync (
                    id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, context_key TEXT NOT NULL,
                    current_view_token TEXT NOT NULL, collection_id TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '', raw_relative_path TEXT, raw_synced_hash TEXT,
                    analysis_relative_path TEXT, analysis_synced_hash TEXT, synced_at TIMESTAMP,
                    UNIQUE(owner_user_id, context_key)
                );
            """)
            self._migrate_legacy_sync_uniqueness(conn)

    @staticmethod
    def _migrate_legacy_sync_uniqueness(conn: sqlite3.Connection) -> None:
        """Replace the short-lived global context_key uniqueness with owner scope."""
        indexes = conn.execute("PRAGMA index_list(obsidian_knowledge_sync)").fetchall()
        has_owner_context = False
        has_context_only = False
        for index in indexes:
            if not index[2]:
                continue
            columns = [
                row[2]
                for row in conn.execute(
                    f'PRAGMA index_info("{index[1]}")'
                ).fetchall()
            ]
            has_owner_context = has_owner_context or columns == [
                "owner_user_id",
                "context_key",
            ]
            has_context_only = has_context_only or columns == ["context_key"]
        if has_owner_context or not has_context_only:
            return
        conn.executescript("""
            CREATE TABLE obsidian_knowledge_sync_v2 (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                context_key TEXT NOT NULL,
                current_view_token TEXT NOT NULL,
                collection_id TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                raw_relative_path TEXT,
                raw_synced_hash TEXT,
                analysis_relative_path TEXT,
                analysis_synced_hash TEXT,
                synced_at TIMESTAMP,
                UNIQUE(owner_user_id, context_key)
            );
            INSERT INTO obsidian_knowledge_sync_v2
            SELECT * FROM obsidian_knowledge_sync;
            DROP TABLE obsidian_knowledge_sync;
            ALTER TABLE obsidian_knowledge_sync_v2
            RENAME TO obsidian_knowledge_sync;
        """)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get_binding(self, owner_user_id: str, scope_type: str, scope_id: str, vault_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return self._row(conn.execute(
                "SELECT * FROM obsidian_knowledge_bindings WHERE owner_user_id=? AND scope_type=? AND scope_id=? AND vault_id=?",
                (owner_user_id, scope_type, scope_id, vault_id),
            ).fetchone())

    def save_binding(self, owner_user_id: str, scope_type: str, scope_id: str, vault_id: str, category: str, collection_directory: str = "", expected_revision: int | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM obsidian_knowledge_bindings WHERE owner_user_id=? AND scope_type=? AND scope_id=? AND vault_id=?",
                (owner_user_id, scope_type, scope_id, vault_id),
            ).fetchone()
            if existing is None:
                if expected_revision is not None:
                    raise KnowledgeRevisionConflict("binding_missing")
                binding_id, revision = str(uuid.uuid4()), 1
                conn.execute("INSERT INTO obsidian_knowledge_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (binding_id, owner_user_id, scope_type, scope_id, vault_id, category, collection_directory, revision, now, now))
            else:
                if expected_revision != existing["revision"]:
                    raise KnowledgeRevisionConflict("binding_revision_conflict")
                binding_id, revision = existing["id"], existing["revision"] + 1
                changed = (category, collection_directory) != (existing["category"], existing["collection_directory"])
                conn.execute("UPDATE obsidian_knowledge_bindings SET category=?, collection_directory=?, revision=?, updated_at=? WHERE id=?",
                    (category, collection_directory, revision, now, binding_id))
                if changed:
                    if scope_type == "single":
                        conn.execute(
                            "DELETE FROM obsidian_knowledge_sync "
                            "WHERE owner_user_id=? AND context_key=?",
                            (owner_user_id, build_study_context_key(scope_id)),
                        )
                    else:
                        conn.execute("DELETE FROM obsidian_knowledge_sync WHERE owner_user_id=? AND collection_id=?", (owner_user_id, scope_id))
            row = conn.execute(
                "SELECT * FROM obsidian_knowledge_bindings WHERE id=?", (binding_id,)
            ).fetchone()
            return self._row(row) or {}

    def get_sync_state(self, owner_user_id: str, context_key: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return self._row(conn.execute("SELECT * FROM obsidian_knowledge_sync WHERE owner_user_id=? AND context_key=?", (owner_user_id, context_key)).fetchone())

    def update_sync_state(self, owner_user_id: str, context_key: str, current_view_token: str, collection_id: str = "", source_id: str = "", **values: str | None) -> dict[str, Any]:
        allowed = {"raw_relative_path", "raw_synced_hash", "analysis_relative_path", "analysis_synced_hash"}
        updates = {key: value for key, value in values.items() if key in allowed}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connection() as conn:
            prior_row = conn.execute(
                "SELECT * FROM obsidian_knowledge_sync WHERE owner_user_id=? AND context_key=?",
                (owner_user_id, context_key),
            ).fetchone()
            prior = self._row(prior_row) or {}
            data = {key: updates.get(key, prior.get(key)) for key in allowed}
            conn.execute("""INSERT INTO obsidian_knowledge_sync
                (id, owner_user_id, context_key, current_view_token, collection_id, source_id, raw_relative_path, raw_synced_hash, analysis_relative_path, analysis_synced_hash, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, context_key) DO UPDATE SET current_view_token=excluded.current_view_token, collection_id=excluded.collection_id, source_id=excluded.source_id, raw_relative_path=excluded.raw_relative_path, raw_synced_hash=excluded.raw_synced_hash, analysis_relative_path=excluded.analysis_relative_path, analysis_synced_hash=excluded.analysis_synced_hash, synced_at=excluded.synced_at""",
                (prior.get("id", str(uuid.uuid4())), owner_user_id, context_key, current_view_token, collection_id, source_id, data["raw_relative_path"], data["raw_synced_hash"], data["analysis_relative_path"], data["analysis_synced_hash"], now))
            row = conn.execute("SELECT * FROM obsidian_knowledge_sync WHERE owner_user_id=? AND context_key=?", (owner_user_id, context_key)).fetchone()
            return self._row(row) or {}
