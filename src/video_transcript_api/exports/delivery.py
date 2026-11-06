"""Small owner-gated status bridge to the independent Feishu archive worker."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote


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


def diagram_delivery_state(config: dict, view_token: str, job_id: str, authorize_task, *,
                           enqueue=False, reposition=False) -> dict:
    """Read or queue a diagram for its already verified archive document."""
    path = Path(config["state_db"]).expanduser().resolve()
    if not path.is_file():
        return {"state": "waiting"}
    key = config["parent_node_token"] + ":" + view_token
    uri = path.as_uri() + ("?mode=rw" if enqueue else "?mode=ro")
    with sqlite3.connect(uri, uri=True, timeout=1) as connection:
        connection.row_factory = sqlite3.Row
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='diagram_exports'"
        ).fetchone():
            return {"state": "waiting"}
        archive = connection.execute(
            """SELECT task_id, document_id, document_url FROM exports
               WHERE source_key=? AND status IN ('done','conflict') AND document_id IS NOT NULL""",
            (key,),
        ).fetchone()
        if archive is None:
            return {"state": "waiting"}
        authorize_task(archive["task_id"])
        parameters = (key, job_id, archive["document_id"])
        if enqueue and reposition:
            connection.execute(
                """UPDATE diagram_exports SET status='writing'
                   WHERE source_key=? AND job_id=? AND document_id=? AND status='done'""",
                parameters,
            )
        elif enqueue:
            connection.execute(
                """INSERT INTO diagram_exports (source_key, job_id, document_id, status)
                   VALUES (?, ?, ?, 'queued')
                   ON CONFLICT (source_key, job_id, document_id) DO UPDATE SET
                     status=CASE diagram_exports.status WHEN 'failed' THEN 'queued'
                         WHEN 'uncertain' THEN 'writing' ELSE diagram_exports.status END""",
                parameters,
            )
        row = connection.execute(
            "SELECT * FROM diagram_exports WHERE source_key=? AND job_id=? AND document_id=?",
            parameters,
        ).fetchone()
        url = archive["document_url"] or ""
        # During a rolling restart an older worker may not have added block_id yet.
        if url and row and "block_id" in row.keys() and row["block_id"]:
            url = url.split("#", 1)[0] + "#" + quote(row["block_id"], safe="")
        return {
            "state": row["status"] if row else "ready",
            "document_url": url if url.startswith(("https://my.feishu.cn/", "https://www.feishu.cn/")) else None,
        }


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
            return {**result, "state": "done", "label": "解读已同步到飞书"}
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
