"""Adapters from existing result caches and collections to knowledge items."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Sequence
from .knowledge_markdown import (
    COLLECTION_INDEX_SOURCE_ID,
    COLLECTION_INDEX_TITLE,
    build_collection_index_bodies,
    collection_index_view_token,
)
from .knowledge_models import KnowledgeItem
from ..collections.titles import source_display_title
from ..study.transcript import normalize_transcript

class KnowledgeContentNotReady(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return "\n".join(
        str(line.get("text", "")).strip()
        for line in normalize_transcript(value)
        if str(line.get("text", "")).strip()
    ).strip()

class ObsidianKnowledgeSourceResolver:
    def __init__(
        self,
        *,
        cache_manager,
        collection_service=None,
        verify_single: Callable[[str, str], Any] | None = None,
    ):
        self.cache_manager = cache_manager
        self.collection_service = collection_service
        self.verify_single = verify_single

    def resolve_single(self, owner_user_id: str, view_token: str) -> KnowledgeItem:
        if self.verify_single:
            self.verify_single(owner_user_id, view_token)
        cache = self.cache_manager.get_cache_by_view_token(view_token)
        if not cache:
            raise KnowledgeContentNotReady("transcript_not_ready")
        raw = _text(cache.get("llm_calibrated") or cache.get("transcript_data"))
        analysis = _text(cache.get("llm_summary"))
        if not raw:
            raise KnowledgeContentNotReady("transcript_not_ready")
        if not analysis:
            raise KnowledgeContentNotReady("analysis_not_ready")

        task = cache.get("task_info") or {}
        title = source_display_title(
            str(cache.get("title") or task.get("title") or view_token).strip()
        )
        local_path = str(
            task.get("source_file_path") or cache.get("source_file_path") or ""
        )
        original_url = str(
            task.get("download_url")
            or task.get("url")
            or cache.get("url")
            or ""
        )
        if local_path and Path(local_path).is_file():
            source_kind = "local_file"
            source_access = str(Path(local_path).resolve())
        elif original_url and not original_url.startswith("local://"):
            source_kind = "online_url"
            source_access = original_url
        else:
            source_kind = "view_only"
            source_access = f"/view/{view_token}" if view_token else ""
        return KnowledgeItem(
            owner_user_id=owner_user_id,
            view_token=view_token,
            title=title,
            raw_content=raw,
            analysis_content=analysis,
            source_kind=source_kind,
            source_access=source_access,
        )

    def _build_collection_index_item(
        self,
        *,
        owner_user_id: str,
        collection_id: str,
        collection: dict[str, Any],
        creator: str,
        collection_title: str,
        directory: str,
        ready_items: Sequence[KnowledgeItem],
    ) -> KnowledgeItem:
        ready_by_id = {item.source_id: item for item in ready_items}
        chapters = []
        for source in sorted(
            collection.get("sources") or [],
            key=lambda value: (value.get("position", 0), value.get("id", "")),
        ):
            source_id = str(source.get("id") or "")
            ready_item = ready_by_id.get(source_id)
            raw_title = str(
                (ready_item.title if ready_item else None)
                or source.get("display_title")
                or source.get("title")
                or source_id
                or "未命名章节"
            )
            chapters.append(
                {
                    "position": int(source.get("position") or 0),
                    "title": source_display_title(raw_title),
                    "source_id": source_id,
                    "ready": ready_item is not None,
                    "summary": ready_item.analysis_content if ready_item else "",
                }
            )
        raw_body, analysis_body = build_collection_index_bodies(
            creator=creator,
            collection_title=collection_title,
            description=str(collection.get("description") or ""),
            summary_markdown=str(collection.get("summary_markdown") or ""),
            chapters=chapters,
        )
        return KnowledgeItem(
            owner_user_id=owner_user_id,
            view_token=collection_index_view_token(collection_id),
            title=COLLECTION_INDEX_TITLE,
            raw_content=raw_body,
            analysis_content=analysis_body,
            source_kind="collection_index",
            source_access=f"learnflux://collections/{collection_id}",
            collection_id=collection_id,
            source_id=COLLECTION_INDEX_SOURCE_ID,
            collection_title=directory,
            collection_creator=creator,
            position=0,
        )

    def resolve_collection(
        self,
        owner_user_id: str,
        collection_id: str,
        source_ids: Sequence[str] | None,
    ):
        if self.collection_service is None:
            raise ValueError("collection_service_required")
        collection = self.collection_service.get_collection_detail(collection_id)
        selected = set(
            source_ids
            if source_ids is not None
            else [source["id"] for source in collection.get("sources", [])]
        )
        items = []
        unavailable = []
        creator = str(
            collection.get("creator_name") or collection.get("creator") or ""
        ).strip()
        collection_title = str(collection.get("title") or "").strip()
        directory = "-".join(part for part in (creator, collection_title) if part)
        for source in sorted(
            collection.get("sources", []),
            key=lambda value: (value.get("position", 0), value.get("id", "")),
        ):
            if source["id"] not in selected:
                continue
            try:
                detail = self.collection_service.get_source_detail(
                    collection_id, source["id"]
                )
                raw = _text(detail.get("transcript"))
                analysis = _text(detail.get("summary"))
                if not raw:
                    raise KnowledgeContentNotReady("transcript_not_ready")
                if not analysis:
                    raise KnowledgeContentNotReady("analysis_not_ready")
                access = detail.get("source_access") or {}
                if access.get("kind") == "online_url":
                    source_access = access.get("url") or ""
                elif access.get("kind") == "local_file":
                    source_access = (
                        self.collection_service.get_source_file_path(
                            collection_id, source["id"]
                        )
                        or access.get("view_url")
                        or ""
                    )
                else:
                    source_access = access.get("view_url") or ""
                item_title = source_display_title(
                    str(
                        detail.get("display_title")
                        or detail.get("title")
                        or source.get("display_title")
                        or source.get("title")
                        or source["id"]
                    )
                )
                items.append(
                    KnowledgeItem(
                        owner_user_id=owner_user_id,
                        view_token=str(
                            detail.get("view_token")
                            or source.get("view_token")
                            or ""
                        ),
                        title=item_title,
                        raw_content=raw,
                        analysis_content=analysis,
                        source_kind=str(access.get("kind") or ""),
                        source_access=str(source_access),
                        collection_id=collection_id,
                        source_id=str(source["id"]),
                        collection_title=directory,
                        collection_creator=creator,
                        position=int(source.get("position") or 0),
                    )
                )
            except KnowledgeContentNotReady as exc:
                unavailable.append({"source_id": source["id"], "code": exc.code})

        # Always deposit a collection-level overview so AI can reason globally
        # before opening individual chapter notes.
        index_item = self._build_collection_index_item(
            owner_user_id=owner_user_id,
            collection_id=collection_id,
            collection=collection,
            creator=creator,
            collection_title=collection_title,
            directory=directory,
            ready_items=items,
        )
        return collection, [index_item, *items], unavailable
