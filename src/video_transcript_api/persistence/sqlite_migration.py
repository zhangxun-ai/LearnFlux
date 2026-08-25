"""Lossless transfer from the four legacy SQLite stores to PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from ..transcriber.control_database import PostgresControlDatabase
from .schema import migrate_postgres_schema


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

ARTIFACT_FILES = {
    "transcript_funasr.json": "transcript_funasr",
    "transcript_capswriter.txt": "transcript_capswriter",
    "transcript_capswriter.json": "transcript_capswriter_json",
    "transcript_zh.txt": "transcript_zh",
    "source_language.txt": "source_language",
    "llm_calibrated.txt": "llm_calibrated",
    "llm_summary.txt": "llm_summary",
    "llm_processed.json": "llm_processed",
    "comment_insight.txt": "comment_insight",
    "comment_samples.json": "comment_samples",
    "key_info.json": "key_info",
    "speaker_mapping.json": "speaker_mapping",
}


@dataclass(frozen=True)
class SQLiteStore:
    name: str
    path: Path


@dataclass(frozen=True)
class MigrationReport:
    table_rows: dict[str, int]
    artifact_rows: int
    artifact_bytes: int
    artifact_manifest_sha256: str


def default_sqlite_stores(data_dir: str | Path = "data") -> list[SQLiteStore]:
    root = Path(data_dir)
    candidates = [
        SQLiteStore("cache", root / "cache" / "cache.db"),
        SQLiteStore("audit", root / "audit.db"),
        SQLiteStore("flywheel", root / "flywheel" / "flywheel.db"),
        SQLiteStore("config", root / "config.db"),
    ]
    return [
        store
        for store in candidates
        if store.name == "cache" or store.path.is_file()
    ]


def _quote(identifier: str) -> str:
    if _IDENTIFIER.fullmatch(identifier) is None:
        raise RuntimeError(f"unsafe_sql_identifier:{identifier}")
    return f'"{identifier}"'


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro", uri=True, timeout=30
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _list_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY rowid
            """
        )
    ]


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quote(table)})")]


def _table_primary_key(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [str(row[1]) for row in sorted(rows, key=lambda row: row[5]) if row[5]]


def _ordered_tables(connections: dict[str, sqlite3.Connection]) -> tuple[list[str], dict[str, str]]:
    table_store: dict[str, str] = {}
    dependencies: dict[str, set[str]] = {}
    insertion_order: list[str] = []
    for store_name, connection in connections.items():
        for table in _list_tables(connection):
            if table in table_store:
                raise RuntimeError(f"duplicate_sqlite_table:{table}")
            table_store[table] = store_name
            insertion_order.append(table)
            dependencies[table] = {
                str(row[2])
                for row in connection.execute(
                    f"PRAGMA foreign_key_list({_quote(table)})"
                )
                if str(row[2]) != table
            }
    known = set(table_store)
    for table in dependencies:
        dependencies[table].intersection_update(known)
    ordered: list[str] = []
    pending = list(insertion_order)
    while pending:
        ready = [table for table in pending if dependencies[table].issubset(ordered)]
        if not ready:
            raise RuntimeError(f"cyclic_sqlite_foreign_keys:{','.join(pending)}")
        for table in ready:
            ordered.append(table)
            pending.remove(table)
    return ordered, table_store


def _ensure_empty_target(connection, tables: Iterable[str]) -> None:
    nonempty: list[str] = []
    for table in tables:
        count = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
        if count:
            nonempty.append(f"{table}={count}")
    artifact_count = connection.execute(
        "SELECT COUNT(*) FROM transcription_artifacts"
    ).fetchone()[0]
    if artifact_count:
        nonempty.append(f"transcription_artifacts={artifact_count}")
    if nonempty:
        raise RuntimeError("postgres_target_not_empty:" + ",".join(nonempty))


def _chunks(rows: list[tuple[Any, ...]], size: int = 500):
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


def _artifact_manifest(
    cache_connection: sqlite3.Connection, cache_root: Path
) -> list[tuple[int, str, str, bytes, str, int]]:
    manifest: list[tuple[int, str, str, bytes, str, int]] = []
    rows = cache_connection.execute(
        "SELECT id, files_loc FROM video_cache ORDER BY id"
    ).fetchall()
    for row in rows:
        cache_id = int(row["id"])
        artifact_dir = cache_root / str(row["files_loc"])
        for original_name, artifact_type in ARTIFACT_FILES.items():
            path = artifact_dir / original_name
            if not path.is_file():
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            manifest.append(
                (cache_id, artifact_type, original_name, content, digest, len(content))
            )
    return manifest


def _manifest_digest(manifest: Iterable[tuple[int, str, str, bytes, str, int]]) -> str:
    canonical = "\n".join(
        f"{cache_id}:{artifact_type}:{original_name}:{digest}:{size}"
        for cache_id, artifact_type, original_name, _content, digest, size in manifest
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def migrate_sqlite_to_postgres(
    database: PostgresControlDatabase,
    *,
    stores: list[SQLiteStore],
    cache_root: str | Path,
) -> MigrationReport:
    """Copy all business rows and whitelisted parsed artifacts into an empty target."""

    migrate_postgres_schema(database)
    connections = {store.name: _connect_readonly(store.path) for store in stores}
    try:
        ordered_tables, table_store = _ordered_tables(connections)
        cache_connection = connections.get("cache")
        if cache_connection is None:
            raise RuntimeError("cache_sqlite_store_required")
        manifest = _artifact_manifest(cache_connection, Path(cache_root))
        table_rows: dict[str, int] = {}
        with database.transaction() as target:
            _ensure_empty_target(target, ordered_tables)
            for table in ordered_tables:
                source = connections[table_store[table]]
                columns = _table_columns(source, table)
                rows = [tuple(row) for row in source.execute(f"SELECT * FROM {_quote(table)}")]
                table_rows[table] = len(rows)
                if not rows:
                    continue
                placeholders = ", ".join("?" for _ in columns)
                statement = (
                    f"INSERT INTO {_quote(table)} "
                    f"({', '.join(_quote(column) for column in columns)}) "
                    f"VALUES ({placeholders})"
                )
                for batch in _chunks(rows):
                    target.executemany(statement, batch)
            if manifest:
                target.executemany(
                    """
                    INSERT INTO transcription_artifacts(
                        cache_id, artifact_type, original_name, content,
                        content_sha256, byte_size
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    manifest,
                )
            _reset_identity_sequences(target)
        report = verify_sqlite_postgres_migration(
            database,
            stores=stores,
            cache_root=cache_root,
        )
        if report.table_rows != table_rows:
            raise RuntimeError("migration_verification_row_counts_changed")
        return report
    finally:
        for connection in connections.values():
            connection.close()


def _reset_identity_sequences(connection) -> None:
    rows = connection.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND is_identity = 'YES'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()
    for row in rows:
        table = str(row["table_name"])
        column = str(row["column_name"])
        maximum = connection.execute(
            f"SELECT MAX({_quote(column)}) FROM {_quote(table)}"
        ).fetchone()[0]
        sequence = connection.execute(
            "SELECT pg_get_serial_sequence(?, ?)", (table, column)
        ).fetchone()[0]
        if maximum is None:
            connection.execute("SELECT setval(?::regclass, 1, FALSE)", (sequence,))
        else:
            connection.execute(
                "SELECT setval(?::regclass, ?, TRUE)", (sequence, int(maximum))
            )


def _normalize(value: Any, *, timestamp: bool = False) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if timestamp and isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=None).isoformat(
                    sep=" ", timespec="microseconds"
                )
            except ValueError:
                return value
        return value
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(
            sep=" ", timespec="microseconds"
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, memoryview):
        return bytes(value).hex()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _row_digest(rows: Iterable[Iterable[Any]], timestamp_indexes: set[int]) -> str:
    canonical = [
        json.dumps(
            [
                _normalize(value, timestamp=index in timestamp_indexes)
                for index, value in enumerate(row)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for row in rows
    ]
    canonical.sort()
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()


def verify_sqlite_postgres_migration(
    database: PostgresControlDatabase,
    *,
    stores: list[SQLiteStore],
    cache_root: str | Path,
) -> MigrationReport:
    """Verify row content, primary keys, and every artifact byte hash."""

    connections = {store.name: _connect_readonly(store.path) for store in stores}
    try:
        ordered_tables, table_store = _ordered_tables(connections)
        table_rows: dict[str, int] = {}
        target = database.connect()
        try:
            for table in ordered_tables:
                source = connections[table_store[table]]
                columns = _table_columns(source, table)
                source_rows = source.execute(f"SELECT * FROM {_quote(table)}").fetchall()
                raw_target_rows = target.execute(
                    f"SELECT * FROM {_quote(table)}"
                ).fetchall()
                target_rows = [
                    tuple(row[column] for column in columns) for row in raw_target_rows
                ]
                table_rows[table] = len(source_rows)
                if len(source_rows) != len(target_rows):
                    raise RuntimeError(
                        f"migration_row_count_mismatch:{table}:"
                        f"sqlite={len(source_rows)}:postgres={len(target_rows)}"
                    )
                timestamp_names = {
                    str(row["column_name"])
                    for row in target.execute(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = ?
                          AND data_type IN (
                              'timestamp without time zone',
                              'timestamp with time zone'
                          )
                        """,
                        (table,),
                    ).fetchall()
                }
                timestamp_indexes = {
                    index for index, column in enumerate(columns) if column in timestamp_names
                }
                if _row_digest(source_rows, timestamp_indexes) != _row_digest(
                    target_rows, timestamp_indexes
                ):
                    primary_key = _table_primary_key(source, table)
                    detail = ",".join(primary_key) if primary_key else "no_primary_key"
                    raise RuntimeError(f"migration_row_digest_mismatch:{table}:{detail}")
            cache_connection = connections.get("cache")
            if cache_connection is None:
                raise RuntimeError("cache_sqlite_store_required")
            source_manifest = _artifact_manifest(cache_connection, Path(cache_root))
            target_rows = target.execute(
                """
                SELECT cache_id, artifact_type, original_name, content,
                       content_sha256, byte_size
                FROM transcription_artifacts
                ORDER BY cache_id, artifact_type
                """
            ).fetchall()
            target_manifest = [
                tuple(
                    row[column]
                    for column in (
                        "cache_id",
                        "artifact_type",
                        "original_name",
                        "content",
                        "content_sha256",
                        "byte_size",
                    )
                )
                for row in target_rows
            ]
            expected = {
                (row[0], row[1]): (row[2], row[4], row[5]) for row in source_manifest
            }
            actual = {
                (int(row[0]), str(row[1])): (
                    str(row[2]),
                    hashlib.sha256(bytes(row[3])).hexdigest(),
                    int(row[5]),
                )
                for row in target_manifest
            }
            if expected != actual:
                raise RuntimeError("migration_artifact_manifest_mismatch")
            manifest_sha = _manifest_digest(source_manifest)
            return MigrationReport(
                table_rows=table_rows,
                artifact_rows=len(source_manifest),
                artifact_bytes=sum(row[5] for row in source_manifest),
                artifact_manifest_sha256=manifest_sha,
            )
        finally:
            target.close()
    finally:
        for connection in connections.values():
            connection.close()
