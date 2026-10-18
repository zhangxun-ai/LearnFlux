"""
审计日志路由模块

提供 API 调用记录查询、历史任务浏览和摘要预览功能。
"""

import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from ..context import get_audit_logger, get_cache_manager, get_logger
from ..services.transcription import TranscribeResponse, verify_token
from ...study.source_files import media_type_for_filename
from ...utils.timeutil import format_datetime_with_timezone, get_configured_timezone

logger = get_logger()
audit_logger = get_audit_logger()

# 延迟导入，避免循环依赖；同时保持模块级引用供测试 mock 使用
from ..context import get_user_manager as _get_user_manager
user_manager = _get_user_manager()

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _history_content_type(platform: str | None, title: str, source_file_path: str | None, video_url: str | None) -> str:
    """Group history inputs for the UI without adding a persisted schema field."""
    is_local_source = bool(source_file_path) or str(video_url or "").lower().startswith("local://")
    if is_local_source:
        filenames = [title or "", Path(source_file_path).name if source_file_path else ""]
        media_source = any(
            media_type_for_filename(name).startswith(("audio/", "video/"))
            for name in filenames if name
        )
        if not media_source:
            return "file"
    if str(platform or "").lower() in {"xiaohongshu", "twitter", "x", "weixin"}:
        return "post"
    return "video"


@router.get("/stats")
async def get_audit_stats(days: int = 30, user_info: dict = Depends(verify_token)):
    try:
        user_id = user_info.get("user_id")
        user_stats = audit_logger.get_user_stats(user_id, days)
        return TranscribeResponse(
            code=200,
            message="获取统计信息成功",
            data={
                "user_stats": user_stats,
                "is_multi_user_mode": user_manager.is_multi_user_mode(),
                "total_users": user_manager.get_user_count(),
            },
        )
    except Exception as exc:
        logger.exception("获取审计统计异常: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {exc}")


@router.get("/calls")
async def get_audit_calls(
    limit: int = 100,
    user_info: dict = Depends(verify_token),
):
    try:
        user_id = user_info.get("user_id")
        recent_calls = audit_logger.get_recent_calls(user_id, limit)
        return TranscribeResponse(
            code=200,
            message="获取调用记录成功",
            data={"calls": recent_calls, "user_id": user_id, "limit": limit},
        )
    except Exception as exc:
        logger.exception("获取审计调用记录异常: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取调用记录失败: {exc}")


@contextmanager
def _history_connection(cache_manager):
    """Open a read-only history connection without initializing repositories."""
    is_postgres = getattr(cache_manager, "_is_postgres", False) is True
    conn = (
        cache_manager.database.connect()
        if is_postgres
        else sqlite3.connect(
            Path(audit_logger.db_path).resolve().as_uri() + "?mode=ro", uri=True
        )
    )
    try:
        prefix = "" if is_postgres else "cache."
        if is_postgres:
            # The content_marks table is created by the existing schema migration.
            has_marks = True
        else:
            cache_uri = Path(cache_manager.db_path).resolve().as_uri() + "?mode=ro"
            conn.execute("ATTACH DATABASE ? AS cache", (cache_uri,))
            conn.execute("PRAGMA query_only = ON")
            has_marks = conn.execute(
                "SELECT 1 FROM cache.sqlite_master WHERE type = 'table' AND name = 'content_marks'"
            ).fetchone() is not None
        yield conn, prefix, has_marks
    finally:
        conn.close()


def _history_records_cte(
    user_info: dict, api_key_masked: str, prefix: str, has_marks: bool
) -> tuple[str, list]:
    """Use one owner-scoped, deduplicated record set for rows and metadata.

    Durable tasks are authoritative. Current-key audit links retain access to
    legacy unowned tasks, and audit-only rows stay visible for recovery. An
    explicit task owner always takes precedence over a legacy audit link.
    """
    include_unowned = bool(
        user_info.get("is_legacy") or user_info.get("user_id") == "legacy_user"
    )
    marks_join = (
        f"LEFT JOIN {prefix}content_marks m ON m.owner_type = 'transcript' "
        "AND m.owner_id = t.view_token AND m.user_key = ?"
        if has_marks else ""
    )
    marked_sql = "CASE WHEN m.id IS NULL THEN 0 ELSE 1 END" if has_marks else "0"
    parameters = [api_key_masked]
    if has_marks:
        parameters.append(api_key_masked)
    parameters.extend([user_info.get("user_id") or "", int(include_unowned)])
    sql = f"""
        WITH owned_audits AS (
            SELECT id, task_id, video_url, wechat_webhook, request_time
            FROM api_audit_logs WHERE api_key_masked = ?
        ), linked_audits AS (
            SELECT a.*, a.task_id AS matched_task_id
            FROM owned_audits a WHERE a.task_id IS NOT NULL
            UNION ALL
            SELECT a.*, t.task_id AS matched_task_id
            FROM owned_audits a JOIN {prefix}task_status t ON t.url = a.video_url
            WHERE a.task_id IS NULL AND a.video_url IS NOT NULL AND a.video_url != ''
        ), candidates AS (
            SELECT
                COALESCE(a.id, 0) AS audit_id,
                t.task_id,
                COALESCE(NULLIF(a.video_url, ''), t.url) AS video_url,
                a.wechat_webhook,
                COALESCE(t.created_at, a.request_time) AS request_time,
                a.request_time AS audit_time,
                a.video_url AS audit_url,
                t.view_token, t.title, t.author,
                COALESCE(NULLIF(t.platform, ''), 'generic') AS platform,
                t.status, t.source_file_path, t.error_message,
                {marked_sql} AS is_marked,
                COALESCE(NULLIF(t.view_token, ''), t.task_id) AS dedupe_key
            FROM {prefix}task_status t
            LEFT JOIN linked_audits a ON a.matched_task_id = t.task_id
            {marks_join}
            WHERE t.owner_user_id = ?
                OR (t.owner_user_id IS NULL AND (a.id IS NOT NULL OR ? = 1))
            UNION ALL
            SELECT
                a.id, a.task_id, a.video_url, a.wechat_webhook,
                a.request_time, a.request_time, a.video_url,
                NULL, NULL, NULL, 'generic', 'unknown', NULL, NULL,
                0, a.task_id
            FROM owned_audits a
            WHERE a.task_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM {prefix}task_status t WHERE t.task_id = a.task_id
                )
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY dedupe_key
                ORDER BY request_time DESC,
                    CASE WHEN audit_url IS NOT NULL AND audit_url != '' THEN 0 ELSE 1 END,
                    audit_time DESC, audit_id DESC, task_id DESC
            ) AS rn FROM candidates
        ), history_records AS (
            SELECT * FROM ranked WHERE rn = 1
        )
    """
    return sql, parameters


def _read_history_query(operation: Callable[[], Any]) -> Any:
    """Retry a transient SQLite read lock in a worker, never on the event loop."""
    for attempt in range(2):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                logger.exception("History database query failed")
                raise HTTPException(status_code=500, detail="查询失败，请稍后重试") from exc
            if attempt:
                raise HTTPException(status_code=503, detail="服务暂时不可用，请稍后重试") from exc
            time.sleep(0.05)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("History database query failed")
            raise HTTPException(status_code=500, detail="查询失败，请稍后重试") from exc


@router.get("/history")
async def get_history(
    start_date: Optional[str] = Query(None, description="导入开始日期，YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="导入结束日期，YYYY-MM-DD"),
    webhook: Optional[str] = Query(None, description="webhook地址精确过滤"),
    platform: Optional[str] = Query(None, description="来源平台"),
    content_type: Optional[str] = Query(None, description="内容类型: video/post/file"),
    author: Optional[str] = Query(None, description="频道/作者，逗号分隔多选"),
    q: Optional[str] = Query(None, description="搜索标题、作者和来源链接"),
    status: Optional[str] = Query(None, description="解析状态，默认 success"),
    marked: bool = Query(False, description="仅精华"),
    limit: int = Query(20, ge=1, le=10000, description="每页条数"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    user_info: dict = Depends(verify_token),
):
    """Return durable owner-scoped history with one count-and-page query."""
    api_key_masked = audit_logger._mask_api_key(user_info.get("api_key", ""))
    cache_manager = get_cache_manager()
    is_postgres = getattr(cache_manager, "_is_postgres", False) is True
    conditions, parameters = [], []
    for value, comparison, suffix in (
        (start_date, ">=", "00:00:00"), (end_date, "<=", "23:59:59.999999")
    ):
        if value:
            try:
                parsed = datetime.fromisoformat(f"{value} {suffix}")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from exc
            # Filter the same calendar day shown by the configured display timezone.
            utc_boundary = parsed.replace(tzinfo=get_configured_timezone()).astimezone(
                timezone.utc
            ).replace(tzinfo=None)
            conditions.append(f"request_time {comparison} ?")
            parameters.append(utc_boundary if is_postgres else utc_boundary.isoformat(" "))
    for column, value in (("wechat_webhook", webhook), ("platform", platform)):
        if value:
            conditions.append(f"{column} = ?")
            parameters.append(value)
    if content_type and content_type not in {"all", "video", "post", "file"}:
        raise HTTPException(status_code=422, detail="content_type must be video, post, or file")
    if content_type and content_type != "all":
        media_extensions = (
            ".mp4", ".ts", ".m4v", ".mov", ".webm", ".mkv", ".avi",
            ".mp3", ".m4a", ".wav", ".aac", ".flac",
        )
        suffixes = " OR ".join(
            f"LOWER(COALESCE({column}, '')) LIKE '%{extension}'"
            for column in ("title", "source_file_path") for extension in media_extensions
        )
        type_sql = (
            "CASE WHEN (COALESCE(source_file_path, '') != '' OR "
            "LOWER(COALESCE(video_url, '')) LIKE 'local://%') "
            f"AND NOT ({suffixes}) THEN 'file' "
            "WHEN LOWER(platform) IN ('xiaohongshu', 'twitter', 'x', 'weixin') THEN 'post' "
            "ELSE 'video' END"
        )
        conditions.append(f"({type_sql}) = ?")
        parameters.append(content_type)
    if author:
        authors = [value.strip() for value in author.split(",") if value.strip()]
        if authors:
            conditions.append(f"author IN ({','.join('?' for _ in authors)})")
            parameters.extend(authors)
    effective_status = status or "success"
    if effective_status == "processing":
        conditions.append("status IN ('queued', 'processing', 'calibrating')")
    elif effective_status != "all":
        conditions.append("status = ?")
        parameters.append(effective_status)
    if q and q.strip():
        conditions.append(
            "(COALESCE(title, '') LIKE ? OR COALESCE(author, '') LIKE ? "
            "OR COALESCE(video_url, '') LIKE ?)"
        )
        parameters.extend([f"%{q.strip()}%"] * 3)
    if marked:
        conditions.append("is_marked = 1")
    where_sql = " AND ".join(conditions) or "1 = 1"

    def read_page():
        with _history_connection(cache_manager) as (conn, prefix, has_marks):
            cte, scope_parameters = _history_records_cte(
                user_info, api_key_masked, prefix, has_marks
            )
            query_parameters = scope_parameters + parameters
            # A single aggregate row also preserves the total for an empty page.
            sql = cte + f"""
                , matches AS (SELECT * FROM history_records WHERE {where_sql}),
                page AS (
                    SELECT * FROM matches
                    ORDER BY request_time DESC, audit_id DESC, task_id DESC
                    LIMIT ? OFFSET ?
                )
                SELECT page.task_id, page.video_url, page.wechat_webhook,
                    page.request_time, page.view_token, page.title, page.author,
                    page.platform, page.status, page.source_file_path,
                    page.is_marked, page.error_message, totals.total
                FROM (SELECT COUNT(*) AS total FROM matches) totals
                LEFT JOIN page ON 1 = 1
                ORDER BY page.request_time DESC, page.audit_id DESC, page.task_id DESC
            """
            rows = conn.execute(sql, query_parameters + [limit, offset]).fetchall()
            total = int(rows[0][12]) if rows else 0
            items = []
            for row in rows:
                if row[0] is None:
                    continue
                source_path = Path(row[9]) if row[9] else None
                source_name = row[5] or (source_path.name if source_path else "")
                study_available = bool(
                    row[4] and source_path
                    and media_type_for_filename(source_name).startswith(("audio/", "video/"))
                    and source_path.is_file()
                )
                items.append({
                    "task_id": row[0], "video_url": row[1], "wechat_webhook": row[2],
                    "request_time": row[3],
                    "request_time_display": format_datetime_with_timezone(row[3], "%Y-%m-%d %H:%M"),
                    "api_key_masked": api_key_masked,
                    "view_token": row[4], "title": row[5], "author": row[6],
                    "platform": row[7], "status": row[8] or "unknown",
                    "content_type": _history_content_type(row[7], source_name, row[9], row[1]),
                    "is_marked": bool(row[10]), "error": row[11] or "",
                    "study_available": study_available,
                    "study_url": f"/study/{row[4]}" if study_available else "",
                })
            return total, items

    total, items = await run_in_threadpool(_read_history_query, read_page)
    return TranscribeResponse(code=200, message="获取历史记录成功", data={
        "items": items, "total": total, "limit": limit, "offset": offset,
        "api_key_masked": api_key_masked,
    })


@router.get("/filter-options")
async def get_filter_options(user_info: dict = Depends(verify_token)):
    """Return metadata from the same owner-scoped record set as history."""
    api_key_masked = audit_logger._mask_api_key(user_info.get("api_key", ""))
    cache_manager = get_cache_manager()

    def read_options():
        with _history_connection(cache_manager) as (conn, prefix, has_marks):
            cte, parameters = _history_records_cte(
                user_info, api_key_masked, prefix, has_marks
            )
            rows = conn.execute(
                cte + "SELECT platform, author, wechat_webhook FROM history_records", parameters
            ).fetchall()
        platform_counts = Counter(row[0] for row in rows)
        authors = Counter(row[1] for row in rows if row[1])
        webhooks = Counter(row[2] for row in rows if row[2])
        counts = [
            {"platform": platform, "count": count}
            for platform, count in sorted(
                platform_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        return {
            "webhooks": [value for value, _ in webhooks.most_common(50)],
            "platforms": [item["platform"] for item in counts],
            "platform_counts": counts,
            "authors": [value for value, _ in authors.most_common(50)],
            "total": len(rows),
            "api_key_masked": api_key_masked,
        }

    data = await run_in_threadpool(_read_history_query, read_options)
    return TranscribeResponse(code=200, message="获取过滤选项成功", data=data)


def _require_summary_owner(task_info: dict, user_info: dict, api_key_masked: str) -> None:
    """Apply the same durable-owner and legacy scope as the history list."""
    owner = task_info.get("owner_user_id")
    if owner is not None:
        if owner != user_info.get("user_id"):
            raise HTTPException(status_code=403, detail="无权访问该任务")
        return
    if user_info.get("is_legacy") or user_info.get("user_id") == "legacy_user":
        return

    try:
        with audit_logger._get_cursor() as cursor:
            cursor.execute(
                """SELECT 1 FROM api_audit_logs
                WHERE api_key_masked = ? AND (
                    task_id = ? OR (
                        task_id IS NULL AND video_url IS NOT NULL
                        AND video_url != '' AND video_url = ?
                    )
                ) LIMIT 1""",
                (api_key_masked, task_info.get("task_id"), task_info.get("url")),
            )
            allowed = cursor.fetchone() is not None
    except Exception as exc:
        logger.exception("Summary ownership lookup failed")
        raise HTTPException(status_code=503, detail="暂时无法核验任务归属，请稍后重试") from exc
    if not allowed:
        raise HTTPException(status_code=403, detail="无权访问该任务")


@router.get("/summary")
async def get_task_summary(
    view_token: str = Query(..., description="任务的 view_token"),
    user_info: dict = Depends(verify_token),
):
    """Return a 300-character preview using the history ownership contract."""
    api_key_masked = audit_logger._mask_api_key(user_info.get("api_key", ""))
    cache_manager = get_cache_manager()

    def read_summary():
        task_info = cache_manager.get_task_by_view_token(view_token)
        if not task_info:
            raise HTTPException(status_code=404, detail="任务不存在")
        _require_summary_owner(task_info, user_info, api_key_masked)
        task_status = task_info.get("status", "")
        if task_status != "success":
            return TranscribeResponse(
                code=202, message="任务尚未解析完成",
                data={"summary": "", "status": task_status},
            )
        view_data = cache_manager.get_view_data_by_token(view_token)
        if not view_data or view_data.get("status") != "success":
            return TranscribeResponse(
                code=200, message="摘要不可用",
                data={"summary": "", "status": view_data.get("status") if view_data else "unknown"},
            )
        return TranscribeResponse(
            code=200, message="获取摘要成功",
            data={"summary": (view_data.get("summary") or "")[:300], "status": "success"},
        )

    return await run_in_threadpool(_read_history_query, read_summary)
