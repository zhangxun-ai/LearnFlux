"""Authenticated Feishu delivery state; transcription never waits for export."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from ..context import get_cache_manager, get_user_manager
from ..services.transcription import TranscribeResponse, verify_token
from ...exports.delivery import delivery_state, load_archive_config
from .audit import _require_summary_owner, audit_logger

router = APIRouter(prefix="/api/tasks", tags=["delivery"])


def archive_config_for_user(user_id: str) -> dict | None:
    try:
        config = load_archive_config()
        owner = next((user.get("user_id") for user in get_user_manager().list_all_users()
                      if config and user.get("name") == config["api_user_name"]
                      and user.get("enabled", True)), None)
        if owner and owner == user_id:
            return config
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail="暂时无法读取飞书归档配置") from exc
    return None


def _read_delivery(task_id: str, user_info: dict, retry: bool = False) -> dict:
    task = get_cache_manager().get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_summary_owner(task, user_info, audit_logger._mask_api_key(user_info.get("api_key", "")))
    try:
        config = archive_config_for_user(user_info["user_id"])
        if not config:
            return {"state": "unavailable", "label": "", "document_url": None,
                    "can_retry": False, "updated_at": None, "message": ""}
        return delivery_state(config, task, retry=retry)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="暂时无法读取飞书同步状态，请稍后重试") from exc


@router.get("/{task_id}/delivery/feishu")
async def get_feishu_delivery(task_id: str, user_info: dict = Depends(verify_token)):
    data = await run_in_threadpool(_read_delivery, task_id, user_info)
    return TranscribeResponse(code=200, message="获取飞书同步状态成功", data=data)


@router.post("/{task_id}/delivery/feishu/retry")
async def retry_feishu_delivery(task_id: str, user_info: dict = Depends(verify_token)):
    data = await run_in_threadpool(_read_delivery, task_id, user_info, True)
    return TranscribeResponse(code=200, message="已请求重新核对飞书同步状态", data=data)
