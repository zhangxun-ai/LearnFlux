"""Owner-scoped persistence for daily and periodic personal reviews."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..utils.logging import setup_logger

logger = setup_logger("review_repository")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_daily_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    review_date TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    fact TEXT NOT NULL DEFAULT '',
    quick_meaning TEXT NOT NULL DEFAULT '',
    meaning_type TEXT NOT NULL DEFAULT '',
    meaning_types_json TEXT NOT NULL DEFAULT '[]',
    meaning_custom TEXT NOT NULL DEFAULT '',
    people_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    past_json TEXT NOT NULL DEFAULT '{}',
    present_json TEXT NOT NULL DEFAULT '{}',
    emotions_json TEXT NOT NULL DEFAULT '[]',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_daily_user_date
    ON review_daily_events(user_id, review_date DESC, position);

CREATE TABLE IF NOT EXISTS review_weekly_reviews (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    focus_ids_json TEXT NOT NULL DEFAULT '[]',
    abstraction_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, week_start)
);
CREATE INDEX IF NOT EXISTS idx_review_weekly_user_start
    ON review_weekly_reviews(user_id, week_start DESC);

CREATE TABLE IF NOT EXISTS review_connections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    connection_type TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'daily',
    source_id TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'daily',
    target_id TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'forward',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_connections_period
    ON review_connections(user_id, period_type, period_key, updated_at DESC);

CREATE TABLE IF NOT EXISTS review_action_experiments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    period_key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    why_text TEXT NOT NULL DEFAULT '',
    what_text TEXT NOT NULL DEFAULT '',
    who_text TEXT NOT NULL DEFAULT '',
    when_text TEXT NOT NULL DEFAULT '',
    where_text TEXT NOT NULL DEFAULT '',
    how_text TEXT NOT NULL DEFAULT '',
    resources TEXT NOT NULL DEFAULT '',
    budget TEXT NOT NULL DEFAULT '',
    success_signal TEXT NOT NULL DEFAULT '',
    desire_check TEXT NOT NULL DEFAULT '',
    control_check TEXT NOT NULL DEFAULT '',
    first_step TEXT NOT NULL DEFAULT '',
    review_date TEXT,
    result TEXT NOT NULL DEFAULT '',
    executed TEXT NOT NULL DEFAULT '',
    insight_result TEXT NOT NULL DEFAULT '',
    next_decision TEXT NOT NULL DEFAULT '',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_experiments_user_review
    ON review_action_experiments(user_id, review_date, updated_at DESC);

CREATE TABLE IF NOT EXISTS review_monthly_reviews (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    month_key TEXT NOT NULL,
    inner_json TEXT NOT NULL DEFAULT '[]',
    actions_json TEXT NOT NULL DEFAULT '[]',
    results_json TEXT NOT NULL DEFAULT '[]',
    notes_json TEXT NOT NULL DEFAULT '[]',
    cross_month_json TEXT NOT NULL DEFAULT '[]',
    affirmation TEXT NOT NULL DEFAULT '',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, month_key)
);
CREATE INDEX IF NOT EXISTS idx_review_monthly_user_month
    ON review_monthly_reviews(user_id, month_key DESC);

CREATE TABLE IF NOT EXISTS review_annual_reviews (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    year_key TEXT NOT NULL,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    cross_month_json TEXT NOT NULL DEFAULT '[]',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, year_key)
);
CREATE INDEX IF NOT EXISTS idx_review_annual_user_year
    ON review_annual_reviews(user_id, year_key DESC);

CREATE TABLE IF NOT EXISTS review_insights (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    level INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    counter_evidence_json TEXT NOT NULL DEFAULT '[]',
    evidence_span_json TEXT NOT NULL DEFAULT '{}',
    evidence_strength_json TEXT NOT NULL DEFAULT '{}',
    uncertainty DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    uncertainty_note TEXT NOT NULL DEFAULT '',
    verification_experiment TEXT NOT NULL DEFAULT '',
    verification_experiment_id TEXT,
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    ai_candidate_id TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_insights_user_tier_status
    ON review_insights(user_id, tier, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS review_ai_candidates (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    scope_json TEXT NOT NULL DEFAULT '[]',
    candidate_json TEXT NOT NULL DEFAULT '{}',
    confirmed_content_json TEXT,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_ai_user_status
    ON review_ai_candidates(user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS review_preferences (
    user_id TEXT PRIMARY KEY,
    newbie_mode INTEGER NOT NULL DEFAULT 1,
    week_start_day INTEGER NOT NULL DEFAULT 0,
    obsidian_root TEXT NOT NULL DEFAULT '复盘',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_sync_state (
    user_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    relative_path TEXT,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    synced_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, record_type, record_id)
);
CREATE INDEX IF NOT EXISTS idx_review_sync_user_status
    ON review_sync_state(user_id, status, updated_at DESC);
"""


_JSON_COLUMNS = {
    "past_json": "past",
    "present_json": "present",
    "emotions_json": "emotions",
    "meaning_types_json": "meaning_types",
    "people_json": "people",
    "keywords_json": "keywords",
    "source_refs_json": "source_refs",
    "focus_ids_json": "focus_ids",
    "abstraction_json": "abstraction",
    "source_ids_json": "source_ids",
    "inner_json": "inner",
    "actions_json": "actions",
    "results_json": "results",
    "notes_json": "notes",
    "cross_month_json": "cross_month",
    "keywords_json": "keywords",
    "evidence_json": "evidence",
    "counter_evidence_json": "counter_evidence",
    "evidence_span_json": "evidence_span",
    "evidence_strength_json": "evidence_strength",
    "scope_json": "scope",
    "candidate_json": "candidate",
    "confirmed_content_json": "confirmed_content",
}


class ReviewDataError(ValueError):
    """Stored or submitted review data violates a domain contract."""


class ReviewRepository:
    """Persist review records with owner isolation on SQLite and PostgreSQL."""

    def __init__(self, database: str | Path | object) -> None:
        self.database = database if hasattr(database, "transaction") else None
        self._is_postgres = getattr(self.database, "dialect", None) == "postgres"
        raw_path = getattr(database, "path", None) if self.database else database
        self.db_path = Path(raw_path) if raw_path not in (None, ":memory:") else raw_path
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_database()

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat(timespec="microseconds")

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _bounded_limit(value: int, maximum: int = 500) -> int:
        return max(1, min(int(value), maximum))

    def _get_connection(self) -> sqlite3.Connection:
        if self.database is not None:
            raise RuntimeError("adapter_connections_must_be_scoped")
        if not hasattr(self._local, "connection"):
            target = str(self.db_path or ":memory:")
            connection = sqlite3.connect(target)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:
                logger.warning("WAL mode is unavailable for review repository")
            self._local.connection = connection
        return self._local.connection

    @contextmanager
    def _cursor(self):
        if self.database is not None:
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

    def close(self) -> None:
        if self.database is not None:
            return
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            del self._local.connection

    def _init_database(self) -> None:
        with self._cursor() as cursor:
            cursor.executescript(_SCHEMA)

    @staticmethod
    def _row(raw: Any | None) -> dict[str, Any] | None:
        if raw is None:
            return None
        item = dict(raw)
        for column, public_name in _JSON_COLUMNS.items():
            if column not in item:
                continue
            value = item.pop(column)
            if value in (None, ""):
                item[public_name] = None if column == "confirmed_content_json" else []
                continue
            try:
                item[public_name] = json.loads(value) if isinstance(value, str) else value
            except (TypeError, json.JSONDecodeError) as exc:
                raise ReviewDataError(f"invalid stored JSON in {column}") from exc
        for key, value in tuple(item.items()):
            if isinstance(value, datetime):
                item[key] = value.isoformat()
        if "newbie_mode" in item:
            item["newbie_mode"] = bool(item["newbie_mode"])
        return item

    @classmethod
    def _rows(cls, values: Iterable[Any]) -> list[dict[str, Any]]:
        return [item for raw in values if (item := cls._row(raw)) is not None]

    def _fetch_owned(self, table: str, user_id: str, record_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
                (record_id, user_id),
            )
            return self._row(cursor.fetchone())

    def create_daily_event(
        self, user_id: str, review_date: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        event_id = self.new_id("dre")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM review_daily_events "
                "WHERE user_id = ? AND review_date = ?",
                (user_id, review_date),
            )
            position = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO review_daily_events (
                    id, user_id, review_date, position, title, fact,
                    quick_meaning, meaning_type, meaning_types_json,
                    meaning_custom, people_json, keywords_json, past_json,
                    present_json, emotions_json, source_refs_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    user_id,
                    review_date,
                    int(payload.get("position", position)),
                    str(payload.get("title") or ""),
                    str(payload.get("fact") or ""),
                    str(payload.get("quick_meaning") or ""),
                    str(payload.get("meaning_type") or ""),
                    self.dump(
                        payload.get("meaning_types")
                        or ([payload.get("meaning_type")] if payload.get("meaning_type") else [])
                    ),
                    str(payload.get("meaning_custom") or ""),
                    self.dump(payload.get("people") or []),
                    self.dump(payload.get("keywords") or []),
                    self.dump(payload.get("past") or {}),
                    self.dump(payload.get("present") or {}),
                    self.dump(payload.get("emotions") or []),
                    self.dump(payload.get("source_refs") or []),
                    str(payload.get("status") or "active"),
                    now,
                    now,
                ),
            )
        return self.get_daily_event(user_id, event_id) or {}

    def get_daily_event(self, user_id: str, event_id: str) -> dict[str, Any] | None:
        return self._fetch_owned("review_daily_events", user_id, event_id)

    def list_daily_events(
        self,
        user_id: str,
        *,
        review_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if review_date:
            clauses.append("review_date = ?")
            params.append(review_date)
        if start_date:
            clauses.append("review_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("review_date <= ?")
            params.append(end_date)
        params.append(self._bounded_limit(limit))
        with self._cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM review_daily_events
                WHERE {' AND '.join(clauses)}
                ORDER BY review_date DESC, position ASC, created_at ASC
                LIMIT ?
                """,
                params,
            )
            return self._rows(cursor.fetchall())

    def update_daily_event(
        self, user_id: str, event_id: str, payload: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        scalar = {
            "review_date": "review_date",
            "position": "position",
            "title": "title",
            "fact": "fact",
            "quick_meaning": "quick_meaning",
            "meaning_type": "meaning_type",
            "meaning_custom": "meaning_custom",
            "status": "status",
        }
        structured = {
            "meaning_types": "meaning_types_json",
            "people": "people_json",
            "keywords": "keywords_json",
            "past": "past_json",
            "present": "present_json",
            "emotions": "emotions_json",
            "source_refs": "source_refs_json",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, column in scalar.items():
            if key in payload:
                updates.append(f"{column} = ?")
                params.append(payload[key] if key == "position" else str(payload[key] or ""))
        for key, column in structured.items():
            if key in payload:
                updates.append(f"{column} = ?")
                params.append(self.dump(payload[key] if payload[key] is not None else []))
        if not updates:
            return self.get_daily_event(user_id, event_id)
        updates.append("updated_at = ?")
        params.extend([self.now(), event_id, user_id])
        with self._cursor() as cursor:
            cursor.execute(
                f"UPDATE review_daily_events SET {', '.join(updates)} "
                "WHERE id = ? AND user_id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get_daily_event(user_id, event_id)

    def delete_daily_event(self, user_id: str, event_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM review_daily_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )
            return cursor.rowcount > 0

    def duplicate_daily_event(self, user_id: str, event_id: str) -> dict[str, Any] | None:
        source = self.get_daily_event(user_id, event_id)
        if source is None:
            return None
        payload = {
            key: source.get(key)
            for key in (
                "title", "fact", "quick_meaning", "meaning_type", "meaning_types",
                "meaning_custom", "people", "keywords", "past", "present",
                "emotions", "source_refs", "status",
            )
        }
        if payload.get("title"):
            payload["title"] = f"{payload['title']}（副本）"
        return self.create_daily_event(user_id, source["review_date"], payload)

    def reorder_daily_events(self, user_id: str, review_date: str, ids: list[str]) -> list[dict[str, Any]]:
        existing = self.list_daily_events(user_id, review_date=review_date, limit=500)
        existing_ids = {item["id"] for item in existing}
        if set(ids) != existing_ids or len(ids) != len(existing_ids):
            raise ReviewDataError("daily event order must contain every event exactly once")
        now = self.now()
        with self._cursor() as cursor:
            for position, event_id in enumerate(ids):
                cursor.execute(
                    "UPDATE review_daily_events SET position = ?, updated_at = ? "
                    "WHERE id = ? AND user_id = ? AND review_date = ?",
                    (position, now, event_id, user_id, review_date),
                )
        return self.list_daily_events(user_id, review_date=review_date, limit=500)

    def upsert_weekly(
        self, user_id: str, week_start: str, week_end: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        review_id = self.new_id("wre")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_weekly_reviews (
                    id, user_id, week_start, week_end, focus_ids_json,
                    abstraction_json, summary, source_ids_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, week_start) DO UPDATE SET
                    week_end = excluded.week_end,
                    focus_ids_json = excluded.focus_ids_json,
                    abstraction_json = excluded.abstraction_json,
                    summary = excluded.summary,
                    source_ids_json = excluded.source_ids_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    review_id,
                    user_id,
                    week_start,
                    week_end,
                    self.dump(payload.get("focus_ids") or []),
                    self.dump(payload.get("abstraction") or {}),
                    str(payload.get("summary") or ""),
                    self.dump(payload.get("source_ids") or []),
                    str(payload.get("status") or "draft"),
                    now,
                    now,
                ),
            )
        return self.get_weekly(user_id, week_start) or {}

    def get_weekly(self, user_id: str, week_start: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM review_weekly_reviews WHERE user_id = ? AND week_start = ?",
                (user_id, week_start),
            )
            return self._row(cursor.fetchone())

    def list_weekly(self, user_id: str, *, year: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
        query = "SELECT * FROM review_weekly_reviews WHERE user_id = ?"
        params: list[Any] = [user_id]
        if year:
            query += " AND week_start >= ? AND week_start <= ?"
            params.extend([f"{year}-01-01", f"{year}-12-31"])
        query += " ORDER BY week_start DESC LIMIT ?"
        params.append(self._bounded_limit(limit))
        with self._cursor() as cursor:
            cursor.execute(query, params)
            return self._rows(cursor.fetchall())

    def upsert_monthly(self, user_id: str, month_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        review_id = self.new_id("mre")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_monthly_reviews (
                    id, user_id, month_key, inner_json, actions_json, results_json,
                    notes_json, cross_month_json, affirmation, source_ids_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, month_key) DO UPDATE SET
                    inner_json = excluded.inner_json,
                    actions_json = excluded.actions_json,
                    results_json = excluded.results_json,
                    notes_json = excluded.notes_json,
                    cross_month_json = excluded.cross_month_json,
                    affirmation = excluded.affirmation,
                    source_ids_json = excluded.source_ids_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    review_id, user_id, month_key,
                    self.dump(payload.get("inner") or []),
                    self.dump(payload.get("actions") or []),
                    self.dump(payload.get("results") or []),
                    self.dump(payload.get("notes") or []),
                    self.dump(payload.get("cross_month") or []),
                    str(payload.get("affirmation") or ""),
                    self.dump(payload.get("source_ids") or []),
                    str(payload.get("status") or "draft"), now, now,
                ),
            )
        return self.get_monthly(user_id, month_key) or {}

    def get_monthly(self, user_id: str, month_key: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM review_monthly_reviews WHERE user_id = ? AND month_key = ?",
                (user_id, month_key),
            )
            return self._row(cursor.fetchone())

    def list_monthly(self, user_id: str, *, year: str | None = None, limit: int = 24) -> list[dict[str, Any]]:
        query = "SELECT * FROM review_monthly_reviews WHERE user_id = ?"
        params: list[Any] = [user_id]
        if year:
            query += " AND month_key >= ? AND month_key <= ?"
            params.extend([f"{year}-01", f"{year}-12"])
        query += " ORDER BY month_key DESC LIMIT ?"
        params.append(self._bounded_limit(limit))
        with self._cursor() as cursor:
            cursor.execute(query, params)
            return self._rows(cursor.fetchall())

    def upsert_annual(self, user_id: str, year_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        review_id = self.new_id("are")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_annual_reviews (
                    id, user_id, year_key, keywords_json, summary,
                    cross_month_json, source_ids_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, year_key) DO UPDATE SET
                    keywords_json = excluded.keywords_json,
                    summary = excluded.summary,
                    cross_month_json = excluded.cross_month_json,
                    source_ids_json = excluded.source_ids_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    review_id, user_id, year_key,
                    self.dump(payload.get("keywords") or []),
                    str(payload.get("summary") or ""),
                    self.dump(payload.get("cross_month") or []),
                    self.dump(payload.get("source_ids") or []),
                    str(payload.get("status") or "draft"), now, now,
                ),
            )
        return self.get_annual(user_id, year_key) or {}

    def get_annual(self, user_id: str, year_key: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM review_annual_reviews WHERE user_id = ? AND year_key = ?",
                (user_id, year_key),
            )
            return self._row(cursor.fetchone())

    def create_connection(self, user_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        source_ids = [
            str(value.get("id") or value.get("source_id") or "")
            if isinstance(value, Mapping)
            else str(value)
            for value in payload.get("source_ids") or []
            if value
        ]
        source_type = str(payload.get("source_type") or "daily")
        source_id = str(payload.get("source_id") or (source_ids[0] if source_ids else ""))
        target_type = str(payload.get("target_type") or source_type)
        target_id = str(payload.get("target_id") or (source_ids[1] if len(source_ids) > 1 else ""))
        if source_id and self.source(user_id, source_type, source_id) is None:
            raise ReviewDataError("connection source does not exist for this user")
        if target_id and self.source(user_id, target_type, target_id) is None:
            raise ReviewDataError("connection target does not exist for this user")
        if source_id and target_id and source_type == target_type and source_id == target_id:
            raise ReviewDataError("connection endpoints must be different")
        source_refs = [
            {"type": endpoint_type, "id": endpoint_id}
            for endpoint_type, endpoint_id in (
                (source_type, source_id),
                (target_type, target_id),
            )
            if endpoint_id
        ]
        connection_id = self.new_id("rcn")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_connections (
                    id, user_id, period_type, period_key, connection_type,
                    source_type, source_id, target_type, target_id, direction,
                    title, description, source_ids_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id, user_id, str(payload.get("period_type") or "weekly"),
                    str(payload.get("period_key") or ""),
                    str(payload.get("connection_type") or "direct"),
                    source_type, source_id, target_type, target_id,
                    str(payload.get("direction") or "forward"),
                    str(payload.get("title") or ""), str(payload.get("description") or ""),
                    self.dump(source_refs),
                    str(payload.get("status") or "active"), now, now,
                ),
            )
        return self.get_connection(user_id, connection_id) or {}

    def get_connection(self, user_id: str, connection_id: str) -> dict[str, Any] | None:
        return self._fetch_owned("review_connections", user_id, connection_id)

    def list_connections(
        self, user_id: str, *, period_type: str | None = None, period_key: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if period_type:
            clauses.append("period_type = ?")
            params.append(period_type)
        if period_key:
            clauses.append("period_key = ?")
            params.append(period_key)
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM review_connections WHERE {' AND '.join(clauses)} "
                "ORDER BY updated_at DESC",
                params,
            )
            return self._rows(cursor.fetchall())

    def update_connection(self, user_id: str, connection_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        current = self.get_connection(user_id, connection_id)
        if current is None:
            return None
        source_type = str(payload.get("source_type", current.get("source_type") or "daily"))
        source_id = str(payload.get("source_id", current.get("source_id") or ""))
        target_type = str(payload.get("target_type", current.get("target_type") or source_type))
        target_id = str(payload.get("target_id", current.get("target_id") or ""))
        if source_id and self.source(user_id, source_type, source_id) is None:
            raise ReviewDataError("connection source does not exist for this user")
        if target_id and self.source(user_id, target_type, target_id) is None:
            raise ReviewDataError("connection target does not exist for this user")
        if source_id and target_id and source_type == target_type and source_id == target_id:
            raise ReviewDataError("connection endpoints must be different")
        clean = dict(payload)
        if any(key in clean for key in ("source_type", "source_id", "target_type", "target_id")):
            clean["source_ids"] = [
                {"type": endpoint_type, "id": endpoint_id}
                for endpoint_type, endpoint_id in (
                    (source_type, source_id),
                    (target_type, target_id),
                )
                if endpoint_id
            ]
        return self._patch_record(
            "review_connections", user_id, connection_id, clean,
            scalar_fields=(
                "period_type", "period_key", "connection_type", "source_type",
                "source_id", "target_type", "target_id", "direction", "title",
                "description", "status",
            ),
            json_fields={"source_ids": "source_ids_json"},
        )

    def delete_connection(self, user_id: str, connection_id: str) -> bool:
        return self._delete_record("review_connections", user_id, connection_id)

    def evidence_overview(self, user_id: str) -> dict[str, Any]:
        """Return deterministic evidence readiness without model-assigned confidence."""

        with self._cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*), MIN(review_date), MAX(review_date) "
                "FROM review_daily_events WHERE user_id = ?",
                (user_id,),
            )
            daily_row = cursor.fetchone()
            daily_count = daily_row[0]
            first_date = daily_row[1]
            last_date = daily_row[2]
            cursor.execute(
                "SELECT COUNT(*) FROM review_weekly_reviews WHERE user_id = ?",
                (user_id,),
            )
            weekly_count = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM review_monthly_reviews WHERE user_id = ?",
                (user_id,),
            )
            monthly_count = cursor.fetchone()[0]
        span_days = 0
        if first_date and last_date:
            span_days = (date.fromisoformat(str(last_date)) - date.fromisoformat(str(first_date))).days + 1
        max_level = 0
        if daily_count:
            max_level = 3
        if daily_count >= 8 and weekly_count >= 3 and span_days >= 21:
            max_level = 6
        if daily_count >= 20 and monthly_count >= 3 and span_days >= 84:
            max_level = 8
        suitable = []
        if max_level >= 3:
            suitable.append("branch")
        if max_level >= 6:
            suitable.append("trunk")
        if max_level >= 8:
            suitable.append("root")
        next_tier = "branch" if max_level < 3 else "trunk" if max_level < 6 else "root" if max_level < 8 else None
        return {
            "daily_events": int(daily_count),
            "weekly_reviews": int(weekly_count),
            "monthly_reviews": int(monthly_count),
            "first_date": str(first_date) if first_date else None,
            "last_date": str(last_date) if last_date else None,
            "span_days": span_days,
            "max_level": max_level,
            "suitable_tiers": suitable,
            "next_tier": next_tier,
        }

    def create_experiment(self, user_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        experiment_id = self.new_id("exp")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_action_experiments (
                    id, user_id, period_key, title, why_text, what_text, who_text,
                    when_text, where_text, how_text, resources, budget, success_signal,
                    desire_check, control_check, first_step, review_date, result,
                    executed, insight_result, next_decision, source_ids_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    user_id,
                    str(payload.get("period_key") or ""),
                    str(payload.get("title") or ""),
                    str(payload.get("why") or ""),
                    str(payload.get("what") or ""),
                    str(payload.get("who") or ""),
                    str(payload.get("when") or ""),
                    str(payload.get("where") or ""),
                    str(payload.get("how") or ""),
                    str(payload.get("resources") or ""),
                    str(payload.get("budget") or ""),
                    str(payload.get("success_signal") or ""),
                    str(payload.get("desire_check") or ""),
                    str(payload.get("control_check") or ""),
                    str(payload.get("first_step") or ""),
                    str(payload["review_date"]) if payload.get("review_date") else None,
                    str(payload.get("result") or ""),
                    str(payload.get("executed") or ""),
                    str(payload.get("insight_result") or ""),
                    str(payload.get("next_decision") or ""),
                    self.dump(payload.get("source_ids") or []),
                    str(payload.get("status") or "planned"), now, now,
                ),
            )
        return self.get_experiment(user_id, experiment_id) or {}

    def get_experiment(self, user_id: str, experiment_id: str) -> dict[str, Any] | None:
        item = self._fetch_owned("review_action_experiments", user_id, experiment_id)
        if item:
            for public, stored in (("why", "why_text"), ("what", "what_text"), ("who", "who_text"), ("when", "when_text"), ("where", "where_text"), ("how", "how_text")):
                item[public] = item.pop(stored)
        return item

    def list_experiments(self, user_id: str, *, period_key: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if period_key:
            clauses.append("period_key = ?")
            params.append(period_key)
        if status:
            clauses.append("status = ?")
            params.append(status)
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM review_action_experiments WHERE {' AND '.join(clauses)} "
                "ORDER BY COALESCE(review_date, '9999-12-31'), updated_at DESC",
                params,
            )
            raw = self._rows(cursor.fetchall())
        items = []
        for item in raw:
            for public, stored in (("why", "why_text"), ("what", "what_text"), ("who", "who_text"), ("when", "when_text"), ("where", "where_text"), ("how", "how_text")):
                item[public] = item.pop(stored)
            items.append(item)
        return items

    def update_experiment(self, user_id: str, experiment_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        mapped = dict(payload)
        for public, stored in (("why", "why_text"), ("what", "what_text"), ("who", "who_text"), ("when", "when_text"), ("where", "where_text"), ("how", "how_text")):
            if public in mapped:
                mapped[stored] = mapped.pop(public)
        item = self._patch_record(
            "review_action_experiments", user_id, experiment_id, mapped,
            scalar_fields=(
                "period_key", "title", "why_text", "what_text", "who_text",
                "when_text", "where_text", "how_text", "resources", "budget",
                "success_signal", "desire_check", "control_check", "first_step",
                "review_date", "result", "executed", "insight_result",
                "next_decision", "status",
            ),
            json_fields={"source_ids": "source_ids_json"},
        )
        return self.get_experiment(user_id, experiment_id) if item else None

    def delete_experiment(self, user_id: str, experiment_id: str) -> bool:
        return self._delete_record("review_action_experiments", user_id, experiment_id)

    def create_insight(self, user_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        insight_id = self.new_id("ins")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_insights (
                    id, user_id, tier, level, category, statement, evidence_json,
                    counter_evidence_json, evidence_span_json,
                    evidence_strength_json, uncertainty, uncertainty_note,
                    verification_experiment, verification_experiment_id,
                    source_ids_json, ai_candidate_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insight_id, user_id, str(payload.get("tier") or "branch"),
                    int(payload.get("level") or 1), str(payload.get("category") or ""),
                    str(payload.get("statement") or ""),
                    self.dump(payload.get("evidence") or []),
                    self.dump(payload.get("counter_evidence") or []),
                    self.dump(payload.get("evidence_span") or {}),
                    self.dump(payload.get("evidence_strength") or {}),
                    float(payload.get("uncertainty", 0.5)),
                    str(payload.get("uncertainty_note") or ""),
                    str(payload.get("verification_experiment") or ""),
                    payload.get("verification_experiment_id"),
                    self.dump(payload.get("source_ids") or []),
                    payload.get("ai_candidate_id"), str(payload.get("status") or "candidate"),
                    now, now,
                ),
            )
        return self.get_insight(user_id, insight_id) or {}

    def get_insight(self, user_id: str, insight_id: str) -> dict[str, Any] | None:
        return self._fetch_owned("review_insights", user_id, insight_id)

    def list_insights(self, user_id: str, *, tier: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if tier:
            clauses.append("tier = ?")
            params.append(tier)
        if status:
            clauses.append("status = ?")
            params.append(status)
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM review_insights WHERE {' AND '.join(clauses)} "
                "ORDER BY level ASC, updated_at DESC",
                params,
            )
            return self._rows(cursor.fetchall())

    def update_insight(self, user_id: str, insight_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        return self._patch_record(
            "review_insights", user_id, insight_id, payload,
            scalar_fields=(
                "tier", "level", "category", "statement", "uncertainty",
                "uncertainty_note", "verification_experiment",
                "verification_experiment_id", "ai_candidate_id", "status",
            ),
            json_fields={
                "evidence": "evidence_json",
                "counter_evidence": "counter_evidence_json",
                "evidence_span": "evidence_span_json",
                "evidence_strength": "evidence_strength_json",
                "source_ids": "source_ids_json",
            },
        )

    def create_ai_candidates(
        self,
        user_id: str,
        analysis_type: str,
        purpose: str,
        scope: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        model: str,
    ) -> list[dict[str, Any]]:
        now = self.now()
        ids: list[str] = []
        with self._cursor() as cursor:
            for candidate in candidates:
                candidate_id = self.new_id("aic")
                ids.append(candidate_id)
                cursor.execute(
                    """
                    INSERT INTO review_ai_candidates (
                        id, user_id, analysis_type, purpose, scope_json,
                        candidate_json, model, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?)
                    """,
                    (
                        candidate_id, user_id, analysis_type, purpose,
                        self.dump(scope), self.dump(candidate), model, now, now,
                    ),
                )
        return [item for candidate_id in ids if (item := self.get_ai_candidate(user_id, candidate_id))]

    def get_ai_candidate(self, user_id: str, candidate_id: str) -> dict[str, Any] | None:
        return self._fetch_owned("review_ai_candidates", user_id, candidate_id)

    def list_ai_candidates(
        self,
        user_id: str,
        *,
        analysis_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if analysis_type:
            clauses.append("analysis_type = ?")
            params.append(analysis_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(self._bounded_limit(limit))
        with self._cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM review_ai_candidates WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            )
            return self._rows(cursor.fetchall())

    def confirm_ai_candidate(
        self, user_id: str, candidate_id: str, content: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE review_ai_candidates
                SET confirmed_content_json = ?, status = 'confirmed',
                    confirmed_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'candidate'
                """,
                (self.dump(dict(content)), now, now, candidate_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_ai_candidate(user_id, candidate_id)

    def dismiss_ai_candidate(self, user_id: str, candidate_id: str) -> dict[str, Any] | None:
        return self._patch_record(
            "review_ai_candidates", user_id, candidate_id, {"status": "dismissed"},
            scalar_fields=("status",), json_fields={},
        )

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM review_preferences WHERE user_id = ?", (user_id,))
            item = self._row(cursor.fetchone())
        return item or {"user_id": user_id, "newbie_mode": True, "week_start_day": 0, "obsidian_root": "复盘", "updated_at": None}

    def save_preferences(self, user_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        current = self.get_preferences(user_id)
        newbie_mode = bool(payload.get("newbie_mode", current["newbie_mode"]))
        week_start_day = int(payload.get("week_start_day", current["week_start_day"]))
        if week_start_day not in range(7):
            raise ReviewDataError("week_start_day must be between 0 and 6")
        obsidian_root = str(payload.get("obsidian_root", current["obsidian_root"]) or "复盘").strip()
        if not obsidian_root:
            raise ReviewDataError("obsidian_root is required")
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_preferences (user_id, newbie_mode, week_start_day, obsidian_root, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    newbie_mode = excluded.newbie_mode,
                    week_start_day = excluded.week_start_day,
                    obsidian_root = excluded.obsidian_root,
                    updated_at = excluded.updated_at
                """,
                (user_id, int(newbie_mode), week_start_day, obsidian_root, now),
            )
        return self.get_preferences(user_id)

    def save_sync_state(
        self,
        user_id: str,
        record_type: str,
        record_id: str,
        *,
        status: str,
        relative_path: str | None = None,
        content_hash: str | None = None,
        error_message: str | None = None,
        synced_at: str | None = None,
    ) -> dict[str, Any]:
        now = self.now()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_sync_state (
                    user_id, record_type, record_id, relative_path, content_hash,
                    status, error_message, synced_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, record_type, record_id) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    content_hash = excluded.content_hash,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    synced_at = excluded.synced_at,
                    updated_at = excluded.updated_at
                """,
                (user_id, record_type, record_id, relative_path, content_hash, status, error_message, synced_at, now),
            )
        return self.get_sync_state(user_id, record_type, record_id) or {}

    def get_sync_state(self, user_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM review_sync_state WHERE user_id = ? AND record_type = ? AND record_id = ?",
                (user_id, record_type, record_id),
            )
            return self._row(cursor.fetchone())

    def list_sync_states(self, user_id: str, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM review_sync_state WHERE user_id = ?"
        params: list[Any] = [user_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(self._bounded_limit(limit))
        with self._cursor() as cursor:
            cursor.execute(query, params)
            return self._rows(cursor.fetchall())

    def source(self, user_id: str, source_type: str, source_id: str) -> dict[str, Any] | None:
        getters = {
            "daily": self.get_daily_event,
            "connection": self.get_connection,
            "experiment": self.get_experiment,
            "insight": self.get_insight,
            "ai_candidate": self.get_ai_candidate,
        }
        if source_type in getters:
            return getters[source_type](user_id, source_id)
        table = {
            "weekly": "review_weekly_reviews",
            "monthly": "review_monthly_reviews",
            "annual": "review_annual_reviews",
        }.get(source_type)
        return self._fetch_owned(table, user_id, source_id) if table else None

    def search(
        self,
        user_id: str,
        *,
        keyword: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        record_types: Iterable[str] = (),
        meaning_type: str | None = None,
        emotion: str | None = None,
        insight_tier: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        selected = set(record_types) or {"daily", "weekly", "monthly", "annual", "insight", "experiment"}
        needle = keyword.strip().casefold()
        results: list[dict[str, Any]] = []
        if "daily" in selected:
            for item in self.list_daily_events(user_id, start_date=start_date, end_date=end_date, limit=500):
                haystack = self.dump(item).casefold()
                if needle and needle not in haystack:
                    continue
                if meaning_type and meaning_type not in (
                    item.get("meaning_types") or [item.get("meaning_type")]
                ):
                    continue
                if emotion and emotion.casefold() not in self.dump(item.get("emotions")).casefold():
                    continue
                if status and item.get("status") != status:
                    continue
                results.append({"record_type": "daily", **item})
        loaders = {
            "weekly": lambda: self.list_weekly(user_id, limit=100),
            "monthly": lambda: self.list_monthly(user_id, limit=100),
            "annual": lambda: [item for year in range(datetime.now().year, datetime.now().year - 20, -1) if (item := self.get_annual(user_id, str(year)))],
            "insight": lambda: self.list_insights(user_id, tier=insight_tier, status=status),
            "experiment": lambda: self.list_experiments(user_id, status=status),
        }
        for record_type, loader in loaders.items():
            if record_type not in selected:
                continue
            for item in loader():
                if needle and needle not in self.dump(item).casefold():
                    continue
                if status and item.get("status") != status:
                    continue
                period_key = str(
                    item.get("review_date")
                    or item.get("week_start")
                    or (f"{item.get('month_key')}-01" if item.get("month_key") else "")
                    or (f"{item.get('year_key')}-01-01" if item.get("year_key") else "")
                    or item.get("period_key")
                    or str(item.get("updated_at") or "")[:10]
                )
                if start_date and period_key and period_key < start_date:
                    continue
                if end_date and period_key and period_key > end_date:
                    continue
                results.append({"record_type": record_type, **item})
        results.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return results[: self._bounded_limit(limit)]

    def _patch_record(
        self,
        table: str,
        user_id: str,
        record_id: str,
        payload: Mapping[str, Any],
        *,
        scalar_fields: Iterable[str],
        json_fields: Mapping[str, str],
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []
        for field in scalar_fields:
            if field in payload:
                updates.append(f"{field} = ?")
                params.append(payload[field])
        for public, column in json_fields.items():
            if public in payload:
                updates.append(f"{column} = ?")
                params.append(self.dump(payload[public] if payload[public] is not None else []))
        if not updates:
            return self._fetch_owned(table, user_id, record_id)
        updates.append("updated_at = ?")
        params.extend([self.now(), record_id, user_id])
        with self._cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self._fetch_owned(table, user_id, record_id)

    def _delete_record(self, table: str, user_id: str, record_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE id = ? AND user_id = ?", (record_id, user_id))
            return cursor.rowcount > 0
