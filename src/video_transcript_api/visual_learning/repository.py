"""SQLite persistence for generated visual learning documents."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import setup_logger


logger = setup_logger("visual_learning_repository")


class VisualLearningRepository:
    """Persist versioned visual documents and generation state."""

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
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                logger.warning("WAL mode not supported for visual learning repository")
            self._local.connection = connection
        return self._local.connection

    @contextmanager
    def _get_cursor(self):
        if self._is_postgres:
            with self.database.transaction() as connection:
                cursor = connection.cursor()
                try:
                    yield cursor
                finally:
                    cursor.close()
            return
        connection = self._get_connection()
        cursor = connection.cursor()
        try:
            yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _deserialize(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        result.pop("rowid", None)
        raw_document = result.get("document_json")
        if raw_document:
            try:
                result["document_json"] = json.loads(raw_document)
            except (TypeError, json.JSONDecodeError):
                result["document_json"] = None
        else:
            result["document_json"] = None
        raw_progress = result.get("progress_json")
        if raw_progress:
            try:
                result["progress_json"] = json.loads(raw_progress)
            except (TypeError, json.JSONDecodeError):
                result["progress_json"] = None
        else:
            result["progress_json"] = None
        return result

    def close(self) -> None:
        if self._is_postgres:
            return
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            del self._local.connection

    def _init_database(self) -> None:
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_documents (
                    id TEXT PRIMARY KEY,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_key TEXT NOT NULL UNIQUE,
                    source_hash TEXT NOT NULL,
                    style TEXT NOT NULL,
                    document_json TEXT,
                    model TEXT,
                    error_message TEXT,
                    progress_json TEXT,
                    generation_token TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute("PRAGMA table_info(visual_documents)")
            columns = {row[1] for row in cursor.fetchall()}
            if "progress_json" not in columns:
                cursor.execute("ALTER TABLE visual_documents ADD COLUMN progress_json TEXT")
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_visual_documents_owner
                ON visual_documents(owner_type, owner_id, document_type, updated_at)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_visual_documents_status
                ON visual_documents(status, updated_at)
                """
            )

    def create_or_get_pending(
        self,
        *,
        owner_type: str,
        owner_id: str,
        document_type: str,
        request_key: str,
        source_hash: str,
        style: str,
        force: bool = False,
    ) -> dict[str, Any]:
        effective_key = request_key
        if force:
            effective_key = f"{request_key}:{uuid.uuid4().hex}"
        document_id = uuid.uuid4().hex
        now = self._now()
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT OR IGNORE INTO visual_documents (
                    id, owner_type, owner_id, document_type, status,
                    request_key, source_hash, style, generation_token,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, '', ?, ?)
                """,
                (
                    document_id,
                    owner_type,
                    owner_id,
                    document_type,
                    effective_key,
                    source_hash,
                    style,
                    now,
                    now,
                ),
            )
            cursor.execute(
                "SELECT * FROM visual_documents WHERE request_key = ?",
                (effective_key,),
            )
            row = cursor.fetchone()
        return self._deserialize(row) or {}

    def claim_generation(
        self,
        document_id: str,
        previous_token: str = "",
    ) -> Optional[str]:
        token = uuid.uuid4().hex
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE visual_documents
                SET status = 'generating', generation_token = ?,
                    error_message = NULL, updated_at = ?
                WHERE id = ?
                  AND status IN ('pending', 'failed')
                  AND generation_token = ?
                """,
                (token, self._now(), document_id, previous_token),
            )
            claimed = cursor.rowcount == 1
        return token if claimed else None

    def save_success(
        self,
        document_id: str,
        generation_token: str,
        document_json: dict[str, Any],
        model: str,
    ) -> bool:
        now = self._now()
        progress = {
            "stage": "completed",
            "stage_label": "图解已生成",
            "percent": 100,
            "updated_at": now,
        }
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE visual_documents
                SET status = 'success', document_json = ?, model = ?,
                    error_message = NULL, progress_json = ?, updated_at = ?
                WHERE id = ? AND generation_token = ? AND status = 'generating'
                """,
                (
                    json.dumps(document_json, ensure_ascii=False, separators=(",", ":")),
                    model,
                    json.dumps(progress, ensure_ascii=False, separators=(",", ":")),
                    now,
                    document_id,
                    generation_token,
                ),
            )
            return cursor.rowcount == 1

    def save_failure(
        self,
        document_id: str,
        generation_token: str,
        error_message: str,
    ) -> bool:
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT progress_json FROM visual_documents WHERE id = ? AND generation_token = ?",
                (document_id, generation_token),
            )
            row = cursor.fetchone()
            previous = {}
            if row and row["progress_json"]:
                try:
                    previous = json.loads(row["progress_json"])
                except (TypeError, json.JSONDecodeError):
                    previous = {}
            now = self._now()
            progress = {
                "stage": "failed",
                "stage_label": "图解生成失败",
                "percent": previous.get("percent"),
                "previous_stage": previous.get("stage"),
                "updated_at": now,
            }
            cursor.execute(
                """
                UPDATE visual_documents
                SET status = 'failed', error_message = ?, progress_json = ?, updated_at = ?
                WHERE id = ? AND generation_token = ? AND status = 'generating'
                """,
                (
                    error_message[:1000],
                    json.dumps(progress, ensure_ascii=False, separators=(",", ":")),
                    now,
                    document_id,
                    generation_token,
                ),
            )
            return cursor.rowcount == 1

    def update_progress(
        self,
        document_id: str,
        generation_token: str,
        progress: dict[str, Any],
    ) -> bool:
        payload = dict(progress)
        payload.setdefault("updated_at", self._now())
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE visual_documents
                SET progress_json = ?, updated_at = ?
                WHERE id = ? AND generation_token = ? AND status = 'generating'
                """,
                (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    payload["updated_at"],
                    document_id,
                    generation_token,
                ),
            )
            return cursor.rowcount == 1

    def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM visual_documents WHERE id = ?",
                (document_id,),
            )
            row = cursor.fetchone()
        return self._deserialize(row)

    def get_latest(
        self,
        owner_type: str,
        owner_id: str,
        document_type: str,
        successful_only: bool = False,
    ) -> Optional[dict[str, Any]]:
        status_clause = "AND status = 'success'" if successful_only else ""
        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM visual_documents
                WHERE owner_type = ? AND owner_id = ? AND document_type = ?
                {status_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (owner_type, owner_id, document_type),
            )
            row = cursor.fetchone()
        return self._deserialize(row)

    def list_documents(
        self,
        owner_type: str,
        owner_id: str,
        document_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        conditions = ["owner_type = ?", "owner_id = ?"]
        parameters: list[Any] = [owner_type, owner_id]
        if document_type:
            conditions.append("document_type = ?")
            parameters.append(document_type)
        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM visual_documents
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC, id DESC
                """,
                parameters,
            )
            rows = cursor.fetchall()
        return [self._deserialize(row) or {} for row in rows]

    def list_recent(
        self,
        document_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conditions = ["status = 'success'"]
        parameters: list[Any] = []
        if document_type:
            conditions.append("document_type = ?")
            parameters.append(document_type)
        parameters.append(max(1, min(limit, 100)))
        with self._get_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM visual_documents
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                parameters,
            )
            rows = cursor.fetchall()
        return [self._deserialize(row) or {} for row in rows]

    def recover_stale_generations(self, max_age_minutes: int = 20) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE visual_documents
                SET status = 'failed', generation_token = '',
                    error_message = 'generation timed out', updated_at = ?
                WHERE status = 'generating' AND updated_at < ?
                """,
                (self._now(), cutoff.isoformat(timespec="microseconds")),
            )
            return cursor.rowcount
