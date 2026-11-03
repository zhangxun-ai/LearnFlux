"""Small owner-gated status bridge to the independent Feishu archive worker."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3


def load_archive_config() -> dict | None:
    """Read private configuration without returning credentials to a client."""
    path = Path(os.environ.get(
        "LEARNFLUX_FEISHU_ARCHIVE_CONFIG",
        str(Path.home() / ".config/learnflux-mobile/feishu/config.json"),
    )).expanduser()
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
    return config if config.get("enabled") is True else None


def delivery_state(config: dict, task: dict, *, retry: bool = False) -> dict:
    """Read one export or request a recheck, never call a remote API here."""
    result = {"state": "pending", "label": "等待同步到飞书", "document_url": None,
              "can_retry": False, "updated_at": None, "message": ""}
    if task.get("status") != "success":
        return {**result, "label": "解析完成后同步到飞书"}
    path = Path(config["state_db"]).expanduser().resolve()
    if not path.is_file():
        return result
    key = config["parent_node_token"] + ":" + task["view_token"]
    uri = path.as_uri() + ("?mode=rw" if retry else "?mode=ro")
    with sqlite3.connect(uri, uri=True, timeout=1) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM exports WHERE source_key=?", (key,)).fetchone()
        if not row:
            return result
        status = row["status"]
        if retry and status not in {"done", "conflict"}:
            # Preserve uncertain-create state: the worker must reconcile, rather
            # than creating a second document after an unknown remote result.
            connection.execute("UPDATE exports SET next_retry=0 WHERE source_key=?", (key,))
        updated = row["updated_at"]
        result["updated_at"] = datetime.fromtimestamp(updated, timezone.utc).isoformat() if updated else None
        url = row["document_url"] or ""
        if url.startswith(("https://my.feishu.cn/", "https://www.feishu.cn/")):
            result["document_url"] = url
        if status == "done":
            return {**result, "state": "done", "label": "已同步到飞书"}
        if status == "conflict":
            return {**result, "state": "needs_attention", "label": "飞书内容需要核对",
                    "message": "飞书文档已有修改或版本无法确认，已保留原文，请打开飞书核对。"}
        if status in {"uncertain", "verifying"} or row["last_error"]:
            if status == "verifying" and row["attempts"] < 3 and not row["last_error"]:
                return {**result, "state": "verifying", "label": "正在校验飞书正文"}
            message = "同步尚未完成，可以重试核对已有文档。"
            if "readback differs" in (row["last_error"] or ""):
                message = "飞书正文校验未通过，可重试核对完整内容。"
            elif "authorization" in (row["last_error"] or "").lower():
                message = "飞书授权暂时不可用，恢复授权后可以重试。"
            return {**result, "state": "needs_attention", "label": "飞书同步需要处理",
                    "can_retry": True, "message": message}
        if status in {"creating", "update_pending", "updating"}:
            return {**result, "state": "syncing", "label": "正在同步到飞书"}
        return {**result, "can_retry": True}
