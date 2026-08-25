"""Storage-agnostic repository interfaces + SQLite implementations.

Business logic depends on the ``*Repository`` Protocols, never on sqlite
directly. To move to Supabase later, add new implementations of these
Protocols; callers don't change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Protocol, Sequence

from .db import FlywheelDB
from .models import (
    Analysis, AnalysisCost, AnalysisStatus, Blogger, Content, ContentSource,
    MediaType, PromptTemplate,
)


# --------------------------------------------------------------------------- #
# Row mappers
# --------------------------------------------------------------------------- #

def _dt(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value) if value else None


def _blogger_from_row(row) -> Blogger:
    return Blogger(
        id=row["id"],
        platform=row["platform"],
        platform_user_id=row["platform_user_id"],
        handle=row["handle"],
        avatar_url=row["avatar_url"],
        bio=row["bio"],
        follower_count=row["follower_count"],
        media_types=tuple(MediaType(m) for m in json.loads(row["media_types"])),
        is_subscribed=bool(row["is_subscribed"]),
        pinned=bool(row["pinned"]),
        last_post_at=_dt(row["last_post_at"]),
        subscribed_at=_dt(row["subscribed_at"]),
        created_at=_dt(row["created_at"]),
    )


def _content_from_row(row) -> Content:
    return Content(
        id=row["id"],
        blogger_id=row["blogger_id"],
        platform=row["platform"],
        platform_item_id=row["platform_item_id"],
        media_type=MediaType(row["media_type"]),
        title=row["title"],
        original_url=row["original_url"],
        cover_url=row["cover_url"],
        published_at=_dt(row["published_at"]),
        like_count=row["like_count"],
        collect_count=row["collect_count"],
        comment_count=row["comment_count"],
        share_count=row["share_count"],
        stats_synced_at=_dt(row["stats_synced_at"]),
        source=ContentSource(row["source"]),
        analysis_status=AnalysisStatus(row["analysis_status"]),
        latest_analysis_id=row["latest_analysis_id"],
        created_at=_dt(row["created_at"]),
    )


# --------------------------------------------------------------------------- #
# Blogger
# --------------------------------------------------------------------------- #

class BloggerRepository(Protocol):
    def upsert(self, blogger: Blogger) -> Blogger: ...
    def get(self, blogger_id: int) -> Optional[Blogger]: ...
    def list_subscribed(self) -> list[Blogger]: ...
    def set_subscribed(self, blogger_id: int, value: bool) -> None: ...


class SqliteBloggerRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def upsert(self, blogger: Blogger) -> Blogger:
        media = json.dumps([m.value for m in blogger.media_types])
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO blogger (platform, platform_user_id, handle, avatar_url,
                    bio, follower_count, media_types, is_subscribed, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_user_id) DO UPDATE SET
                    handle=excluded.handle, avatar_url=excluded.avatar_url, bio=excluded.bio,
                    follower_count=excluded.follower_count, media_types=excluded.media_types
                """,
                (blogger.platform, blogger.platform_user_id, blogger.handle, blogger.avatar_url,
                 blogger.bio, blogger.follower_count, media,
                 int(blogger.is_subscribed), int(blogger.pinned)),
            )
            cur.execute(
                "SELECT * FROM blogger WHERE platform=? AND platform_user_id=?",
                (blogger.platform, blogger.platform_user_id),
            )
            return _blogger_from_row(cur.fetchone())

    def get(self, blogger_id: int) -> Optional[Blogger]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM blogger WHERE id=?", (blogger_id,))
            row = cur.fetchone()
            return _blogger_from_row(row) if row else None

    def list_subscribed(self) -> list[Blogger]:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT * FROM blogger WHERE is_subscribed=1 "
                "ORDER BY pinned DESC, last_post_at DESC, id DESC"
            )
            return [_blogger_from_row(r) for r in cur.fetchall()]

    def set_subscribed(self, blogger_id: int, value: bool) -> None:
        with self._db.cursor() as cur:
            cur.execute("UPDATE blogger SET is_subscribed=? WHERE id=?",
                        (int(value), blogger_id))


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ContentQuery:
    """Filter / sort / paginate spec. Maps 1:1 to the UI filter bar."""
    subscribed: Optional[bool] = None              # None=全部
    blogger_ids: Sequence[int] = ()                # () = 全部
    statuses: Sequence[AnalysisStatus] = ()        # () = 全部
    media_type: Optional[MediaType] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    sort: str = "published_at"                     # "published_at" | "like_count"
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))  # ceil division


class ContentRepository(Protocol):
    def upsert(self, content: Content) -> Content: ...
    def get(self, content_id: int) -> Optional[Content]: ...
    def list(self, query: ContentQuery) -> Page: ...
    def set_analysis_status(self, content_id: int, status: AnalysisStatus,
                            analysis_id: Optional[int] = None) -> None: ...


class SqliteContentRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def upsert(self, content: Content) -> Content:
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO content (blogger_id, platform, platform_item_id, media_type,
                    title, original_url, cover_url, published_at, like_count, collect_count,
                    comment_count, share_count, source, analysis_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_item_id) DO UPDATE SET
                    title=excluded.title, original_url=excluded.original_url,
                    cover_url=excluded.cover_url,
                    like_count=excluded.like_count, collect_count=excluded.collect_count,
                    comment_count=excluded.comment_count, share_count=excluded.share_count
                """,
                (content.blogger_id, content.platform, content.platform_item_id,
                 content.media_type.value, content.title, content.original_url, content.cover_url,
                 content.published_at.isoformat() if content.published_at else None,
                 content.like_count, content.collect_count, content.comment_count,
                 content.share_count, content.source.value, content.analysis_status.value),
            )
            cur.execute(
                "SELECT * FROM content WHERE platform=? AND platform_item_id=?",
                (content.platform, content.platform_item_id),
            )
            return _content_from_row(cur.fetchone())

    def get(self, content_id: int) -> Optional[Content]:
        with self._db.cursor() as cur:
            cur.execute("SELECT * FROM content WHERE id=?", (content_id,))
            row = cur.fetchone()
            return _content_from_row(row) if row else None

    def list(self, query: ContentQuery) -> Page:
        where: list[str] = []
        params: list = []
        if query.blogger_ids:
            where.append(f"c.blogger_id IN ({','.join('?' * len(query.blogger_ids))})")
            params += list(query.blogger_ids)
        if query.statuses:
            where.append(f"c.analysis_status IN ({','.join('?' * len(query.statuses))})")
            params += [s.value for s in query.statuses]
        if query.media_type:
            where.append("c.media_type=?")
            params.append(query.media_type.value)
        if query.date_from:
            where.append("c.published_at>=?")
            params.append(query.date_from.isoformat())
        if query.date_to:
            where.append("c.published_at<=?")
            params.append(query.date_to.isoformat())
        if query.subscribed is not None:
            where.append("b.is_subscribed=?")
            params.append(int(query.subscribed))
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = "c.like_count DESC" if query.sort == "like_count" else "c.published_at DESC"
        base = f"FROM content c JOIN blogger b ON c.blogger_id=b.id{clause}"
        with self._db.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) {base}", params)
            total = cur.fetchone()[0]
            offset = (query.page - 1) * query.page_size
            cur.execute(
                f"SELECT c.* {base} ORDER BY {order}, c.id DESC LIMIT ? OFFSET ?",
                params + [query.page_size, offset],
            )
            items = [_content_from_row(r) for r in cur.fetchall()]
        return Page(items=items, total=total, page=query.page, page_size=query.page_size)

    def set_analysis_status(self, content_id: int, status: AnalysisStatus,
                            analysis_id: Optional[int] = None) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE content SET analysis_status=?, latest_analysis_id=? WHERE id=?",
                (status.value, analysis_id, content_id),
            )


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #

class AnalysisRepository(Protocol):
    def create(self, analysis: Analysis) -> Analysis: ...
    def get_by_content(self, content_id: int) -> Optional[Analysis]: ...


class SqliteAnalysisRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def create(self, analysis: Analysis) -> Analysis:
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis (content_id, media_type, status, result_json,
                    error_message, prompt_version, model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (analysis.content_id, analysis.media_type.value, analysis.status.value,
                 json.dumps(analysis.result_json, ensure_ascii=False), analysis.error_message,
                 analysis.prompt_version, analysis.model),
            )
            return replace(analysis, id=cur.lastrowid)

    def get_by_content(self, content_id: int) -> Optional[Analysis]:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT * FROM analysis WHERE content_id=? ORDER BY id DESC LIMIT 1",
                (content_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return Analysis(
                id=row["id"], content_id=row["content_id"],
                media_type=MediaType(row["media_type"]), status=AnalysisStatus(row["status"]),
                result_json=json.loads(row["result_json"] or "{}"),
                error_message=row["error_message"], prompt_version=row["prompt_version"],
                model=row["model"], created_at=_dt(row["created_at"]),
            )


# --------------------------------------------------------------------------- #
# Analysis cost ledger
# --------------------------------------------------------------------------- #

class AnalysisCostRepository(Protocol):
    def add(self, cost: AnalysisCost) -> AnalysisCost: ...
    def total(self) -> float: ...
    def total_by_blogger(self) -> dict: ...


class SqliteAnalysisCostRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def add(self, cost: AnalysisCost) -> AnalysisCost:
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis_cost (analysis_id, content_id, blogger_id,
                    in_tokens, out_tokens, total_cost, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (cost.analysis_id, cost.content_id, cost.blogger_id, cost.in_tokens,
                 cost.out_tokens, cost.total_cost, cost.currency),
            )
            return replace(cost, id=cur.lastrowid)

    def total(self) -> float:
        with self._db.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(total_cost), 0) FROM analysis_cost")
            return float(cur.fetchone()[0])

    def total_by_blogger(self) -> dict:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT blogger_id, COALESCE(SUM(total_cost), 0) FROM analysis_cost "
                "GROUP BY blogger_id"
            )
            return {row[0]: float(row[1]) for row in cur.fetchall()}


# --------------------------------------------------------------------------- #
# Prompt templates (editable, one active version per media type)
# --------------------------------------------------------------------------- #

def _prompt_from_row(row) -> PromptTemplate:
    return PromptTemplate(
        id=row["id"], media_type=MediaType(row["media_type"]), version=row["version"],
        body=row["body"], is_active=bool(row["is_active"]), updated_at=_dt(row["updated_at"]),
    )


class PromptTemplateRepository(Protocol):
    def get_active(self, media_type: MediaType) -> Optional[PromptTemplate]: ...
    def list_versions(self, media_type: MediaType, limit: int = 20) -> list[PromptTemplate]: ...
    def upsert(self, media_type: MediaType, body: str) -> PromptTemplate: ...
    def upgrade_default_if_legacy(
        self, media_type: MediaType, new_body: str, legacy_bodies: Sequence[str]
    ) -> Optional[PromptTemplate]: ...
    def seed_defaults(self, defaults: dict) -> None: ...


class SqlitePromptTemplateRepository:
    def __init__(self, db: FlywheelDB):
        self._db = db

    def get_active(self, media_type: MediaType) -> Optional[PromptTemplate]:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT * FROM prompt_template WHERE media_type=? AND is_active=1 "
                "ORDER BY version DESC LIMIT 1",
                (media_type.value,),
            )
            row = cur.fetchone()
            return _prompt_from_row(row) if row else None

    def list_versions(self, media_type: MediaType, limit: int = 20) -> list[PromptTemplate]:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT * FROM prompt_template WHERE media_type=? "
                "ORDER BY version DESC LIMIT ?",
                (media_type.value, limit),
            )
            return [_prompt_from_row(row) for row in cur.fetchall()]

    def upsert(self, media_type: MediaType, body: str) -> PromptTemplate:
        """Save a new active version, deactivating the previous active one."""
        with self._db.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM prompt_template WHERE media_type=?",
                        (media_type.value,))
            next_version = cur.fetchone()[0] + 1
            cur.execute("UPDATE prompt_template SET is_active=0 WHERE media_type=?",
                        (media_type.value,))
            cur.execute(
                "INSERT INTO prompt_template (media_type, version, body, is_active) "
                "VALUES (?, ?, ?, 1)",
                (media_type.value, next_version, body),
            )
            new_id = cur.lastrowid
            cur.execute("SELECT * FROM prompt_template WHERE id=?", (new_id,))
            return _prompt_from_row(cur.fetchone())

    def upgrade_default_if_legacy(
        self, media_type: MediaType, new_body: str, legacy_bodies: Sequence[str]
    ) -> Optional[PromptTemplate]:
        active = self.get_active(media_type)
        if not active:
            return self.upsert(media_type, new_body)
        if active.body != new_body and active.body in set(legacy_bodies):
            return self.upsert(media_type, new_body)
        return active

    def seed_defaults(self, defaults: dict) -> None:
        """Insert a v1 active prompt for any media type that has none yet."""
        for media_type, body in defaults.items():
            if self.get_active(media_type) is None:
                self.upsert(media_type, body)
