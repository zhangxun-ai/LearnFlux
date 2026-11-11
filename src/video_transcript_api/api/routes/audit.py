"""
审计日志路由模块

提供 API 调用记录查询、历史任务浏览和摘要预览功能。
"""

import sqlite3
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..context import get_audit_logger, get_cache_manager, get_config, get_logger
from ..services.study_access import require_study_source
from ..services.transcription import TranscribeResponse, verify_token
from ...collections.titles import source_display_title
from ...study.source_files import media_type_for_filename
from ...study.body_search import authorized_body_texts, matching_excerpt
from ...utils.timeutil import format_datetime_with_timezone, get_configured_timezone

logger = get_logger()
audit_logger = get_audit_logger()

# 延迟导入，避免循环依赖；同时保持模块级引用供测试 mock 使用
from ..context import get_user_manager as _get_user_manager
user_manager = _get_user_manager()

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _history_content_type(platform: str | None, title: str, source_file_path: str | None, video_url: str | None) -> str:
    """Group history inputs for the UI without adding a persisted schema field."""
    platform = (platform or "").lower()
    if platform == "feishu":
        return "file"
    if platform in {"xiaohongshu", "twitter", "x", "weixin"}:
        return "post"
    is_local_source = bool(source_file_path) or str(video_url or "").lower().startswith("local://")
    if is_local_source:
        filenames = [title or "", Path(source_file_path).name if source_file_path else ""]
        media_source = any(
            media_type_for_filename(name).startswith(("audio/", "video/"))
            for name in filenames if name
        )
        if not media_source:
            return "file"
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
            has_hidden = True
        else:
            cache_uri = Path(cache_manager.db_path).resolve().as_uri() + "?mode=ro"
            conn.execute("ATTACH DATABASE ? AS cache", (cache_uri,))
            conn.execute("PRAGMA query_only = ON")
            has_marks = conn.execute(
                "SELECT 1 FROM cache.sqlite_master WHERE type = 'table' AND name = 'content_marks'"
            ).fetchone() is not None
            has_hidden = conn.execute(
                "SELECT 1 FROM cache.sqlite_master WHERE type = 'table' AND name = 'task_history_hidden'"
            ).fetchone() is not None
        yield conn, prefix, has_marks, has_hidden
    finally:
        conn.close()


def _history_records_cte(
    user_info: dict, api_key_masked: str, prefix: str, has_marks: bool,
    has_hidden: bool,
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
    visible_sql = ""
    if has_hidden:
        visible_sql = (
            f"AND NOT EXISTS (SELECT 1 FROM {prefix}task_history_hidden h "
            "WHERE h.task_id = candidates.task_id AND h.user_id = ?)"
        )
        parameters.append(user_info.get("user_id") or "")
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
                COALESCE(NULLIF(t.view_token, ''), t.task_id) AS dedupe_key,
                t.cache_id, t.owner_user_id
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
                0, a.task_id, NULL, NULL
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
            ) AS rn FROM candidates WHERE 1 = 1 {visible_sql}
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
    q: Optional[str] = Query(None, max_length=200, description="搜索标题、作者、来源链接和已解析正文"),
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
            "CASE WHEN LOWER(platform) = 'feishu' THEN 'file' "
            "WHEN LOWER(platform) IN ('xiaohongshu', 'twitter', 'x', 'weixin') THEN 'post' "
            "WHEN (COALESCE(source_file_path, '') != '' OR "
            "LOWER(COALESCE(video_url, '')) LIKE 'local://%') "
            f"AND NOT ({suffixes}) THEN 'file' "
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
    if marked:
        conditions.append("is_marked = 1")
    where_sql = " AND ".join(conditions) or "1 = 1"

    def read_page():
        with _history_connection(cache_manager) as (conn, prefix, has_marks, has_hidden):
            cte, scope_parameters = _history_records_cte(
                user_info, api_key_masked, prefix, has_marks, has_hidden
            )
            query_parameters = scope_parameters + parameters
            excerpts = {}
            if q and q.strip():
                # Scope and other filters are applied before reading any body.
                # Paginate after matching, so body-only hits and total agree.
                candidates = conn.execute(cte + f"""
                    SELECT task_id, video_url, wechat_webhook, request_time,
                        view_token, title, author, platform, status,
                        source_file_path, is_marked, error_message, cache_id, owner_user_id
                    FROM history_records WHERE {where_sql}
                    ORDER BY request_time DESC, audit_id DESC, task_id DESC
                """, query_parameters).fetchall()
                metadata_matches, body_candidates = set(), []
                for candidate in candidates:
                    if matching_excerpt([str(candidate[index] or "") for index in (1, 5, 6)], q) is not None:
                        metadata_matches.add(candidate[0])
                    elif candidate[12] is not None:
                        if str(candidate[7] or "").lower() == "feishu":
                            from ...document_sources.feishu import FeishuDocumentError, require_feishu_access
                            try:
                                require_feishu_access(get_config().get("feishu_documents") or {},
                                                      {"owner_user_id": candidate[13]})
                            except FeishuDocumentError:
                                continue
                        body_candidates.append(candidate)
                bodies = authorized_body_texts(conn, prefix, cache_manager,
                                               [row[12] for row in body_candidates])
                for candidate in body_candidates:
                    excerpt = matching_excerpt(bodies.get(str(candidate[12]), []), q)
                    if excerpt is not None:
                        excerpts[candidate[0]] = excerpt
                matched = [row for row in candidates if row[0] in metadata_matches or row[0] in excerpts]
                total = len(matched)
                rows = matched[offset:offset + limit]
            else:
                rows = None
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
            if rows is None:
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
                    "task_id": row[0], "video_url": row[1], "wechat_webhook": None,
                    "request_time": row[3],
                    "request_time_display": format_datetime_with_timezone(row[3], "%Y-%m-%d %H:%M"),
                    "api_key_masked": api_key_masked,
                    "view_token": row[4], "title": row[5], "author": row[6],
                    "platform": row[7], "status": row[8] or "unknown",
                    "content_type": _history_content_type(row[7], source_name, row[9], row[1]),
                    "is_marked": bool(row[10]), "error": row[11] or "",
                    "study_available": study_available,
                    "study_url": f"/study/{row[4]}" if study_available else "",
                    "search_in_body": row[0] in excerpts,
                    "search_excerpt": excerpts.get(row[0], ""),
                })
            return total, items

    total, items = await run_in_threadpool(_read_history_query, read_page)
    return TranscribeResponse(code=200, message="获取历史记录成功", data={
        "items": items, "total": total, "limit": limit, "offset": offset,
        "api_key_masked": api_key_masked,
    })


def _reading_search_key(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum())


def _reading_match_score(phrase: str, terms: list[str], title: str, author: str) -> int:
    fields = [_reading_search_key(title), _reading_search_key(author)]
    if phrase in fields:
        return 4
    if any(phrase in field for field in fields):
        return 3
    if len(terms) > 1 and all(any(term in field for field in fields) for term in terms):
        return 2
    if len(phrase) >= 3:
        # Match ordered characters across small gaps, e.g. “验证产品” in “验证一个 AI 产品”.
        for field in fields:
            start = field.find(phrase[0])
            while start != -1:
                position = start
                for char in phrase[1:]:
                    position = field.find(char, position + 1, start + 3 * len(phrase))
                    if position == -1:
                        break
                if position != -1:
                    return 1
                start = field.find(phrase[0], start + 1)
    return 0


def _reading_series_tokens(conn, prefix: str, view_token: str, user_id: str) -> set[str]:
    if prefix and not conn.execute(
        "SELECT 1 FROM cache.sqlite_master WHERE type = 'table' AND name = 'learning_collection_sources'"
    ).fetchone():
        return set()
    return {row[0] for row in conn.execute(f"""
        SELECT DISTINCT sibling.view_token
        FROM {prefix}learning_collection_sources current_source
        JOIN {prefix}learning_collections collection ON collection.id = current_source.collection_id
        JOIN {prefix}learning_collection_sources sibling ON sibling.collection_id = collection.id
        WHERE current_source.view_token = ? AND collection.owner_user_id = ?
    """, (view_token, user_id)).fetchall()}


@router.get("/reading-switch")
async def get_reading_switch(
    response: Response,
    current: str = Query(min_length=1, max_length=128),
    q: str = Query("", max_length=200),
    user_info: dict = Depends(verify_token),
):
    """Suggest completed results from the reader's own visible history."""
    cache_manager = get_cache_manager()
    api_key_masked = audit_logger._mask_api_key(user_info.get("api_key", ""))
    user_id = user_info.get("user_id") or ""
    feishu_settings = get_config().get("feishu_documents") or {}
    search = q.strip()
    phrase = _reading_search_key(search)
    terms = [term for word in search.split() if (term := _reading_search_key(word))]

    def read_switch():
        task = require_study_source(
            cache_manager.get_task_by_view_token(current), user_info, audit_logger, feishu_settings
        )
        with _history_connection(cache_manager) as (conn, prefix, has_marks, has_hidden):
            cte, parameters = _history_records_cte(
                user_info, api_key_masked, prefix, has_marks, has_hidden
            )
            series = set() if search else _reading_series_tokens(conn, prefix, current, user_id)
            candidates = conn.execute(cte + f"""
                SELECT r.view_token, COALESCE(NULLIF(r.title, ''), v.title) AS title,
                    COALESCE(NULLIF(r.author, ''), v.author) AS author, t.url,
                    COALESCE(t.completed_at, r.request_time) AS finished_at, v.files_loc
                FROM history_records r
                JOIN {prefix}task_status t ON t.task_id = r.task_id
                JOIN {prefix}video_cache v ON v.id = (
                    SELECT cached.id FROM {prefix}video_cache cached
                    WHERE cached.platform = t.platform AND cached.media_id = t.media_id
                        AND (COALESCE(t.use_speaker_recognition, 0) = 0 OR cached.use_speaker_recognition = 1)
                    ORDER BY cached.use_speaker_recognition DESC, cached.updated_at DESC, cached.id DESC
                    LIMIT 1
                )
                WHERE r.status = 'success' AND r.view_token != '' AND r.view_token != ?
                ORDER BY COALESCE(t.completed_at, r.request_time) DESC, r.task_id DESC
            """, parameters + [current]).fetchall()

        author_key = unicodedata.normalize("NFKC", task.get("author") or "").strip().casefold()
        related, recent, matches = [], [], []
        ranked = []
        for row in candidates:
            # PostgreSQL rows are mappings with positional access; iteration yields keys.
            token, title, author, url, completed_at, files_loc = (row[index] for index in range(6))
            title = title or "未命名解读"
            if (url or "").startswith("local://collection-source/"):
                title = source_display_title(title) or title
            author = author or ""
            score = _reading_match_score(phrase, terms, title, author) if phrase else 0
            if not search or score:
                ranked.append((score, token, title, author, completed_at, files_loc))
        if search:
            ranked.sort(key=lambda row: row[0], reverse=True)

        for _, token, title, author, completed_at, files_loc in ranked:
            if not search and len(recent) >= 5 and len(related) >= 4:
                break
            same_author = bool(author_key and unicodedata.normalize("NFKC", author).strip().casefold() == author_key)
            reason = "同系列" if token in series else "同作者" if same_author else ""
            if not search and len(recent) >= 5 and (not reason or len(related) >= 4):
                continue
            # Historical tokens may be reused. Authorize the actual task selected by /view.
            try:
                require_study_source(
                    cache_manager.get_task_by_view_token(token), user_info, audit_logger, feishu_settings
                )
            except HTTPException:
                continue
            if prefix and not (Path(cache_manager.cache_dir) / files_loc).is_dir():
                continue
            item = {
                "view_token": token,
                "title": title,
                "author": author,
                "date": format_datetime_with_timezone(completed_at, "%m月%d日"),
            }
            if search:
                matches.append(item)
                if len(matches) >= 20:
                    break
            elif reason and len(related) < 4:
                related.append({**item, "reason": reason})
            elif len(recent) < 5:
                recent.append(item)
        return {"related": related, "recent": recent, "matches": matches}

    data = await run_in_threadpool(_read_history_query, read_switch)
    response.headers["Cache-Control"] = "no-store"
    return TranscribeResponse(code=200, message="获取可切换解读成功", data=data)


@router.get("/filter-options")
async def get_filter_options(user_info: dict = Depends(verify_token)):
    """Return metadata from the same owner-scoped record set as history."""
    api_key_masked = audit_logger._mask_api_key(user_info.get("api_key", ""))
    cache_manager = get_cache_manager()

    def read_options():
        with _history_connection(cache_manager) as (conn, prefix, has_marks, has_hidden):
            cte, parameters = _history_records_cte(
                user_info, api_key_masked, prefix, has_marks, has_hidden
            )
            rows = conn.execute(
                cte + "SELECT platform, author FROM history_records", parameters
            ).fetchall()
        platform_counts = Counter(row[0] for row in rows)
        authors = Counter(row[1] for row in rows if row[1])
        counts = [
            {"platform": platform, "count": count}
            for platform, count in sorted(
                platform_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        return {
            "webhooks": [],
            "platforms": [item["platform"] for item in counts],
            "platform_counts": counts,
            "authors": [value for value, _ in authors.most_common(50)],
            "total": len(rows),
            "api_key_masked": api_key_masked,
        }

    data = await run_in_threadpool(_read_history_query, read_options)
    return TranscribeResponse(code=200, message="获取过滤选项成功", data=data)


class RemoveHistoryRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=1000)


@router.post("/history/remove")
async def remove_history(
    payload: RemoveHistoryRequest,
    user_info: dict = Depends(verify_token),
):
    """Remove selected owned entries from history, retaining all source results."""
    user_id = user_info.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="无法核验历史记录归属")
    task_ids = list(dict.fromkeys(payload.task_ids))
    api_key_masked = audit_logger._mask_api_key(user_info.get("api_key", ""))
    cache_manager = get_cache_manager()

    def remove_owned_entries():
        # Authorize individual tasks rather than deduplicated history rows: older
        # submissions can share a view token and must remain individually removable.
        for task_id in task_ids:
            task = cache_manager.get_task_by_id(task_id)
            if task:
                _require_summary_owner(task, user_info, api_key_masked)
            else:
                with audit_logger._get_cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM api_audit_logs WHERE task_id = ? AND api_key_masked = ? LIMIT 1",
                        (task_id, api_key_masked),
                    )
                    if cursor.fetchone() is None:
                        raise HTTPException(status_code=403, detail="部分记录不存在或无权删除，请刷新后重试")
        cache_manager.hide_history_tasks(task_ids, user_id)

    await run_in_threadpool(remove_owned_entries)
    return TranscribeResponse(
        code=200, message="已从历史记录移除，解析结果和原始文件仍保留",
        data={"task_ids": task_ids, "removed_count": len(task_ids)},
    )


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
