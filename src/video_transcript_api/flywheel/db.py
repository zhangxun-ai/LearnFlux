"""SQLite connection + schema for the flywheel feature.

Mirrors ``cache_manager``'s pattern: thread-local connections, WAL mode, and a
``cursor()`` context manager that commits / rolls back. New tables only; it does
not touch the transcription cache DB. The DB lives behind repository interfaces
(see ``repositories.py``) so it can be swapped for Supabase later.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from ..utils.logging import setup_logger

logger = setup_logger("flywheel_db")


class FlywheelDB:
    """Owns the sqlite connection + schema. Cheap to construct; idempotent init."""

    def __init__(self, db_path: str | object = "./data/flywheel/flywheel.db"):
        self.database = db_path if hasattr(db_path, "transaction") else None
        self._is_postgres = getattr(self.database, "dialect", None) == "postgres"
        raw_path = getattr(db_path, "path", None) if self.database else db_path
        self.db_path = Path(raw_path) if raw_path else None
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _connection(self) -> sqlite3.Connection:
        if self._is_postgres:
            raise RuntimeError("postgres_connections_must_be_scoped")
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
            except sqlite3.OperationalError:
                logger.warning("WAL/foreign_keys not supported, using defaults")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def cursor(self):
        if self._is_postgres:
            with self.database.transaction() as conn:
                cur = conn.cursor()
                try:
                    yield cur
                finally:
                    cur.close()
            return
        conn = self._connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception as e:  # noqa: BLE001 - logged then re-raised
            conn.rollback()
            logger.error(f"flywheel db error: {e}")
            raise
        finally:
            cur.close()

    def _init_schema(self):
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS blogger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    platform_user_id TEXT NOT NULL,
                    handle TEXT NOT NULL,
                    avatar_url TEXT,
                    bio TEXT,
                    follower_count INTEGER NOT NULL DEFAULT 0,
                    media_types TEXT NOT NULL DEFAULT '[]',
                    is_subscribed INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    last_post_at TIMESTAMP,
                    subscribed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(platform, platform_user_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    blogger_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_url TEXT NOT NULL,
                    cover_url TEXT,
                    published_at TIMESTAMP,
                    like_count INTEGER NOT NULL DEFAULT 0,
                    collect_count INTEGER NOT NULL DEFAULT 0,
                    comment_count INTEGER NOT NULL DEFAULT 0,
                    share_count INTEGER NOT NULL DEFAULT 0,
                    stats_synced_at TIMESTAMP,
                    source TEXT NOT NULL DEFAULT 'feed',
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    latest_analysis_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(platform, platform_item_id),
                    FOREIGN KEY (blogger_id) REFERENCES blogger(id)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_blogger_pub "
                "ON content(blogger_id, published_at DESC)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_status ON content(analysis_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_pub ON content(published_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_content_media ON content(media_type)")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    prompt_version INTEGER,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (content_id) REFERENCES content(id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analysis_content ON analysis(content_id)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_cost (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER NOT NULL,
                    content_id INTEGER NOT NULL,
                    blogger_id INTEGER,
                    in_tokens INTEGER NOT NULL DEFAULT 0,
                    out_tokens INTEGER NOT NULL DEFAULT 0,
                    total_cost REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cost_blogger ON analysis_cost(blogger_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cost_created ON analysis_cost(created_at)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_template (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    body TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_prompt_media ON prompt_template(media_type, is_active)")

    def close(self):
        if self._is_postgres:
            return
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
