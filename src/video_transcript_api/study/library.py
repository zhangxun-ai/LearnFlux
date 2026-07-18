from pathlib import Path
from typing import Any

from .source_files import describe_study_source, find_study_source_file


class StudyLibraryService:
    """Build the authenticated, playable content list used by Study."""

    def __init__(self, cache_manager, audit_logger, source_root, collection_service=None):
        self.cache_manager = cache_manager
        self.audit_logger = audit_logger
        self.source_root = Path(source_root)
        self.collection_service = collection_service

    def list(
        self,
        *,
        kind: str,
        user_id: str,
        q: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if kind == "collection":
            return self.list_collections(user_id=user_id, q=q, limit=limit, offset=offset)
        return self.list_single(user_id=user_id, q=q, limit=limit, offset=offset)

    def list_single(
        self,
        user_id: str,
        q: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = (q or "").strip().casefold()
        items = []
        seen = set()
        for call in self.audit_logger.get_recent_calls(user_id=user_id, limit=10000):
            task_id = call.get("task_id")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            task = self.cache_manager.get_task_by_id(task_id) or {}
            item = self._single_item(task)
            if not item:
                continue
            haystack = f"{item['title']} {item['author']}".casefold()
            if query and query not in haystack:
                continue
            items.append(item)

        return {
            "items": items[offset:offset + limit],
            "total": len(items),
        }

    def list_collections(
        self,
        *,
        user_id: str,
        q: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not self.collection_service:
            return {"items": [], "total": 0}
        return self.collection_service.list_study_collections(
            owner_user_id=user_id,
            q=q,
            limit=limit,
            offset=offset,
        )

    def _single_item(self, task: dict[str, Any]) -> dict[str, Any] | None:
        view_token = task.get("view_token") or ""
        if not view_token:
            return None
        source_file = find_study_source_file(
            source_root=self.source_root,
            media_id=task.get("media_id") or "",
            title=task.get("title") or "",
            url=task.get("url") or "",
            source_file_path=task.get("source_file_path") or "",
        )
        if source_file is None:
            return None
        source = describe_study_source(
            url=task.get("url") or "",
            title=task.get("title") or source_file.name,
            source_file=source_file,
        )
        if source["kind"] not in {"audio", "video"}:
            return None
        view_data = self.cache_manager.get_view_data_by_token(view_token) or {}
        status = task.get("status") or "queued"
        return {
            "view_token": view_token,
            "title": task.get("title") or source["filename"],
            "author": task.get("author") or "",
            "source_kind": source["kind"],
            "media_type": source["media_type"],
            "state": "ready" if status == "success" else status,
            "progress": task.get("progress") or {},
            "transcript_count": len(view_data.get("transcript") or []),
            "ai_ready": bool(view_data.get("summary")),
            "created_at": task.get("created_at"),
            "study_available": True,
            "study_url": f"/study/{view_token}",
        }
