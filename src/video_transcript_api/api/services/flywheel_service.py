"""Service layer wiring the flywheel feature into the web app.

Owns a lazily-built singleton of the flywheel DB + repositories, and exposes
the operations the routes need: quick-analyze a URL end-to-end (fetch -> text
-> LLM -> persist), list content with filters, manage subscribed bloggers, and
summarize a blogger's overall playbook (multi-sample).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Optional

from ...flywheel.analyzer import ContentAnalyzer
from ...flywheel.analysis_service import run_analysis
from ...flywheel.db import FlywheelDB
from ...flywheel.ingest import ingest_blogger
from ...flywheel.models import (
    AnalysisStatus, Blogger, Content, ContentSource, MediaType,
)
from ...flywheel.prompts import DEFAULT_PROMPTS
from ...flywheel.repositories import (
    ContentQuery, SqliteAnalysisCostRepository, SqliteAnalysisRepository,
    SqliteBloggerRepository, SqliteContentRepository, SqlitePromptTemplateRepository,
)
from ...flywheel.text_acquisition import acquire_text
from ...utils.logging import setup_logger

logger = setup_logger("flywheel_service")

_lock = threading.Lock()
_repos: Optional[dict] = None


def repos() -> dict:
    """Lazily build (once) the shared DB + repositories; seed default prompts."""
    global _repos
    if _repos is None:
        with _lock:
            if _repos is None:
                db = FlywheelDB()
                prompt = SqlitePromptTemplateRepository(db)
                prompt.seed_defaults(DEFAULT_PROMPTS)
                _repos = {
                    "db": db,
                    "blogger": SqliteBloggerRepository(db),
                    "content": SqliteContentRepository(db),
                    "analysis": SqliteAnalysisRepository(db),
                    "cost": SqliteAnalysisCostRepository(db),
                    "prompt": prompt,
                }
    return _repos


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def _serialize_content(c: Content, handle: str) -> dict:
    return {
        "id": c.id,
        "blogger_id": c.blogger_id,
        "blogger_handle": handle,
        "platform": c.platform,
        "media_type": c.media_type.value,
        "title": c.title,
        "original_url": c.original_url,
        "published_at": c.published_at.isoformat() if c.published_at else None,
        "like_count": c.like_count,
        "collect_count": c.collect_count,
        "comment_count": c.comment_count,
        "analysis_status": c.analysis_status.value,
        "source": c.source.value,
    }


# --------------------------------------------------------------------------- #
# Quick analyze (one URL, end-to-end)
# --------------------------------------------------------------------------- #

def analyze_url(url: str, analyzer: ContentAnalyzer) -> dict:
    """Fetch a single note, acquire its text (transcribe video), analyze, persist."""
    r = repos()
    detail, text = acquire_text(url)

    uid = detail.author_user_id or f"adhoc:{detail.note_id}"
    blogger = r["blogger"].upsert(Blogger(
        id=None, platform="xiaohongshu", platform_user_id=uid,
        handle=detail.author or "临时解析", media_types=(detail.media_type,),
        is_subscribed=False,
    ))
    content = r["content"].upsert(Content(
        id=None, blogger_id=blogger.id, platform="xiaohongshu",
        platform_item_id=detail.note_id, media_type=detail.media_type,
        title=detail.title, original_url=url, like_count=detail.like_count,
        collect_count=detail.collect_count, comment_count=detail.comment_count,
        source=ContentSource.ADHOC,
    ))

    analysis = run_analysis(
        content, text,
        analyzer=analyzer, analysis_repo=r["analysis"], cost_repo=r["cost"],
        content_repo=r["content"], prompt_repo=r["prompt"],
    )

    result = analysis.result_json or {}
    return {
        "ok": analysis.status is AnalysisStatus.SUCCESS,
        "content_id": content.id,
        "title": detail.title,
        "author": detail.author,
        "media_type": detail.media_type.value,
        "original_url": url,
        "stats": {"like_count": detail.like_count, "collect_count": detail.collect_count,
                  "comment_count": detail.comment_count},
        "status": analysis.status.value,
        "error": analysis.error_message,
        "sections": result.get("sections", []),
        "one_thing": result.get("one_thing", ""),
        "markdown": result.get("markdown", ""),
    }


# --------------------------------------------------------------------------- #
# Lists / bloggers / subscribe
# --------------------------------------------------------------------------- #

_PRESET_DAYS = {"today": 1, "7d": 7, "30d": 30, "90d": 90}


def _date_from(preset: Optional[str], now: datetime) -> Optional[datetime]:
    if preset == "today":
        return datetime(now.year, now.month, now.day)
    days = _PRESET_DAYS.get(preset or "")
    return (now - timedelta(days=days)) if days else None


def list_contents(*, subscribe=None, blogger_ids=(), statuses=(), media_type=None,
                  date_preset=None, sort="published_at", page=1, page_size=20,
                  now: Optional[datetime] = None) -> dict:
    r = repos()
    now = now or datetime.now()
    q = ContentQuery(
        subscribed={"subscribed": True, "adhoc": False}.get(subscribe),
        blogger_ids=tuple(blogger_ids),
        statuses=tuple(AnalysisStatus(s) for s in statuses),
        media_type=MediaType(media_type) if media_type else None,
        date_from=_date_from(date_preset, now),
        sort=sort, page=page, page_size=page_size,
    )
    pg = r["content"].list(q)
    handles = {b.id: b.handle for b in [r["blogger"].get(c.blogger_id) for c in pg.items] if b}
    return {
        "items": [_serialize_content(c, handles.get(c.blogger_id, "")) for c in pg.items],
        "total": pg.total, "page": pg.page, "page_size": pg.page_size, "pages": pg.pages,
    }


def list_bloggers() -> list[dict]:
    r = repos()
    return [
        {"id": b.id, "handle": b.handle, "platform": b.platform,
         "follower_count": b.follower_count, "pinned": b.pinned,
         "media_types": [m.value for m in b.media_types]}
        for b in r["blogger"].list_subscribed()
    ]


def subscribe(url: str, max_items: int = 20) -> dict:
    r = repos()
    res = ingest_blogger(url, subscribe=True, blogger_repo=r["blogger"],
                         content_repo=r["content"], max_items=max_items)
    return {"ok": True, "blogger_id": res.blogger.id, "handle": res.blogger.handle,
            "ingested": res.ingested}


def usage() -> dict:
    r = repos()
    by_blogger = r["cost"].total_by_blogger()
    handles = {bid: (r["blogger"].get(bid).handle if r["blogger"].get(bid) else str(bid))
               for bid in by_blogger}
    return {
        "total": round(r["cost"].total(), 4),
        "by_blogger": [{"blogger_id": bid, "handle": handles.get(bid, ""), "cost": round(c, 4)}
                       for bid, c in by_blogger.items()],
    }


def get_analysis(content_id: int) -> dict:
    """Return a persisted content's stored analysis (for the 'view result' entry)."""
    r = repos()
    content = r["content"].get(content_id)
    if not content:
        raise ValueError("内容不存在")
    blogger = r["blogger"].get(content.blogger_id)
    analysis = r["analysis"].get_by_content(content_id)
    result = (analysis.result_json if analysis else {}) or {}
    return {
        "ok": bool(analysis and analysis.status is AnalysisStatus.SUCCESS),
        "content_id": content.id,
        "title": content.title,
        "author": blogger.handle if blogger else "",
        "media_type": content.media_type.value,
        "original_url": content.original_url,
        "stats": {"like_count": content.like_count, "collect_count": content.collect_count,
                  "comment_count": content.comment_count},
        "status": content.analysis_status.value,
        "error": analysis.error_message if analysis else None,
        "sections": result.get("sections", []),
        "one_thing": result.get("one_thing", ""),
        "markdown": result.get("markdown", ""),
    }
