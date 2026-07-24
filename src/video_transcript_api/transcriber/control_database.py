"""Small database ports for transcription control state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class SQLiteControlDatabase:
    """Create short SQLite connections with explicit transactional writes."""

    dialect = "sqlite"

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def close(self) -> None:
        """SQLite connections are short-lived and need no pool shutdown."""


class _PostgresConnection:
    def __init__(self, raw_connection, release) -> None:
        self._raw_connection = raw_connection
        self._release = release
        self._closed = False

    def execute(self, statement: str, parameters=()):
        normalized = statement.strip().upper()
        if normalized.startswith("PRAGMA"):
            return _NoopCursor()
        if normalized == "BEGIN IMMEDIATE":
            statement = "BEGIN"
        return self._raw_connection.execute(statement.replace("?", "%s"), parameters)

    @property
    def in_transaction(self) -> bool:
        return self._raw_connection.info.transaction_status.name != "IDLE"

    def commit(self) -> None:
        self._raw_connection.commit()

    def rollback(self) -> None:
        self._raw_connection.rollback()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._release(self._raw_connection)


class _NoopCursor:
    rowcount = 0

    @staticmethod
    def fetchone():
        return None

    @staticmethod
    def fetchall():
        return []


class PostgresControlDatabase:
    """Small pooled PostgreSQL adapter matching the control-store connection port."""

    dialect = "postgres"

    def __init__(self, dsn: str, *, max_size: int = 4) -> None:
        self.pool = ConnectionPool(
            conninfo=dsn,
            min_size=0,
            max_size=max_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=True,
        )

    def connect(self) -> _PostgresConnection:
        raw = self.pool.getconn()
        return _PostgresConnection(raw, self.pool.putconn)

    @contextmanager
    def transaction(self) -> Iterator[_PostgresConnection]:
        connection = self.connect()
        try:
            with connection._raw_connection.transaction():
                yield connection
        finally:
            connection.close()

    def close(self) -> None:
        self.pool.close()
