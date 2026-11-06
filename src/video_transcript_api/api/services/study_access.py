"""Authorize the shared source behind study and image-diagram views."""

from fastapi import HTTPException

from ...document_sources.feishu import FeishuDocumentError, parse_feishu_url, require_feishu_access


def require_study_source(task, user_info: dict, audit_logger, feishu_settings: dict) -> dict:
    """Check durable ownership before reading any source or its cached content."""
    user_id = user_info.get("user_id")
    if not user_id or not task or not task.get("task_id"):
        raise HTTPException(status_code=404, detail="学习内容不存在")
    owner = task.get("owner_user_id")
    if owner is not None:
        allowed = owner == user_id
    elif user_info.get("is_legacy") or user_id == "legacy_user":
        allowed = True
    else:
        allowed = audit_logger.has_task_call(user_id, task["task_id"])
    if not allowed:
        raise HTTPException(status_code=404, detail="学习内容不存在")
    if str(task.get("platform") or "").lower() == "feishu" or parse_feishu_url(task.get("url") or ""):
        try:
            require_feishu_access(feishu_settings, task)
        except FeishuDocumentError:
            raise HTTPException(status_code=403, detail="当前身份未获准读取这份飞书资料") from None
    return task
