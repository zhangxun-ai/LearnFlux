"""Immutable PostgreSQL SQL migration runner."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..transcriber.control_database import PostgresControlDatabase


_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    checksum: str
    sql: str


def load_postgres_migrations() -> list[SchemaMigration]:
    """Load checked-in migrations in deterministic version order."""

    migration_dir = Path(__file__).parent / "migrations" / "postgres"
    migrations: list[SchemaMigration] = []
    for path in sorted(migration_dir.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"invalid_migration_name:{path.name}")
        raw = path.read_bytes()
        migrations.append(
            SchemaMigration(
                version=int(match.group(1)),
                name=path.name,
                checksum=hashlib.sha256(raw).hexdigest(),
                sql=raw.decode("utf-8"),
            )
        )
    versions = [migration.version for migration in migrations]
    if versions != sorted(set(versions)):
        raise RuntimeError("duplicate_postgres_migration_version")
    return migrations


def migrate_postgres_schema(database: PostgresControlDatabase) -> list[str]:
    """Apply pending migrations atomically and verify immutable checksums."""

    applied_now: list[str] = []
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learnflux_schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            ("learnflux_schema_migrations",),
        )
        rows = connection.execute(
            "SELECT version, name, checksum FROM learnflux_schema_migrations"
        ).fetchall()
        applied = {int(row["version"]): row for row in rows}
        for migration in load_postgres_migrations():
            existing = applied.get(migration.version)
            if existing is not None:
                if (
                    existing["name"] != migration.name
                    or existing["checksum"] != migration.checksum
                ):
                    raise RuntimeError(
                        f"postgres_migration_checksum_mismatch:{migration.version}"
                    )
                continue
            connection.executescript(migration.sql)
            connection.execute(
                """
                INSERT INTO learnflux_schema_migrations(version, name, checksum)
                VALUES (?, ?, ?)
                """,
                (migration.version, migration.name, migration.checksum),
            )
            applied_now.append(migration.name)
    return applied_now
