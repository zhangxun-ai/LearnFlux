"""
审计日志路由模块

提供 API 调用记录查询、历史任务浏览和摘要预览功能。
"""

import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import get_audit_logger, get_cache_manager, get_logger
from ..services.transcription import TranscribeResponse, verify_token
from ...marks import ContentMarkRepository
from ...utils.timeutil import format_datetime_with_timezone

logger = get_logger()
audit_logger = get_audit_logger()

# 延迟导入，避免循环依赖；同时保持模块级引用供测试 mock 使用
from ..context import get_user_manager as _get_user_manager
user_manager = _get_user_manager()

router = APIRouter(prefix="/api/audit", tags=["audit"])


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


@router.get("/history")
async def get_history(
    start_date: Optional[str] = Query(None, description="开始日期，ISO格式 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期，ISO格式 YYYY-MM-DD"),
    webhook: Optional[str] = Query(None, description="webhook地址精确过滤"),
    platform: Optional[str] = Query(None, description="平台过滤: youtube/bilibili/xiaoyuzhou/xiaohongshu/douyin"),
    author: Optional[str] = Query(None, description="频道/作者过滤，支持逗号分隔多选"),
    q: Optional[str] = Query(None, description="关键词搜索：匹配标题、频道名、视频URL"),
    status: Optional[str] = Query(None, description="任务状态过滤，默认只显示 success（已完成）"),
    marked: bool = Query(False, description="仅返回已标记精华的任务"),
    limit: int = Query(20, ge=1, le=10000, description="每页条数，客户端已读过滤时传大值"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    user_info: dict = Depends(verify_token),
):
    """
    查询任务提交历史（跨库 JOIN：audit.db + cache.db）。

    默认只返回已完成（completed）的任务，支持按日期、webhook、平台、频道过滤。
    """
    api_key = user_info.get("api_key", "")
    api_key_masked = audit_logger._mask_api_key(api_key)
    cache_manager = get_cache_manager()
    cache_db_path = str(cache_manager.db_path)
    marks_repository = ContentMarkRepository(db_path=cache_db_path)
    marks_repository.close()

    # 构建 WHERE 条件
    conditions = [
        "a.api_key_masked = ?",
        "COALESCE(a.task_id, t.task_id) IS NOT NULL",
    ]
    params: list = [api_key_masked]

    if webhook:
        conditions.append("a.wechat_webhook = ?")
        params.append(webhook)

    if start_date:
        conditions.append("a.request_time >= ?")
        params.append(f"{start_date} 00:00:00")

    if end_date:
        conditions.append("a.request_time <= ?")
        params.append(f"{end_date} 23:59:59")

    # 平台和作者过滤来自 cache.db，只有在 JOIN 成功时才有效
    cache_conditions = []
    if platform:
        cache_conditions.append("t.platform = ?")
        params.append(platform)

    if author:
        author_list = [a.strip() for a in author.split(",") if a.strip()]
        if len(author_list) == 1:
            cache_conditions.append("t.author = ?")
            params.append(author_list[0])
        elif author_list:
            placeholders = ",".join("?" * len(author_list))
            cache_conditions.append(f"t.author IN ({placeholders})")
            params.extend(author_list)

    # status 默认 'success'（cache.db 中完成任务的实际值）；传 'all' 则不过滤
    effective_status = status or "success"
    if effective_status != "all":
        cache_conditions.append("COALESCE(t.status, 'unknown') = ?")
        params.append(effective_status)

    # 关键词搜索：LIKE 匹配标题、频道名、视频URL
    # 注意：加入 cache_conditions 而非 conditions，保证 params 顺序与 SQL 占位符一致
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        cache_conditions.append(
            "(COALESCE(t.title, '') LIKE ? OR COALESCE(t.author, '') LIKE ? OR COALESCE(a.video_url, '') LIKE ?)"
        )
        params.extend([pattern, pattern, pattern])

    if marked:
        cache_conditions.append("m.id IS NOT NULL")

    where_clause = " AND ".join(conditions + cache_conditions)

    history_cte = f"""
        WITH filtered AS (
            SELECT
                a.id AS audit_id,
                COALESCE(a.task_id, t.task_id) AS task_id,
                COALESCE(NULLIF(a.video_url, ''), t.url) AS video_url,
                a.wechat_webhook,
                COALESCE(t.created_at, a.request_time) AS request_time,
                a.api_key_masked,
                t.view_token,
                t.title,
                t.author,
                t.platform,
                t.status,
                CASE WHEN m.id IS NULL THEN 0 ELSE 1 END AS is_marked,
                COALESCE(t.view_token, a.task_id, t.task_id) AS dedupe_key,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(t.view_token, a.task_id, t.task_id)
                    ORDER BY
                        COALESCE(t.created_at, a.request_time) DESC,
                        CASE WHEN a.video_url IS NOT NULL AND a.video_url != '' THEN 0 ELSE 1 END,
                        a.request_time DESC,
                        a.id DESC
                ) AS rn
            FROM api_audit_logs a
            LEFT JOIN cache.task_status t
                ON a.task_id = t.task_id
                OR (
                    a.task_id IS NULL
                    AND a.video_url IS NOT NULL
                    AND a.video_url != ''
                    AND a.video_url = t.url
                )
            LEFT JOIN cache.content_marks m
                ON m.owner_type = 'transcript'
               AND m.owner_id = t.view_token
               AND m.user_key = a.api_key_masked
            WHERE {where_clause}
        )
    """

    base_sql = history_cte + """
        SELECT
            task_id,
            video_url,
            wechat_webhook,
            request_time,
            api_key_masked,
            view_token,
            title,
            author,
            platform,
            status,
            is_marked
        FROM filtered
        WHERE rn = 1
        ORDER BY request_time DESC, audit_id DESC
    """

    count_sql = history_cte + """
        SELECT COUNT(*)
        FROM filtered
        WHERE rn = 1
    """

    def _run_query():
        # 每次请求新建独立连接（不复用 thread-local），ATTACH 是连接级操作
        conn = sqlite3.connect(audit_logger.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(f"ATTACH DATABASE ? AS cache", (cache_db_path,))
            conn.execute("PRAGMA cache.query_only = 1")

            cur = conn.cursor()
            cur.execute(count_sql, params)
            total = cur.fetchone()[0]

            cur.execute(base_sql + " LIMIT ? OFFSET ?", params + [limit, offset])
            rows = cur.fetchall()

            items = []
            for row in rows:
                request_time = row[3]
                items.append({
                    "task_id": row[0],
                    "video_url": row[1],
                    "wechat_webhook": row[2],
                    "request_time": request_time,
                    "request_time_display": format_datetime_with_timezone(
                        request_time, "%Y-%m-%d %H:%M"
                    ),
                    "api_key_masked": row[4],
                    "view_token": row[5],
                    "title": row[6],
                    "author": row[7],
                    "platform": row[8],
                    "status": row[9] or "unknown",
                    "is_marked": bool(row[10]),
                })
            return total, items
        finally:
            conn.close()

    # 锁竞争重试一次（50ms 间隔）
    try:
        total, items = _run_query()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            logger.warning("history query: database locked, retrying in 50ms")
            time.sleep(0.05)
            try:
                total, items = _run_query()
            except sqlite3.OperationalError as e2:
                logger.error("history query: database still locked after retry: %s", e2)
                raise HTTPException(status_code=503, detail="服务暂时不可用，请稍后重试")
        else:
            logger.exception("history query failed: %s", e)
            raise HTTPException(status_code=500, detail=f"查询失败: {e}")
    except Exception as exc:
        logger.exception("history query unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}")

    return TranscribeResponse(
        code=200,
        message="获取历史记录成功",
        data={
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "api_key_masked": api_key_masked,
        },
    )


@router.get("/filter-options")
async def get_filter_options(user_info: dict = Depends(verify_token)):
    """
    获取当前 API Key 下历史出现的所有 webhook、平台、频道名称，用于前端过滤下拉框。
    各选项按出现频次倒序，最多返回 50 条。
    """
    api_key = user_info.get("api_key", "")
    api_key_masked = audit_logger._mask_api_key(api_key)
    cache_manager = get_cache_manager()
    cache_db_path = str(cache_manager.db_path)

    def _run_query():
        conn = sqlite3.connect(audit_logger.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute("ATTACH DATABASE ? AS cache", (cache_db_path,))
            conn.execute("PRAGMA cache.query_only = 1")
            cur = conn.cursor()

            # 历史 webhook 列表（按频次倒序）
            cur.execute("""
                SELECT wechat_webhook, COUNT(*) as cnt
                FROM api_audit_logs
                WHERE api_key_masked = ? AND wechat_webhook IS NOT NULL
                GROUP BY wechat_webhook
                ORDER BY cnt DESC
                LIMIT 50
            """, (api_key_masked,))
            webhooks = [row[0] for row in cur.fetchall()]

            # 历史平台列表
            cur.execute("""
                SELECT t.platform, COUNT(*) as cnt
                FROM api_audit_logs a
                LEFT JOIN cache.task_status t ON a.task_id = t.task_id
                WHERE a.api_key_masked = ? AND t.platform IS NOT NULL
                GROUP BY t.platform
                ORDER BY cnt DESC
            """, (api_key_masked,))
            platforms = [row[0] for row in cur.fetchall()]

            # 历史频道/作者列表（按频次倒序）
            cur.execute("""
                SELECT t.author, COUNT(*) as cnt
                FROM api_audit_logs a
                LEFT JOIN cache.task_status t ON a.task_id = t.task_id
                WHERE a.api_key_masked = ? AND t.author IS NOT NULL AND t.author != ''
                GROUP BY t.author
                ORDER BY cnt DESC
                LIMIT 50
            """, (api_key_masked,))
            authors = [row[0] for row in cur.fetchall()]

            return webhooks, platforms, authors
        finally:
            conn.close()

    try:
        webhooks, platforms, authors = _run_query()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            time.sleep(0.05)
            try:
                webhooks, platforms, authors = _run_query()
            except sqlite3.OperationalError as e2:
                logger.error("filter-options: database still locked: %s", e2)
                raise HTTPException(status_code=503, detail="服务暂时不可用，请稍后重试")
        else:
            logger.exception("filter-options query failed: %s", e)
            raise HTTPException(status_code=500, detail=f"查询失败: {e}")
    except Exception as exc:
        logger.exception("filter-options unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}")

    return TranscribeResponse(
        code=200,
        message="获取过滤选项成功",
        data={
            "webhooks": webhooks,
            "platforms": platforms,
            "authors": authors,
        },
    )


@router.get("/summary")
async def get_task_summary(
    view_token: str = Query(..., description="任务的 view_token"),
    user_info: dict = Depends(verify_token),
):
    """
    获取任务摘要预览（前 300 字），用于历史页面 hover 展示。
    校验 view_token 归属当前 API Key，防止跨用户读取。
    """
    api_key = user_info.get("api_key", "")
    api_key_masked = audit_logger._mask_api_key(api_key)
    cache_manager = get_cache_manager()

    # 通过 view_token 查任务信息
    task_info = cache_manager.get_task_by_view_token(view_token)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 校验归属：task_info 中暂无 api_key_masked，通过 audit_log 反查
    # 若无法查到关联记录，允许访问（兼容旧数据）
    task_id = task_info.get("task_id")
    if task_id and api_key_masked:
        try:
            with audit_logger._get_cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM api_audit_logs WHERE task_id = ? AND api_key_masked = ? LIMIT 1",
                    (task_id, api_key_masked),
                )
                if not cursor.fetchone():
                    # 有历史记录但不属于该 key
                    cursor.execute(
                        "SELECT 1 FROM api_audit_logs WHERE task_id = ? LIMIT 1",
                        (task_id,),
                    )
                    if cursor.fetchone():
                        raise HTTPException(status_code=403, detail="无权访问该任务")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("summary auth check failed, allowing access: %s", e)

    # 任务未完成（cache.db 中完成的状态值为 'success'）
    task_status = task_info.get("status", "")
    if task_status not in ("success",):
        return TranscribeResponse(
            code=202,
            message="任务处理中",
            data={"summary": "", "status": task_status},
        )

    # 获取摘要：复用现有 get_view_data_by_token 逻辑
    try:
        view_data = cache_manager.get_view_data_by_token(view_token)
        if not view_data or view_data.get("status") not in ("success",):
            return TranscribeResponse(
                code=200,
                message="摘要不可用",
                data={"summary": "", "status": view_data.get("status") if view_data else "unknown"},
            )

        raw_summary = view_data.get("summary", "")
        # 取前 300 个 Unicode 字符
        preview = raw_summary[:300] if raw_summary else ""

        return TranscribeResponse(
            code=200,
            message="获取摘要成功",
            data={"summary": preview, "status": "success"},
        )
    except Exception as exc:
        logger.exception("get summary failed for view_token=%s: %s", view_token, exc)
        raise HTTPException(status_code=500, detail=f"获取摘要失败: {exc}")
