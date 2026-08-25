"""Process-wide persistence database selection."""

from __future__ import annotations

import os
import threading

from ..transcriber.control_database import PostgresControlDatabase
from .schema import migrate_postgres_schema


_UNSET = object()
_database: PostgresControlDatabase | None | object = _UNSET
_database_lock = threading.Lock()


def get_persistence_database() -> PostgresControlDatabase | None:
    """Return the migrated PostgreSQL pool or ``None`` for SQLite mode."""

    global _database
    with _database_lock:
        if _database is not _UNSET:
            return _database
        backend = os.environ.get(
            "LEARNFLUX_PERSISTENCE_BACKEND", "sqlite"
        ).strip().lower()
        if backend == "sqlite":
            _database = None
            return None
        if backend != "postgres":
            raise RuntimeError(f"unsupported_persistence_backend:{backend}")
        dsn = os.environ.get("DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("database_url_required_for_postgres")
        database = PostgresControlDatabase(dsn, max_size=32)
        try:
            migrate_postgres_schema(database)
        except Exception:
            database.close()
            raise
        _database = database
        return database


def reset_persistence_database() -> None:
    """Close and clear the cached database; intended for tests and shutdown."""

    global _database
    with _database_lock:
        if isinstance(_database, PostgresControlDatabase):
            _database.close()
        _database = _UNSET
