#!/usr/bin/env python3
"""Migrate all LearnFlux SQLite data and parsed artifacts to PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from video_transcript_api.persistence.schema import migrate_postgres_schema
from video_transcript_api.persistence.sqlite_migration import (
    default_sqlite_stores,
    migrate_sqlite_to_postgres,
    verify_sqlite_postgres_migration,
)
from video_transcript_api.transcriber.control_database import PostgresControlDatabase


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "strictly compare PostgreSQL with the SQLite source; run before "
            "allowing post-cutover writes"
        ),
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    data_dir = Path(args.data_dir)
    database = PostgresControlDatabase(args.database_url)
    try:
        if args.verify_only:
            migrate_postgres_schema(database)
        operation = (
            verify_sqlite_postgres_migration
            if args.verify_only
            else migrate_sqlite_to_postgres
        )
        report = operation(
            database,
            stores=default_sqlite_stores(data_dir),
            cache_root=data_dir / "cache",
        )
    finally:
        database.close()
    print(f"tables={len(report.table_rows)}")
    print(f"business_rows={sum(report.table_rows.values())}")
    print(f"artifact_rows={report.artifact_rows}")
    print(f"artifact_bytes={report.artifact_bytes}")
    print(f"artifact_manifest_sha256={report.artifact_manifest_sha256}")
    print("migration_status=verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
