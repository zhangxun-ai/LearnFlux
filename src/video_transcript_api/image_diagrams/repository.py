"""Private, versioned image-diagram jobs with conservative paid-call recovery."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..transcriber.control_database import SQLiteControlDatabase


_ACTIVE = ("queued", "planning", "generating", "reviewing")
_TERMINAL = ("succeeded", "failed", "unknown")
_JSON_FIELDS = ("request", "source", "plan", "review", "usage")
_UPDATE_FIELDS = {
    "status", "stage", "plan", "review", "usage", "image_key", "error_code",
    "submitted_at",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_diagram_jobs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    view_token TEXT NOT NULL,
    request_key TEXT NOT NULL UNIQUE,
    recipe_key TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    request_json TEXT NOT NULL,
    source_json TEXT NOT NULL,
    plan_json TEXT,
    review_json TEXT,
    usage_json TEXT,
    image_key TEXT,
    error_code TEXT,
    parent_id TEXT,
    generation_token TEXT NOT NULL DEFAULT '',
    submitted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_image_diagram_source_created
    ON image_diagram_jobs(owner_user_id, view_token, created_at);
CREATE INDEX IF NOT EXISTS idx_image_diagram_recipe
    ON image_diagram_jobs(owner_user_id, view_token, recipe_key, created_at);
CREATE INDEX IF NOT EXISTS idx_image_diagram_queue
    ON image_diagram_jobs(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_image_diagram_active_source
    ON image_diagram_jobs(owner_user_id, view_token)
    WHERE status IN ('queued', 'planning', 'generating', 'reviewing');
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class ImageDiagramRepository:
    """Persist private source snapshots, one active job per source and versions.

    Callers must authorize source ownership before returning any job payload to
    users. The repository intentionally retains source snapshots for workers;
    these must never be serialized directly into an HTTP response.
    """

    def __init__(self, db_path: str | Path | object):
        self.database = (
            db_path if hasattr(db_path, "transaction")
            else SQLiteControlDatabase(db_path)
        )
        self._is_postgres = getattr(self.database, "dialect", None) == "postgres"
        if not self._is_postgres:
            with self.database.transaction() as connection:
                connection.executescript(_SCHEMA)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _decode(row) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in _JSON_FIELDS:
            raw = result.pop(field + "_json", None)
            result[field] = json.loads(raw) if raw else None
        return result

    def close(self) -> None:
        """Connections are transaction-scoped; shared pools remain caller owned."""

    def create_or_get(
        self, *, owner_user_id: str, view_token: str, request_key: str,
        recipe_key: str, source_hash: str, request: dict, source: dict,
        parent_id: str | None = None, max_daily_generations: int | None = None,
        day_start: str | None = None,
    ) -> dict[str, Any]:
        """Deduplicate or enqueue, enforcing an optional atomic per-owner quota.

        Idempotency and active-job reuse happen before quota accounting. The
        conservative cap counts every persisted attempt in the Beijing day,
        including failed jobs, because even failed work may have incurred cost.
        """
        if not all(isinstance(value, str) and value.strip() for value in (
            owner_user_id, view_token, request_key, recipe_key, source_hash,
        )):
            raise ValueError("invalid_image_diagram_identity")
        if max_daily_generations is not None and (
            isinstance(max_daily_generations, bool)
            or not isinstance(max_daily_generations, int)
            or max_daily_generations < 0
        ):
            raise ValueError("invalid_image_diagram_daily_limit")
        if max_daily_generations is not None:
            if day_start is None:
                start = datetime.now(ZoneInfo("Asia/Shanghai")).replace(
                    hour=0, minute=0, second=0, microsecond=0,
                )
            else:
                try:
                    start = _instant(day_start)
                except (TypeError, ValueError):
                    raise ValueError("invalid_image_diagram_day_start") from None
            day_start = start.astimezone(timezone.utc).isoformat(timespec="microseconds")
        job_id, now = uuid.uuid4().hex, self._now()

        def validate_existing(row) -> dict[str, Any]:
            record = self._decode(row)
            if (
                record["owner_user_id"] != owner_user_id
                or record["view_token"] != view_token
                or record["recipe_key"] != recipe_key
                or record["source_hash"] != source_hash
                or record["request"] != request
                or record["parent_id"] != parent_id
            ):
                raise ValueError("image_diagram_request_key_conflict")
            return record

        with self.database.transaction() as connection:
            if self._is_postgres:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(?))",
                    ("image_diagram_owner:" + owner_user_id,),
                )
            existing = connection.execute(
                "SELECT * FROM image_diagram_jobs WHERE request_key = ?", (request_key,),
            ).fetchone()
            if existing is not None:
                return validate_existing(existing)
            if parent_id:
                parent = connection.execute(
                    "SELECT owner_user_id, view_token FROM image_diagram_jobs WHERE id = ?",
                    (parent_id,),
                ).fetchone()
                if not parent or parent["owner_user_id"] != owner_user_id or parent["view_token"] != view_token:
                    raise ValueError("invalid_image_diagram_parent")
            active = connection.execute(
                """SELECT * FROM image_diagram_jobs
                   WHERE owner_user_id = ? AND view_token = ?
                     AND status IN ('queued', 'planning', 'generating', 'reviewing')
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (owner_user_id, view_token),
            ).fetchone()
            if active is not None:
                return self._decode(active)
            if max_daily_generations is not None:
                attempted = connection.execute(
                    """SELECT COUNT(*) FROM image_diagram_jobs
                       WHERE owner_user_id = ? AND created_at >= ?""",
                    (owner_user_id, day_start),
                ).fetchone()[0]
                if attempted >= max_daily_generations:
                    raise ValueError("image_diagram_daily_limit")
            connection.execute(
                """
                INSERT OR IGNORE INTO image_diagram_jobs (
                    id, owner_user_id, view_token, request_key, recipe_key,
                    source_hash, status, stage, request_json, source_json,
                    parent_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'queued', ?, ?, ?, ?, ?)
                """,
                (job_id, owner_user_id, view_token, request_key, recipe_key,
                 source_hash, _json(request), _json(source), parent_id, now, now),
            )
            row = connection.execute(
                "SELECT * FROM image_diagram_jobs WHERE request_key = ?", (request_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("image_diagram_job_not_created")
            return validate_existing(row)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM image_diagram_jobs WHERE id = ?", (job_id,),
            ).fetchone()
        return self._decode(row)

    def get_identity(self, job_id: str) -> dict[str, str] | None:
        """Read only identity metadata so callers can authorize before text access."""
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id, owner_user_id, view_token FROM image_diagram_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_by_request_key(self, request_key: str) -> dict[str, Any] | None:
        """Read a private existing attempt after its source has been authorized.

        Unlike recipe reuse, explicit idempotent retries retain failed and
        unknown outcomes. Callers must never use this method as authorization.
        """
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM image_diagram_jobs WHERE request_key = ?",
                (request_key,),
            ).fetchone()
        return self._decode(row)

    def list_for_source(
        self, owner_user_id: str, view_token: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """SELECT * FROM image_diagram_jobs
                   WHERE owner_user_id = ? AND view_token = ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (owner_user_id, view_token, max(1, min(int(limit), 200))),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def find_reusable(
        self, owner_user_id: str, view_token: str, recipe_key: str,
    ) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT * FROM image_diagram_jobs
                   WHERE owner_user_id = ? AND view_token = ? AND recipe_key = ?
                     AND status IN ('queued', 'planning', 'generating', 'reviewing', 'succeeded', 'unknown')
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (owner_user_id, view_token, recipe_key),
            ).fetchone()
        return self._decode(row)

    def claim_next(self, metadata_only: bool = False) -> dict[str, Any] | None:
        """Claim queued work once, optionally without loading private snapshots.

        Workers should claim metadata, authorize that identity, then load the
        full job. The default full record remains available to internal callers.
        """
        lock = " FOR UPDATE SKIP LOCKED" if self._is_postgres else ""
        projection = (
            "id, owner_user_id, view_token, status, stage, generation_token, "
            "submitted_at, parent_id, created_at, updated_at"
            if metadata_only else "*"
        )
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT " + projection + " FROM image_diagram_jobs WHERE status = 'queued' "
                + "ORDER BY created_at, id LIMIT 1" + lock,
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            result = connection.execute(
                """UPDATE image_diagram_jobs
                   SET status = 'planning', stage = 'planning', generation_token = ?, updated_at = ?
                   WHERE id = ? AND status = 'queued'""",
                (token, self._now(), row["id"]),
            )
            if result.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT " + projection + " FROM image_diagram_jobs WHERE id = ?",
                (row["id"],),
            ).fetchone()
            return dict(row) if metadata_only else self._decode(row)

    def heartbeat(self, job_id: str, generation_token: str) -> bool:
        """Keep slow authorized work alive without reading any private snapshot."""
        with self.database.transaction() as connection:
            result = connection.execute(
                """UPDATE image_diagram_jobs SET updated_at = ?
                   WHERE id = ? AND generation_token = ?
                     AND status IN ('planning', 'generating', 'reviewing')""",
                (self._now(), job_id, generation_token),
            )
            return result.rowcount == 1

    def update(self, job_id: str, generation_token: str, **fields) -> bool:
        """Update active work only while its generation token still matches.

        Entering ``generating`` marks the paid-request submission boundary even
        if the caller omits ``submitted_at``. A recovered or finished worker can
        never overwrite a later result.
        """
        if not fields or not set(fields).issubset(_UPDATE_FIELDS):
            raise ValueError("invalid_image_diagram_update_fields")
        if "status" in fields and fields["status"] not in (*_ACTIVE, *_TERMINAL):
            raise ValueError("invalid_image_diagram_status")
        if not generation_token:
            return False
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status, generation_token, submitted_at, image_key FROM image_diagram_jobs WHERE id = ?", (job_id,),
            ).fetchone()
            if row is None or row["generation_token"] != generation_token or row["status"] not in _ACTIVE:
                return False
            if fields.get("status") == "queued":
                raise ValueError("worker_cannot_requeue_image_diagram")
            if row["submitted_at"] and fields.get("submitted_at", row["submitted_at"]) != row["submitted_at"]:
                raise ValueError("image_submission_boundary_is_immutable")
            if fields.get("status") == "generating" and not row["submitted_at"]:
                fields["submitted_at"] = fields.get("submitted_at") or self._now()
            image_key = fields.get("image_key", row["image_key"])
            if fields.get("status") in {"reviewing", "succeeded"} and not image_key:
                raise ValueError("image_diagram_image_required")
            assignments, parameters = [], []
            for name, value in fields.items():
                column = name + "_json" if name in _JSON_FIELDS else name
                assignments.append(column + " = ?")
                parameters.append(_json(value) if name in _JSON_FIELDS else value)
            assignments.append("updated_at = ?")
            parameters.extend((self._now(), job_id, generation_token))
            result = connection.execute(
                "UPDATE image_diagram_jobs SET " + ", ".join(assignments)
                + " WHERE id = ? AND generation_token = ? AND status IN ('queued', 'planning', 'generating', 'reviewing')",
                parameters,
            )
            return result.rowcount == 1

    def recover_interrupted(self, stale_minutes: int = 20) -> int:
        """Recover unsubmitted work; never replay an uncertain image request."""
        if stale_minutes < 0:
            raise ValueError("invalid_image_diagram_stale_minutes")
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        count = 0
        with self.database.transaction() as connection:
            lock = " FOR UPDATE SKIP LOCKED" if self._is_postgres else ""
            rows = connection.execute(
                """SELECT id, status, image_key, submitted_at, generation_token, updated_at
                   FROM image_diagram_jobs
                   WHERE status IN ('planning', 'generating', 'reviewing')""" + lock,
            ).fetchall()
            for row in rows:
                legacy_saved = row["status"] == "reviewing" and bool(row["image_key"])
                try:
                    if not legacy_saved and _instant(row["updated_at"]) >= cutoff:
                        continue
                except (ValueError, TypeError):
                    # Corrupt timing cannot authorize another paid request.
                    if not row["submitted_at"] and row["status"] == "planning":
                        continue
                now = self._now()
                if row["image_key"]:
                    status, stage, error = "succeeded", "completed", None
                elif row["submitted_at"] or row["status"] in {"generating", "reviewing"}:
                    status, stage, error = "unknown", "unknown", "image_outcome_unknown"
                else:
                    status, stage, error = "queued", "queued", None
                result = connection.execute(
                    """UPDATE image_diagram_jobs
                       SET status = ?, stage = ?, error_code = ?,
                           generation_token = '', updated_at = ?
                       WHERE id = ? AND generation_token = ? AND updated_at = ?""",
                    (status, stage, error, now,
                     row["id"], row["generation_token"], row["updated_at"]),
                )
                count += int(result.rowcount == 1)
        return count
