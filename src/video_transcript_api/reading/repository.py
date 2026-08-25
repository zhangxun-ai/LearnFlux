"""Owner-scoped SQLite repository for reading data."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import IntegrityError as PostgresIntegrityError

from .schemas import (
    FocusMaterial,
    ReadingAnnotation,
    ReadingChapter,
    ReadingDocument,
    ReadingLocator,
    ReadingPreferences,
    ReadingProgress,
    ReadingPageAnalysis,
    ReadingParseRun,
    ReadingRangeLocator,
    VALID_ANNOTATION_KINDS,
    VALID_READING_STATUSES,
)

_MAX_LOCATOR_JSON_BYTES = 65_536


class ReadingDataError(ValueError):
    """Stored reading data cannot be interpreted safely."""


class ReadingRepository:
    """Persist owner-isolated reading state without web framework dependencies."""

    def __init__(self, db_path: str | Path | object) -> None:
        if hasattr(db_path, "connect") and hasattr(db_path, "transaction"):
            self.database = db_path
            self.db_path = None
            self._connection = db_path.connect()
        else:
            self.database = None
            self.db_path = Path(db_path)
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS reading_documents (
                id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, title TEXT NOT NULL,
                author TEXT, format TEXT NOT NULL, source_path TEXT NOT NULL,
                file_sha256 TEXT NOT NULL, file_size INTEGER NOT NULL, status TEXT NOT NULL,
                parse_error TEXT, cover_path TEXT, outline_json TEXT, parse_generation INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_opened_at TEXT,
                UNIQUE(owner_user_id, file_sha256)
            );
            CREATE TABLE IF NOT EXISTS reading_chapters (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, position INTEGER NOT NULL,
                parent_id TEXT, title TEXT NOT NULL, source_locator_json TEXT NOT NULL,
                plain_text TEXT NOT NULL, sanitized_html TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES reading_documents(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_id) REFERENCES reading_chapters(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reading_chapters_document_position
                ON reading_chapters(document_id, position);
            CREATE TABLE IF NOT EXISTS reading_parse_runs (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, generation INTEGER NOT NULL,
                parent_run_id TEXT, parser_version TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(document_id, generation),
                FOREIGN KEY(document_id) REFERENCES reading_documents(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_run_id) REFERENCES reading_parse_runs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reading_parse_runs_document_generation
                ON reading_parse_runs(document_id, generation DESC);
            CREATE TABLE IF NOT EXISTS reading_page_analyses (
                id TEXT PRIMARY KEY, creating_run_id TEXT NOT NULL,
                source_page INTEGER NOT NULL, retry_profile TEXT NOT NULL,
                extraction_mode TEXT NOT NULL, quality_status TEXT NOT NULL,
                quality_score REAL NOT NULL, issue_codes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(creating_run_id) REFERENCES reading_parse_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reading_page_analyses_run_page
                ON reading_page_analyses(creating_run_id, source_page);
            CREATE TABLE IF NOT EXISTS reading_run_pages (
                run_id TEXT NOT NULL, source_page INTEGER NOT NULL,
                analysis_id TEXT NOT NULL,
                PRIMARY KEY(run_id, source_page),
                FOREIGN KEY(run_id) REFERENCES reading_parse_runs(id) ON DELETE CASCADE,
                FOREIGN KEY(analysis_id) REFERENCES reading_page_analyses(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS reading_page_blocks (
                analysis_id TEXT NOT NULL, block_index INTEGER NOT NULL,
                text TEXT NOT NULL, bbox_json TEXT, confidence REAL,
                kind TEXT NOT NULL, reading_order INTEGER NOT NULL,
                PRIMARY KEY(analysis_id, block_index),
                FOREIGN KEY(analysis_id) REFERENCES reading_page_analyses(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reading_page_blocks_analysis_order
                ON reading_page_blocks(analysis_id, reading_order);
            CREATE TABLE IF NOT EXISTS reading_locator_resolutions (
                id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL,
                document_id TEXT NOT NULL, target_run_id TEXT NOT NULL,
                target_type TEXT NOT NULL, old_locator_json TEXT NOT NULL,
                resolved_locator_json TEXT, status TEXT NOT NULL,
                reason TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES reading_documents(id) ON DELETE CASCADE,
                FOREIGN KEY(target_run_id) REFERENCES reading_parse_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reading_locator_resolutions_document_run
                ON reading_locator_resolutions(document_id, target_run_id, created_at);
            CREATE TABLE IF NOT EXISTS reading_progress (
                owner_user_id TEXT NOT NULL, document_id TEXT NOT NULL, mode TEXT NOT NULL,
                locator_json TEXT NOT NULL, percent REAL NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(owner_user_id, document_id),
                FOREIGN KEY(document_id) REFERENCES reading_documents(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS reading_preferences (
                owner_user_id TEXT PRIMARY KEY, theme TEXT NOT NULL, font_family TEXT NOT NULL,
                font_size INTEGER NOT NULL, layout TEXT NOT NULL, sound_track TEXT NOT NULL,
                sound_volume REAL NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reading_annotations (
                id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, document_id TEXT NOT NULL,
                kind TEXT NOT NULL, locator_json TEXT NOT NULL, quote TEXT NOT NULL,
                note_body TEXT, color TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES reading_documents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reading_annotations_owner_document_updated
                ON reading_annotations(owner_user_id, document_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS focus_materials (
                id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, source_type TEXT NOT NULL,
                source_id TEXT, source_title TEXT NOT NULL, quote TEXT NOT NULL, note TEXT,
                locator_json TEXT, consumed_at TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_focus_materials_owner_consumed_created
                ON focus_materials(owner_user_id, consumed_at, created_at DESC);
            CREATE TABLE IF NOT EXISTS reading_deletion_jobs (
                id TEXT PRIMARY KEY, source_path TEXT NOT NULL,
                asset_dir TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reading_schema_migrations (
                version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
            );
            """
        )
        migration = self._connection.execute(
            "SELECT 1 FROM reading_schema_migrations WHERE version = 1"
        ).fetchone()
        if migration is None:
            self._ensure_column(
                "reading_documents", "active_parse_run_id", "TEXT"
            )
            self._ensure_column(
                "reading_documents",
                "parse_quality",
                "TEXT NOT NULL DEFAULT 'good'",
            )
            self._ensure_column(
                "reading_documents",
                "parse_warning_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column("reading_chapters", "parse_run_id", "TEXT")
            self._connection.execute(
                "INSERT INTO reading_schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, self._now()),
            )
        self._connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_reading_chapters_document_run_position
               ON reading_chapters(document_id, parse_run_id, position)"""
        )
        self._connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @staticmethod
    def _now() -> str:
        """Return a portable ISO timestamp for the repository's TEXT columns."""

        return datetime.now(UTC).isoformat(timespec="microseconds")

    @staticmethod
    def _id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _validate_status(status: object) -> None:
        if not isinstance(status, str) or status not in VALID_READING_STATUSES:
            raise ReadingDataError("invalid reading status")

    @staticmethod
    def _validate_parse_run_status(status: object) -> None:
        if status not in {"running", "completed", "failed", "cancelled"}:
            raise ReadingDataError("invalid parse run status")

    @staticmethod
    def _validate_parse_quality(status: object) -> None:
        if status not in {"good", "warning", "attention"}:
            raise ReadingDataError("invalid parse quality")

    @staticmethod
    def _validate_annotation_kind(kind: object) -> None:
        if not isinstance(kind, str) or kind not in VALID_ANNOTATION_KINDS:
            raise ReadingDataError("invalid annotation kind")

    def _validate_parent_chapter(
        self, owner_user_id: str, document_id: str, parent_id: str | None
    ) -> None:
        if parent_id is None:
            return
        parent = self._fetchone(
            """SELECT c.id FROM reading_chapters c
               JOIN reading_documents d ON d.id = c.document_id
               WHERE c.id = ? AND c.document_id = ? AND d.owner_user_id = ?""",
            (parent_id, document_id, owner_user_id),
        )
        if parent is None:
            raise ReadingDataError("invalid parent chapter")

    @staticmethod
    def _encode_locator(locator: ReadingLocator | ReadingRangeLocator) -> str:
        encoded = locator.model_dump_json()
        if len(encoded.encode("utf-8")) > _MAX_LOCATOR_JSON_BYTES:
            raise ValueError("locator JSON is too large")
        return encoded

    @staticmethod
    def _decode_locator(raw: str, schema: type[ReadingLocator] | type[ReadingRangeLocator]):
        try:
            if len(raw.encode("utf-8")) > _MAX_LOCATOR_JSON_BYTES:
                raise ValueError
            return schema.model_validate_json(raw)
        except (AttributeError, UnicodeError, ValueError):
            pass
        raise ReadingDataError("invalid locator JSON")

    @staticmethod
    def _as_model(schema: type[Any], row: sqlite3.Row, locators: dict[str, type[Any]] | None = None):
        values = dict(row)
        for field, locator_schema in (locators or {}).items():
            raw_locator = values.pop(f"{field}_json")
            values[field] = (
                ReadingRepository._decode_locator(raw_locator, locator_schema)
                if raw_locator is not None
                else None
            )
        try:
            return schema.model_validate(values)
        except Exception:
            pass
        raise ReadingDataError("invalid stored reading data") from None

    def _fetchone(self, query: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        return self._connection.execute(query, params).fetchone()

    def create_document(self, *, owner_user_id: str, title: str, author: str | None,
                        format: str, source_path: str, file_sha256: str, file_size: int,
                        status: str, parse_error: str | None = None, cover_path: str | None = None,
                        outline_json: str | None = None) -> ReadingDocument:
        self._validate_status(status)
        now = self._now()
        document_id = self._id()
        self._connection.execute(
            """INSERT INTO reading_documents (id, owner_user_id, title, author, format, source_path,
               file_sha256, file_size, status, parse_error, cover_path, outline_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, owner_user_id, title, author, format, source_path, file_sha256, file_size,
             status, parse_error, cover_path, outline_json, now, now),
        )
        self._connection.commit()
        return self.get_document(owner_user_id, document_id)  # type: ignore[return-value]

    def get_document(self, owner_user_id: str, document_id: str) -> ReadingDocument | None:
        row = self._fetchone("SELECT * FROM reading_documents WHERE owner_user_id = ? AND id = ?", (owner_user_id, document_id))
        return self._as_model(ReadingDocument, row) if row else None

    def list_documents(self, owner_user_id: str) -> list[ReadingDocument]:
        rows = self._connection.execute("SELECT * FROM reading_documents WHERE owner_user_id = ? ORDER BY updated_at DESC", (owner_user_id,)).fetchall()
        return [self._as_model(ReadingDocument, row) for row in rows]

    def create_parse_run(
        self,
        owner_user_id: str,
        document_id: str,
        *,
        parser_version: str,
        status: str = "running",
        parent_run_id: str | None = None,
    ) -> ReadingParseRun:
        self._validate_parse_run_status(status)
        if self.get_document(owner_user_id, document_id) is None:
            raise ReadingDataError("document not found")
        if parent_run_id is not None:
            parent = self._fetchone(
                """SELECT r.id FROM reading_parse_runs r
                   JOIN reading_documents d ON d.id = r.document_id
                   WHERE r.id = ? AND r.document_id = ? AND d.owner_user_id = ?""",
                (parent_run_id, document_id, owner_user_id),
            )
            if parent is None:
                raise ReadingDataError("invalid parent parse run")
        now = self._now()
        run_id = self._id()
        with self._connection:
            if status == "running":
                active = self._connection.execute(
                    """SELECT 1 FROM reading_parse_runs
                       WHERE document_id = ? AND status = 'running' LIMIT 1""",
                    (document_id,),
                ).fetchone()
                if active is not None:
                    raise ReadingDataError("parse run already active")
            generation = self._connection.execute(
                "SELECT COALESCE(MAX(generation), 0) + 1 FROM reading_parse_runs WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
            self._connection.execute(
                """INSERT INTO reading_parse_runs
                   (id, document_id, generation, parent_run_id, parser_version, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    document_id,
                    generation,
                    parent_run_id,
                    parser_version,
                    status,
                    now,
                    now,
                ),
            )
        return self.get_parse_run(owner_user_id, run_id)  # type: ignore[return-value]

    def record_page_analysis(
        self,
        owner_user_id: str,
        run_id: str,
        *,
        source_page: int,
        retry_profile: str,
        extraction_mode: str,
        quality_status: str,
        quality_score: float,
        issue_codes: list[str],
    ) -> ReadingPageAnalysis:
        self._validate_parse_quality(quality_status)
        if source_page < 0 or not 0 <= quality_score <= 1:
            raise ReadingDataError("invalid page analysis")
        if self.get_parse_run(owner_user_id, run_id) is None:
            raise ReadingDataError("parse run not found")
        analysis_id = self._id()
        now = self._now()
        self._connection.execute(
            """INSERT INTO reading_page_analyses
               (id, creating_run_id, source_page, retry_profile, extraction_mode,
                quality_status, quality_score, issue_codes_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analysis_id,
                run_id,
                source_page,
                retry_profile,
                extraction_mode,
                quality_status,
                quality_score,
                json.dumps(issue_codes),
                now,
            ),
        )
        self._connection.commit()
        return self.get_page_analysis(owner_user_id, analysis_id)  # type: ignore[return-value]

    def get_page_analysis(
        self, owner_user_id: str, analysis_id: str
    ) -> ReadingPageAnalysis | None:
        row = self._fetchone(
            """SELECT a.* FROM reading_page_analyses a
               JOIN reading_parse_runs r ON r.id = a.creating_run_id
               JOIN reading_documents d ON d.id = r.document_id
               WHERE a.id = ? AND d.owner_user_id = ?""",
            (analysis_id, owner_user_id),
        )
        return self._as_model(ReadingPageAnalysis, row) if row else None

    def snapshot_run_page(
        self, owner_user_id: str, run_id: str, source_page: int, analysis_id: str
    ) -> None:
        if source_page < 0:
            raise ReadingDataError("invalid source page")
        run = self.get_parse_run(owner_user_id, run_id)
        analysis = self.get_page_analysis(owner_user_id, analysis_id)
        if run is None or analysis is None:
            raise ReadingDataError("parse run page not found")
        analysis_run = self.get_parse_run(owner_user_id, analysis.creating_run_id)
        if analysis_run is None or analysis_run.document_id != run.document_id:
            raise ReadingDataError("invalid page analysis")
        try:
            self._connection.execute(
                """INSERT INTO reading_run_pages (run_id, source_page, analysis_id)
                   VALUES (?, ?, ?)""",
                (run_id, source_page, analysis_id),
            )
        except (sqlite3.IntegrityError, PostgresIntegrityError) as exc:
            raise ReadingDataError("page snapshot already exists") from exc
        self._connection.commit()

    def list_run_pages(
        self, owner_user_id: str, run_id: str
    ) -> list[tuple[int, str]]:
        if self.get_parse_run(owner_user_id, run_id) is None:
            return []
        rows = self._connection.execute(
            """SELECT source_page, analysis_id FROM reading_run_pages
               WHERE run_id = ? ORDER BY source_page""",
            (run_id,),
        ).fetchall()
        return [(int(row["source_page"]), str(row["analysis_id"])) for row in rows]

    def record_page_blocks(
        self,
        owner_user_id: str,
        analysis_id: str,
        blocks: list[dict[str, Any]],
    ) -> None:
        if self.get_page_analysis(owner_user_id, analysis_id) is None:
            raise ReadingDataError("page analysis not found")
        values: list[tuple[Any, ...]] = []
        for index, block in enumerate(blocks):
            text = block.get("text")
            bbox = block.get("bbox")
            confidence = block.get("confidence")
            kind = block.get("kind")
            order = block.get("reading_order")
            if (
                not isinstance(text, str)
                or not isinstance(kind, str)
                or not isinstance(order, int)
                or (
                    bbox is not None
                    and (
                        not isinstance(bbox, list)
                        or len(bbox) != 4
                        or not all(isinstance(item, (int, float)) for item in bbox)
                    )
                )
                or (confidence is not None and not isinstance(confidence, (int, float)))
            ):
                raise ReadingDataError("invalid page block")
            values.append(
                (
                    analysis_id,
                    index,
                    text,
                    json.dumps(bbox) if bbox is not None else None,
                    confidence,
                    kind,
                    order,
                )
            )
        with self._connection:
            self._connection.execute(
                "DELETE FROM reading_page_blocks WHERE analysis_id = ?", (analysis_id,)
            )
            self._connection.executemany(
                """INSERT INTO reading_page_blocks
                   (analysis_id, block_index, text, bbox_json, confidence, kind, reading_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                values,
            )

    def list_page_blocks(
        self, owner_user_id: str, analysis_id: str
    ) -> list[dict[str, Any]]:
        if self.get_page_analysis(owner_user_id, analysis_id) is None:
            return []
        rows = self._connection.execute(
            """SELECT text, bbox_json, confidence, kind, reading_order
               FROM reading_page_blocks WHERE analysis_id = ?
               ORDER BY reading_order, block_index""",
            (analysis_id,),
        ).fetchall()
        return [
            {
                "text": row["text"],
                "bbox": json.loads(row["bbox_json"])
                if row["bbox_json"] is not None
                else None,
                "confidence": row["confidence"],
                "kind": row["kind"],
                "reading_order": row["reading_order"],
            }
            for row in rows
        ]

    def get_parse_run(
        self, owner_user_id: str, run_id: str
    ) -> ReadingParseRun | None:
        row = self._fetchone(
            """SELECT r.* FROM reading_parse_runs r
               JOIN reading_documents d ON d.id = r.document_id
               WHERE r.id = ? AND d.owner_user_id = ?""",
            (run_id, owner_user_id),
        )
        return self._as_model(ReadingParseRun, row) if row else None

    def update_parse_run_status(
        self, owner_user_id: str, run_id: str, status: str
    ) -> ReadingParseRun | None:
        self._validate_parse_run_status(status)
        now = self._now()
        cursor = self._connection.execute(
            """UPDATE reading_parse_runs SET status = ?, updated_at = ?
               WHERE id = ? AND EXISTS (
                   SELECT 1 FROM reading_documents d
                   WHERE d.id = reading_parse_runs.document_id
                     AND d.owner_user_id = ?
               )""",
            (status, now, run_id, owner_user_id),
        )
        self._connection.commit()
        return self.get_parse_run(owner_user_id, run_id) if cursor.rowcount else None

    def activate_parse_run(
        self,
        owner_user_id: str,
        document_id: str,
        run_id: str,
        *,
        outline_json: str,
        parse_quality: str,
        parse_warning_count: int,
        progress_locator: ReadingLocator | None = None,
        locator_resolutions: list[dict[str, Any]] | None = None,
    ) -> ReadingDocument | None:
        self._validate_parse_quality(parse_quality)
        if parse_warning_count < 0:
            raise ReadingDataError("invalid parse warning count")
        run = self.get_parse_run(owner_user_id, run_id)
        if run is None or run.document_id != document_id or run.status != "completed":
            raise ReadingDataError("parse run is not ready")
        now = self._now()
        with self._connection:
            cursor = self._connection.execute(
                """UPDATE reading_documents
                   SET active_parse_run_id = ?, parse_generation = ?, outline_json = ?,
                       parse_quality = ?, parse_warning_count = ?, status = 'ready',
                       parse_error = NULL, updated_at = ?
                   WHERE id = ? AND owner_user_id = ?""",
                (
                    run_id,
                    run.generation,
                    outline_json,
                    parse_quality,
                    parse_warning_count,
                    now,
                    document_id,
                    owner_user_id,
                ),
            )
            if progress_locator is not None:
                self._connection.execute(
                    """UPDATE reading_progress SET locator_json = ?, updated_at = ?
                       WHERE owner_user_id = ? AND document_id = ?""",
                    (
                        self._encode_locator(progress_locator),
                        now,
                        owner_user_id,
                        document_id,
                    ),
                )
            for resolution in locator_resolutions or []:
                self._insert_locator_resolution(
                    owner_user_id,
                    document_id,
                    run_id,
                    resolution,
                    now,
                )
        return self.get_document(owner_user_id, document_id) if cursor.rowcount else None

    def _insert_locator_resolution(
        self,
        owner_user_id: str,
        document_id: str,
        run_id: str,
        resolution: dict[str, Any],
        created_at: str,
    ) -> None:
        target_type = resolution.get("target_type")
        status = resolution.get("status")
        old_locator = resolution.get("old_locator")
        resolved_locator = resolution.get("resolved_locator")
        reason = resolution.get("reason")
        if target_type not in {"progress", "annotation"}:
            raise ReadingDataError("invalid locator resolution target")
        if status not in {"resolved", "unresolved"}:
            raise ReadingDataError("invalid locator resolution status")
        if not isinstance(old_locator, ReadingLocator) or not isinstance(reason, str):
            raise ReadingDataError("invalid locator resolution")
        if resolved_locator is not None and not isinstance(
            resolved_locator, ReadingLocator
        ):
            raise ReadingDataError("invalid resolved locator")
        self._connection.execute(
            """INSERT INTO reading_locator_resolutions
               (id, owner_user_id, document_id, target_run_id, target_type,
                old_locator_json, resolved_locator_json, status, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self._id(),
                owner_user_id,
                document_id,
                run_id,
                target_type,
                self._encode_locator(old_locator),
                self._encode_locator(resolved_locator)
                if resolved_locator is not None
                else None,
                status,
                reason,
                created_at,
            ),
        )

    def list_locator_resolutions(
        self, owner_user_id: str, document_id: str, run_id: str
    ) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """SELECT target_type, old_locator_json, resolved_locator_json, status, reason
               FROM reading_locator_resolutions
               WHERE owner_user_id = ? AND document_id = ? AND target_run_id = ?
               ORDER BY created_at, id""",
            (owner_user_id, document_id, run_id),
        ).fetchall()
        return [
            {
                "target_type": row["target_type"],
                "old_locator": json.loads(row["old_locator_json"]),
                "resolved_locator": json.loads(row["resolved_locator_json"])
                if row["resolved_locator_json"] is not None
                else None,
                "status": row["status"],
                "reason": row["reason"],
            }
            for row in rows
        ]

    def update_document(self, owner_user_id: str, document_id: str, **changes: Any) -> ReadingDocument | None:
        allowed = {"title", "author", "format", "source_path", "file_size", "status", "parse_error", "cover_path", "outline_json", "parse_generation", "last_opened_at"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if "status" in values:
            self._validate_status(values["status"])
        if not values:
            return self.get_document(owner_user_id, document_id)
        values["updated_at"] = self._now()
        assignment = ", ".join(f"{key} = ?" for key in values)
        cursor = self._connection.execute(f"UPDATE reading_documents SET {assignment} WHERE owner_user_id = ? AND id = ?", (*values.values(), owner_user_id, document_id))
        self._connection.commit()
        return self.get_document(owner_user_id, document_id) if cursor.rowcount else None

    def recover_interrupted_pdf_ocr(
        self, *, older_than: datetime | None = None
    ) -> int:
        conditions = ["format = 'pdf'", "status = 'processing'"]
        params: list[Any] = [self._now()]
        if older_than is not None:
            conditions.append("updated_at < ?")
            params.append(older_than.isoformat(timespec="microseconds"))
        cursor = self._connection.execute(
            "UPDATE reading_documents "
            "SET status = 'needs_ocr', parse_error = 'ocr_interrupted', updated_at = ? "
            f"WHERE {' AND '.join(conditions)}",
            params,
        )
        self._connection.commit()
        return cursor.rowcount

    def delete_document(self, owner_user_id: str, document_id: str) -> bool:
        if not self.get_document(owner_user_id, document_id):
            return False
        with self._connection:
            self._connection.execute(
                "UPDATE focus_materials SET source_id = NULL WHERE owner_user_id = ? AND source_id = ?",
                (owner_user_id, document_id),
            )
            self._connection.execute("DELETE FROM reading_documents WHERE owner_user_id = ? AND id = ?", (owner_user_id, document_id))
        return True

    def delete_document_with_job(
        self,
        owner_user_id: str,
        document_id: str,
        *,
        source_path: str,
        asset_dir: str,
    ) -> dict[str, str] | None:
        if not self.get_document(owner_user_id, document_id):
            return None
        job = {
            "id": self._id(),
            "source_path": source_path,
            "asset_dir": asset_dir,
            "created_at": self._now(),
        }
        with self._connection:
            self._connection.execute(
                """INSERT INTO reading_deletion_jobs
                   (id, source_path, asset_dir, created_at)
                   VALUES (?, ?, ?, ?)""",
                tuple(job.values()),
            )
            self._connection.execute(
                "DELETE FROM focus_materials WHERE owner_user_id = ? AND source_id = ?",
                (owner_user_id, document_id),
            )
            self._connection.execute(
                "DELETE FROM reading_documents WHERE owner_user_id = ? AND id = ?",
                (owner_user_id, document_id),
            )
        return job

    def list_deletion_jobs(self) -> list[dict[str, str]]:
        rows = self._connection.execute(
            "SELECT id, source_path, asset_dir, created_at "
            "FROM reading_deletion_jobs ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def complete_deletion_job(self, job_id: str) -> bool:
        cursor = self._connection.execute(
            "DELETE FROM reading_deletion_jobs WHERE id = ?", (job_id,)
        )
        self._connection.commit()
        return bool(cursor.rowcount)

    def create_chapter(self, owner_user_id: str, document_id: str, *, position: int, title: str,
                       source_locator: ReadingLocator, plain_text: str, sanitized_html: str,
                       parent_id: str | None = None, parse_run_id: str | None = None) -> ReadingChapter:
        if not self.get_document(owner_user_id, document_id):
            raise ReadingDataError("document not found")
        if parse_run_id is not None:
            run = self.get_parse_run(owner_user_id, parse_run_id)
            if run is None or run.document_id != document_id:
                raise ReadingDataError("invalid parse run")
        self._validate_parent_chapter(owner_user_id, document_id, parent_id)
        chapter_id, now = self._id(), self._now()
        self._connection.execute("""INSERT INTO reading_chapters (id, document_id, position, parent_id, title,
            source_locator_json, plain_text, sanitized_html, created_at, parse_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chapter_id, document_id, position, parent_id, title, self._encode_locator(source_locator), plain_text, sanitized_html, now, parse_run_id))
        self._connection.commit()
        return self.get_chapter(owner_user_id, chapter_id)  # type: ignore[return-value]

    def get_chapter(self, owner_user_id: str, chapter_id: str) -> ReadingChapter | None:
        row = self._fetchone("""SELECT c.* FROM reading_chapters c JOIN reading_documents d ON d.id = c.document_id
            WHERE d.owner_user_id = ? AND c.id = ?""", (owner_user_id, chapter_id))
        return self._as_model(ReadingChapter, row, {"source_locator": ReadingLocator}) if row else None

    def list_chapters(self, owner_user_id: str, document_id: str) -> list[ReadingChapter]:
        rows = self._connection.execute("""SELECT c.* FROM reading_chapters c JOIN reading_documents d ON d.id = c.document_id
            WHERE d.owner_user_id = ? AND c.document_id = ?
              AND ((d.active_parse_run_id IS NULL AND c.parse_run_id IS NULL)
                   OR c.parse_run_id = d.active_parse_run_id)
            ORDER BY c.position""", (owner_user_id, document_id)).fetchall()
        return [self._as_model(ReadingChapter, row, {"source_locator": ReadingLocator}) for row in rows]

    def update_chapter(self, owner_user_id: str, chapter_id: str, **changes: Any) -> ReadingChapter | None:
        allowed = {"position", "parent_id", "title", "plain_text", "sanitized_html"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if "source_locator" in changes:
            values["source_locator_json"] = self._encode_locator(changes["source_locator"])
        if not values:
            return self.get_chapter(owner_user_id, chapter_id)
        target = self._fetchone(
            """SELECT c.document_id FROM reading_chapters c
               JOIN reading_documents d ON d.id = c.document_id
               WHERE c.id = ? AND d.owner_user_id = ?""",
            (chapter_id, owner_user_id),
        )
        if target is None:
            return None
        if "parent_id" in values:
            self._validate_parent_chapter(
                owner_user_id, target["document_id"], values["parent_id"]
            )
        assignment = ", ".join(f"{key} = ?" for key in values)
        cursor = self._connection.execute(f"""UPDATE reading_chapters SET {assignment} WHERE id = ? AND EXISTS
            (SELECT 1 FROM reading_documents d WHERE d.id = reading_chapters.document_id AND d.owner_user_id = ?)""", (*values.values(), chapter_id, owner_user_id))
        self._connection.commit()
        return self.get_chapter(owner_user_id, chapter_id) if cursor.rowcount else None

    def delete_chapter(self, owner_user_id: str, chapter_id: str) -> bool:
        cursor = self._connection.execute("""DELETE FROM reading_chapters WHERE id = ? AND EXISTS
            (SELECT 1 FROM reading_documents d WHERE d.id = reading_chapters.document_id AND d.owner_user_id = ?)""", (chapter_id, owner_user_id))
        self._connection.commit()
        return bool(cursor.rowcount)

    def upsert_progress(self, owner_user_id: str, document_id: str, *, mode: str, locator: ReadingLocator, percent: float) -> ReadingProgress:
        if not self.get_document(owner_user_id, document_id):
            raise ReadingDataError("document not found")
        now = self._now()
        self._connection.execute("""INSERT INTO reading_progress (owner_user_id, document_id, mode, locator_json, percent, updated_at)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(owner_user_id, document_id) DO UPDATE SET
            mode = excluded.mode, locator_json = excluded.locator_json, percent = excluded.percent, updated_at = excluded.updated_at""",
            (owner_user_id, document_id, mode, self._encode_locator(locator), percent, now))
        self._connection.commit()
        return self.get_progress(owner_user_id, document_id)  # type: ignore[return-value]

    def get_progress(self, owner_user_id: str, document_id: str) -> ReadingProgress | None:
        row = self._fetchone("SELECT * FROM reading_progress WHERE owner_user_id = ? AND document_id = ?", (owner_user_id, document_id))
        return self._as_model(ReadingProgress, row, {"locator": ReadingLocator}) if row else None

    def delete_progress(self, owner_user_id: str, document_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM reading_progress WHERE owner_user_id = ? AND document_id = ?", (owner_user_id, document_id))
        self._connection.commit()
        return bool(cursor.rowcount)

    def upsert_preferences(self, owner_user_id: str, *, theme: str, font_family: str, font_size: int,
                           layout: str, sound_track: str, sound_volume: float) -> ReadingPreferences:
        now = self._now()
        self._connection.execute("""INSERT INTO reading_preferences (owner_user_id, theme, font_family, font_size, layout, sound_track, sound_volume, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(owner_user_id) DO UPDATE SET theme = excluded.theme,
            font_family = excluded.font_family, font_size = excluded.font_size, layout = excluded.layout,
            sound_track = excluded.sound_track, sound_volume = excluded.sound_volume, updated_at = excluded.updated_at""",
            (owner_user_id, theme, font_family, font_size, layout, sound_track, sound_volume, now))
        self._connection.commit()
        return self.get_preferences(owner_user_id)  # type: ignore[return-value]

    def get_preferences(self, owner_user_id: str) -> ReadingPreferences | None:
        row = self._fetchone("SELECT * FROM reading_preferences WHERE owner_user_id = ?", (owner_user_id,))
        return self._as_model(ReadingPreferences, row) if row else None

    def delete_preferences(self, owner_user_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM reading_preferences WHERE owner_user_id = ?", (owner_user_id,))
        self._connection.commit()
        return bool(cursor.rowcount)

    def create_annotation(self, owner_user_id: str, document_id: str, *, kind: str, locator: ReadingRangeLocator,
                          quote: str, note_body: str | None, color: str | None) -> ReadingAnnotation:
        self._validate_annotation_kind(kind)
        if not self.get_document(owner_user_id, document_id):
            raise ReadingDataError("document not found")
        annotation_id, now = self._id(), self._now()
        self._connection.execute("""INSERT INTO reading_annotations (id, owner_user_id, document_id, kind, locator_json,
            quote, note_body, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (annotation_id, owner_user_id, document_id, kind, self._encode_locator(locator), quote, note_body, color, now, now))
        self._connection.commit()
        return self.get_annotation(owner_user_id, annotation_id)  # type: ignore[return-value]

    def get_annotation(self, owner_user_id: str, annotation_id: str) -> ReadingAnnotation | None:
        row = self._fetchone("SELECT * FROM reading_annotations WHERE owner_user_id = ? AND id = ?", (owner_user_id, annotation_id))
        return self._as_model(ReadingAnnotation, row, {"locator": ReadingRangeLocator}) if row else None

    def list_annotations(self, owner_user_id: str, document_id: str) -> list[ReadingAnnotation]:
        rows = self._connection.execute("SELECT * FROM reading_annotations WHERE owner_user_id = ? AND document_id = ? ORDER BY updated_at DESC", (owner_user_id, document_id)).fetchall()
        return [self._as_model(ReadingAnnotation, row, {"locator": ReadingRangeLocator}) for row in rows]

    def update_annotation(self, owner_user_id: str, annotation_id: str, **changes: Any) -> ReadingAnnotation | None:
        allowed = {"kind", "quote", "note_body", "color"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if "kind" in values:
            self._validate_annotation_kind(values["kind"])
        if "locator" in changes:
            values["locator_json"] = self._encode_locator(changes["locator"])
        if not values:
            return self.get_annotation(owner_user_id, annotation_id)
        values["updated_at"] = self._now()
        assignment = ", ".join(f"{key} = ?" for key in values)
        cursor = self._connection.execute(f"UPDATE reading_annotations SET {assignment} WHERE owner_user_id = ? AND id = ?", (*values.values(), owner_user_id, annotation_id))
        self._connection.commit()
        return self.get_annotation(owner_user_id, annotation_id) if cursor.rowcount else None

    def delete_annotation(self, owner_user_id: str, annotation_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM reading_annotations WHERE owner_user_id = ? AND id = ?", (owner_user_id, annotation_id))
        self._connection.commit()
        return bool(cursor.rowcount)

    def create_material(self, owner_user_id: str, *, source_type: str, source_id: str | None, source_title: str,
                        quote: str, note: str | None, locator: ReadingRangeLocator | None) -> FocusMaterial:
        material_id, now = self._id(), self._now()
        locator_json = self._encode_locator(locator) if locator is not None else None
        self._connection.execute("""INSERT INTO focus_materials (id, owner_user_id, source_type, source_id, source_title, quote, note, locator_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (material_id, owner_user_id, source_type, source_id, source_title, quote, note, locator_json, now))
        self._connection.commit()
        return self.get_material(owner_user_id, material_id)  # type: ignore[return-value]

    def get_material(self, owner_user_id: str, material_id: str) -> FocusMaterial | None:
        row = self._fetchone("SELECT * FROM focus_materials WHERE owner_user_id = ? AND id = ?", (owner_user_id, material_id))
        return self._as_model(FocusMaterial, row, {"locator": ReadingRangeLocator}) if row else None

    def list_materials(self, owner_user_id: str, *, consumed: bool | None = None) -> list[FocusMaterial]:
        query, params = "SELECT * FROM focus_materials WHERE owner_user_id = ?", [owner_user_id]
        if consumed is not None:
            query += " AND consumed_at IS " + ("NOT NULL" if consumed else "NULL")
        query += " ORDER BY created_at DESC"
        rows = self._connection.execute(query, params).fetchall()
        return [self._as_model(FocusMaterial, row, {"locator": ReadingRangeLocator}) for row in rows]

    def update_material(self, owner_user_id: str, material_id: str, **changes: Any) -> FocusMaterial | None:
        allowed = {"source_type", "source_id", "source_title", "quote", "note"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if "locator" in changes:
            values["locator_json"] = self._encode_locator(changes["locator"]) if changes["locator"] is not None else None
        if "consumed" in changes:
            values["consumed_at"] = self._now() if changes["consumed"] else None
        if not values:
            return self.get_material(owner_user_id, material_id)
        assignment = ", ".join(f"{key} = ?" for key in values)
        cursor = self._connection.execute(f"UPDATE focus_materials SET {assignment} WHERE owner_user_id = ? AND id = ?", (*values.values(), owner_user_id, material_id))
        self._connection.commit()
        return self.get_material(owner_user_id, material_id) if cursor.rowcount else None

    def delete_material(self, owner_user_id: str, material_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM focus_materials WHERE owner_user_id = ? AND id = ?", (owner_user_id, material_id))
        self._connection.commit()
        return bool(cursor.rowcount)
