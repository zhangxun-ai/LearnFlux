import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from typing import Any, Callable, Dict, List, Optional

from ..cache.cache_manager import CacheManager
from ..llm import call_llm_api
from ..utils.logging import setup_logger
from ..utils.task_status import NON_TERMINAL_STATUSES, TaskStatus
from .repository import LearningCollectionRepository

logger = setup_logger("learning_collection_service")

DOCUMENT_EXTS = {".txt", ".md", ".markdown", ".csv", ".log", ".pdf", ".docx"}
VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
}

COLLECTION_SUMMARY_CONTEXT_TOKENS = 1_000_000
COLLECTION_SUMMARY_RESERVED_OUTPUT_TOKENS = 100_000
COLLECTION_SUMMARY_CONTEXT_SAFETY_RATIO = 0.85
COLLECTION_SUMMARY_CHARS_PER_TOKEN = 1.2
COLLECTION_MODULE_SOURCE_CHAR_LIMIT = 70000
COLLECTION_MODULE_TARGET_SOURCE_COUNT = 12


class LearningCollectionService:
    """Application service for topic-level learning workflows."""

    def __init__(
        self,
        repository: LearningCollectionRepository,
        cache_manager: CacheManager,
        summary_generator: Optional[Callable[[Dict[str, Any], List[Dict[str, Any]]], str]] = None,
        knowledge_map_generator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        source_file_dir: Optional[str] = None,
    ):
        self.repository = repository
        self.cache_manager = cache_manager
        self.summary_generator = summary_generator
        self.knowledge_map_generator = knowledge_map_generator
        self.llm_config = llm_config or {}
        self.source_file_dir = Path(source_file_dir or "./data/source_files/collection_uploads")

    def create_collection(
        self,
        title: str,
        creator_name: str,
        collection_type: str,
        goal: str = "",
        description: str = "",
        import_method: str = "",
        tags: str = "",
    ) -> Dict[str, Any]:
        return self.repository.create_collection(
            title=title,
            creator_name=creator_name,
            collection_type=collection_type,
            goal=goal,
            description=description,
            import_method=import_method,
            tags=tags,
        )

    def list_collections(
        self,
        creator_name: Optional[str] = None,
        title: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        collection_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        collections = self.repository.list_collections(
            creator_name=creator_name,
            title=title,
            date_from=date_from,
            date_to=date_to,
            collection_type=collection_type,
        )
        decorated = [self._decorate_collection_for_list(item) for item in collections]
        if status:
            decorated = [
                item for item in decorated if item.get("workflow_status") == status
            ]
        return decorated

    def get_filter_options(self) -> Dict[str, List[str]]:
        return self.repository.get_filter_options()

    def get_collection_detail(self, collection_id: str) -> Dict[str, Any]:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        detail["sources"] = [self._decorate_source(source) for source in detail["sources"]]
        detail["metrics"] = self._build_metrics(detail["sources"])
        detail["workflow_status"] = self._collection_workflow_status(detail, detail["sources"])
        detail["export_status"] = "exported" if detail.get("exported_at") else "not_exported"
        return detail

    def get_source_detail(self, collection_id: str, source_id: str) -> Dict[str, Any]:
        detail = self.get_collection_detail(collection_id)
        source = next((item for item in detail["sources"] if item["id"] == source_id), None)
        if not source:
            raise ValueError("source not found")

        task_info = self.cache_manager.get_task_by_id(source["task_id"]) or {}
        source_access = self._build_source_access(collection_id, source, task_info)
        cache_data = self.cache_manager.get_cache_by_view_token(source["view_token"])
        if not cache_data:
            return {
                **source,
                "summary": "",
                "transcript": "",
                "raw_transcript": "",
                "content_ready": False,
                "source_access": source_access,
            }

        raw_transcript = cache_data.get("transcript_data") or ""
        calibrated = cache_data.get("llm_calibrated") or ""
        transcript = calibrated or raw_transcript
        if isinstance(transcript, (dict, list)):
            transcript = str(transcript)
        if isinstance(raw_transcript, (dict, list)):
            raw_transcript = str(raw_transcript)

        return {
            **source,
            "summary": cache_data.get("llm_summary") or "",
            "transcript": transcript,
            "raw_transcript": raw_transcript,
            "content_ready": bool(transcript),
            "source_access": source_access,
        }

    def get_source_navigation_by_view_token(
        self, view_token: str
    ) -> Optional[Dict[str, Any]]:
        view_token = (view_token or "").strip()
        if not view_token:
            return None

        source_context = self.repository.get_source_with_collection_by_view_token(
            view_token
        )
        if not source_context:
            return None

        collection_id = source_context["collection_id"]
        detail = self.get_collection_detail(collection_id)
        sources = detail.get("sources", [])
        if len(sources) < 2:
            return None

        current_index = next(
            (
                index
                for index, source in enumerate(sources)
                if source.get("view_token") == view_token
            ),
            -1,
        )
        if current_index < 0:
            return None

        items = [
            {
                "id": source["id"],
                "title": source.get("title") or f"Source {index + 1}",
                "position": source.get("position"),
                "task_status": source.get("task_status"),
                "view_token": source.get("view_token") or "",
                "view_url": (
                    f"/view/{source['view_token']}" if source.get("view_token") else ""
                ),
                "is_current": index == current_index,
            }
            for index, source in enumerate(sources)
        ]
        current = items[current_index]
        collection_url = (
            f"/collections?collection_id={quote(collection_id)}"
            f"&source_id={quote(current['id'])}"
        )

        return {
            "collection": {
                "id": collection_id,
                "title": detail.get("title") or "学习合集",
                "url": collection_url,
            },
            "items": items,
            "current": current,
            "previous": items[current_index - 1] if current_index > 0 else None,
            "next": (
                items[current_index + 1]
                if current_index < len(items) - 1
                else None
            ),
            "current_number": current_index + 1,
            "total": len(items),
        }

    def add_existing_source(
        self,
        collection_id: str,
        task_id: str,
        view_token: str,
        title: str,
        source_type: str,
        position: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.repository.add_source(
            collection_id=collection_id,
            task_id=task_id,
            view_token=view_token,
            title=title,
            source_type=source_type,
            position=position,
        )

    def cancel_collection_processing(self, collection_id: str) -> Dict[str, Any]:
        detail = self.get_collection_detail(collection_id)
        canceled_count = 0
        for source in detail["sources"]:
            if source.get("task_status") not in NON_TERMINAL_STATUSES:
                continue
            self.cache_manager.update_task_status(
                source["task_id"],
                TaskStatus.CANCELED,
                error_message="用户取消合集解析",
            )
            canceled_count += 1

        updated = self.get_collection_detail(collection_id)
        return {
            "collection": updated,
            "canceled_count": canceled_count,
        }

    def source_type_for_filename(self, filename: str) -> str:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext in DOCUMENT_EXTS:
            return "document"
        if ext in VIDEO_EXTS:
            return "video"
        raise ValueError(f"unsupported file type: {ext or filename}")

    def validate_source_type_for_collection(self, collection_id: str, filename: str) -> str:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        source_type = self.source_type_for_filename(filename)
        expected = "video" if detail["collection_type"] == "video_course" else "document"
        if source_type != expected:
            raise ValueError(f"{detail['collection_type']} expects {expected} files")
        return source_type

    def generate_summary(self, collection_id: str) -> Dict[str, Any]:
        detail = self.get_collection_detail(collection_id)
        if any(source.get("task_status") != "success" for source in detail["sources"]):
            raise ValueError("all sources must be parsed before collection summary")
        sources = self._load_ready_sources(detail["sources"])
        if not sources:
            raise ValueError("no parsed sources available")

        if self.summary_generator:
            markdown = self.summary_generator(detail, sources)
        else:
            markdown = self._generate_summary_with_llm(detail, sources)
        description = _derive_collection_description(markdown)
        self.repository.save_summary(collection_id, markdown, description=description)
        return self.get_collection_detail(collection_id)

    def get_export_markdown(self, collection_id: str) -> str:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        markdown = detail.get("summary_markdown")
        if not markdown:
            raise ValueError("collection summary not generated")
        return markdown

    def mark_exported(self, collection_id: str) -> Dict[str, Any]:
        self.repository.mark_exported(collection_id)
        return self.get_collection_detail(collection_id)

    def get_source_file_path(self, collection_id: str, source_id: str) -> Optional[str]:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        source = next((item for item in detail["sources"] if item["id"] == source_id), None)
        if not source:
            raise ValueError("source not found")
        task_info = self.cache_manager.get_task_by_id(source["task_id"]) or {}
        return self._local_source_file_path(source, task_info)

    def retry_source(self, collection_id: str, source_id: str) -> Dict[str, Any]:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        source = next((item for item in detail["sources"] if item["id"] == source_id), None)
        if not source:
            raise ValueError("source not found")

        old_task = self.cache_manager.get_task_by_id(source["task_id"]) or {}
        old_status = old_task.get("status") or "queued"
        if old_status in NON_TERMINAL_STATUSES:
            raise ValueError("source is still processing")

        file_path = self._local_source_file_path(source, old_task)
        if not file_path:
            raise ValueError("源文件未保存或已被清理，无法重新解析")

        raw_url = old_task.get("url") or ""
        media_id = old_task.get("media_id") or _media_id_from_local_url(raw_url)
        if not media_id:
            raise ValueError("source media_id missing")
        display_url = raw_url or f"local://collection-source/{media_id}/{source.get('title', '')}"
        use_speaker_recognition = bool(old_task.get("use_speaker_recognition"))
        task_info = self.cache_manager.create_task(
            url=display_url,
            use_speaker_recognition=use_speaker_recognition,
            platform="generic",
            media_id=media_id,
        )
        self.repository.update_source_task(
            source_id=source_id,
            task_id=task_info["task_id"],
            view_token=task_info["view_token"],
        )
        updated = self.get_collection_detail(collection_id)
        updated_source = next(
            (item for item in updated["sources"] if item["id"] == source_id),
            None,
        )
        return {
            "collection": updated,
            "source": updated_source,
            "task_id": task_info["task_id"],
            "file_path": file_path,
            "original_name": source.get("title") or os.path.basename(file_path),
            "display_url": display_url,
            "media_id": media_id,
            "use_speaker_recognition": use_speaker_recognition,
        }

    def get_knowledge_map(
        self,
        collection_id: str,
        scope: str,
        source_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._validate_knowledge_map_scope(scope, source_id)
        collection = self.repository.get_collection_detail(collection_id)
        if not collection:
            raise ValueError("collection not found")
        return self.repository.get_knowledge_map(collection_id, scope, source_id)

    def generate_knowledge_map(
        self,
        collection_id: str,
        scope: str,
        source_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        self._validate_knowledge_map_scope(scope, source_id)
        if not force:
            cached = self.repository.get_knowledge_map(collection_id, scope, source_id)
            if cached:
                return cached

        collection = self.get_collection_detail(collection_id)
        if scope == "source":
            source = self.get_source_detail(collection_id, source_id or "")
            if source.get("task_status") != "success":
                raise ValueError("source must be parsed before knowledge map")
            if not source.get("content_ready"):
                raise ValueError("source transcript is empty")
            payload = {
                "scope": "source",
                "collection": _collection_for_knowledge_map(collection),
                "source": _source_for_knowledge_map(source),
            }
        else:
            if any(source.get("task_status") != "success" for source in collection["sources"]):
                raise ValueError("all sources must be parsed before collection knowledge map")
            source_maps = []
            for source in collection["sources"]:
                item = self.generate_knowledge_map(
                    collection_id=collection_id,
                    scope="source",
                    source_id=source["id"],
                    force=force,
                )
                source_maps.append(
                    {
                        "source": {
                            "id": source["id"],
                            "title": source.get("title", ""),
                            "position": source.get("position"),
                        },
                        "map_json": item["map_json"],
                    }
                )
            payload = {
                "scope": "collection",
                "collection": _collection_for_knowledge_map(collection),
                "summary_markdown": collection.get("summary_markdown") or "",
                "source_maps": source_maps,
            }

        map_json = self._generate_knowledge_map_json(payload)
        normalized = _normalize_knowledge_map(map_json, scope)
        model = self._knowledge_map_model()
        return self.repository.save_knowledge_map(
            collection_id=collection_id,
            scope=scope,
            source_id=source_id,
            map_json=normalized,
            model=model,
        )

    def _decorate_collection_for_list(self, collection: Dict[str, Any]) -> Dict[str, Any]:
        detail = self.repository.get_collection_detail(collection["id"]) or collection
        sources = [self._decorate_source(source) for source in detail.get("sources", [])]
        metrics = self._build_metrics(sources)
        workflow_status = self._collection_workflow_status(detail, sources)
        return {
            **collection,
            "sources": sources,
            "metrics": metrics,
            "workflow_status": workflow_status,
            "export_status": "exported" if collection.get("exported_at") else "not_exported",
        }

    def _collection_workflow_status(
        self, collection: Dict[str, Any], sources: List[Dict[str, Any]]
    ) -> str:
        if collection.get("summary_status") == "success":
            return "summarized"
        if any(source.get("task_status") == "failed" for source in sources):
            return "failed"
        if sources and all(source.get("task_status") == "success" for source in sources):
            return "ready"
        if any(source.get("task_status") == "canceled" for source in sources):
            return "stopped"
        if sources:
            return "processing"
        return "draft"

    def _decorate_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        task = self.cache_manager.get_task_by_id(source["task_id"]) or {}
        decorated = dict(source)
        task_status = task.get("status") or "queued"
        decorated["status"] = task_status
        decorated["task_status"] = task_status
        decorated["task_title"] = task.get("title")
        decorated["author"] = task.get("author")
        decorated["error_message"] = task.get("error_message")
        decorated["progress"] = task.get("progress")
        decorated["created_at"] = task.get("created_at")
        decorated["completed_at"] = task.get("completed_at")
        decorated["elapsed_seconds"] = _elapsed_seconds(
            task.get("created_at"), task.get("completed_at")
        )
        return decorated

    def _build_source_access(
        self,
        collection_id: str,
        source: Dict[str, Any],
        task_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        view_url = f"/view/{source['view_token']}" if source.get("view_token") else ""
        original_url = task_info.get("download_url") or task_info.get("url") or ""
        if original_url and not original_url.startswith("local://"):
            return {
                "kind": "online_url",
                "label": "打开源链接",
                "url": original_url,
                "view_url": view_url,
            }

        file_path = self._local_source_file_path(source, task_info)
        if file_path:
            return {
                "kind": "local_file",
                "label": "打开本地目录",
                "url": f"/api/collections/{collection_id}/sources/{source['id']}/file",
                "reveal_url": f"/api/collections/{collection_id}/sources/{source['id']}/reveal",
                "view_url": view_url,
                "filename": source.get("title", ""),
            }
        return {
            "kind": "local_missing" if original_url.startswith("local://") else "view_only",
            "label": "源内容不可用",
            "url": "",
            "view_url": view_url,
            "filename": source.get("title", ""),
        }

    def _local_source_file_path(
        self,
        source: Dict[str, Any],
        task_info: Dict[str, Any],
    ) -> Optional[str]:
        raw_url = task_info.get("url") or ""
        media_id = task_info.get("media_id") or _media_id_from_local_url(raw_url)
        if not media_id or not raw_url.startswith("local://"):
            return None
        ext = os.path.splitext(source.get("title") or raw_url)[1][:10] or ".bin"
        path = self.source_file_dir / f"{media_id}{ext}"
        return str(path) if path.exists() else None

    def _build_metrics(self, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        completed = [source for source in sources if source.get("task_status") == "success"]
        started_values = [source.get("created_at") for source in sources if source.get("created_at")]
        completed_values = [
            source.get("completed_at") for source in completed if source.get("completed_at")
        ]
        started_at = min(started_values) if started_values else None
        completed_at = max(completed_values) if completed_values else None

        return {
            "source_count": len(sources),
            "completed_count": len(completed),
            "started_at": started_at,
            "completed_at": completed_at,
            "elapsed_seconds": _elapsed_seconds(started_at, completed_at),
        }

    def _load_ready_sources(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ready = []
        for source in sources:
            cache_data = self.cache_manager.get_cache_by_view_token(source["view_token"])
            if not cache_data:
                continue
            transcript = cache_data.get("transcript_data")
            if isinstance(transcript, (dict, list)):
                transcript = str(transcript)
            transcript = (transcript or "").strip()
            if not transcript:
                continue
            ready.append(
                {
                    **source,
                    "title": source.get("title") or cache_data.get("title") or "",
                    "transcript": transcript,
                    "single_summary": cache_data.get("llm_summary") or "",
                }
            )
        return ready

    def _generate_summary_with_llm(
        self, collection: Dict[str, Any], sources: List[Dict[str, Any]]
    ) -> str:
        model = (
            self.llm_config.get("collection_summary_model")
            or self.llm_config.get("model")
            or self.llm_config.get("summary_model")
            or "gpt-4o-mini"
        )
        reasoning_effort = self.llm_config.get(
            "collection_summary_reasoning_effort",
            self.llm_config.get("summary_reasoning_effort"),
        )
        system_prompt = (
            "你是严谨的中文学习内容总教练。你的任务不是逐篇总结，而是帮助学习者在学习前"
            "建立全集主线，在学完后快速复习定位。输出必须有全局视角、章节关系和可复习的索引。"
        )
        if should_generate_collection_summary_directly(
            sources,
            collection_direct_source_char_limit(self.llm_config),
        ):
            prompt = build_collection_summary_prompt(collection, sources, content_mode="full")
            markdown = self._call_collection_llm_text(
                model,
                prompt,
                reasoning_effort,
                "collection_summary",
                system_prompt,
            )
        else:
            markdown = self._generate_layered_summary_with_llm(
                collection,
                sources,
                model,
                reasoning_effort,
                system_prompt,
            )
        return self._repair_summary_coverage(
            collection,
            sources,
            markdown,
            model,
            reasoning_effort,
            system_prompt,
        )

    def _generate_layered_summary_with_llm(
        self,
        collection: Dict[str, Any],
        sources: List[Dict[str, Any]],
        model: str,
        reasoning_effort: Optional[str],
        system_prompt: str,
    ) -> str:
        plan_prompt = build_collection_module_plan_prompt(collection, sources)
        plan_result = call_llm_api(
            model=model,
            prompt=plan_prompt,
            reasoning_effort=reasoning_effort,
            task_type="collection_module_plan",
            system_prompt=system_prompt,
            response_schema=COLLECTION_MODULE_PLAN_SCHEMA,
        )
        modules = normalize_collection_module_plan(
            getattr(plan_result, "data", None) if getattr(plan_result, "success", False) else None,
            sources,
            int(self.llm_config.get(
                "collection_module_target_source_count",
                COLLECTION_MODULE_TARGET_SOURCE_COUNT,
            )),
        )
        modules = split_oversized_collection_modules(
            modules,
            sources,
            int(self.llm_config.get(
                "collection_module_source_char_limit",
                COLLECTION_MODULE_SOURCE_CHAR_LIMIT,
            )),
        )
        module_markdowns = []
        for module in modules:
            module_prompt = build_collection_module_summary_prompt(
                collection,
                sources,
                module,
            )
            module_markdowns.append(
                {
                    **module,
                    "markdown": self._call_collection_llm_text(
                        model,
                        module_prompt,
                        reasoning_effort,
                        "collection_module_summary",
                        system_prompt,
                    ),
                }
            )
        final_prompt = build_layered_collection_summary_prompt(
            collection,
            sources,
            module_markdowns,
        )
        return self._call_collection_llm_text(
            model,
            final_prompt,
            reasoning_effort,
            "collection_summary",
            system_prompt,
        )

    def _repair_summary_coverage(
        self,
        collection: Dict[str, Any],
        sources: List[Dict[str, Any]],
        markdown: str,
        model: str,
        reasoning_effort: Optional[str],
        system_prompt: str,
    ) -> str:
        missing = missing_source_positions(markdown, sources)
        if not missing:
            return markdown
        repair_prompt = build_collection_summary_repair_prompt(
            collection,
            sources,
            markdown,
            missing,
        )
        return self._call_collection_llm_text(
            model,
            repair_prompt,
            reasoning_effort,
            "collection_summary_repair",
            system_prompt,
        )

    def _call_collection_llm_text(
        self,
        model: str,
        prompt: str,
        reasoning_effort: Optional[str],
        task_type: str,
        system_prompt: str,
    ) -> str:
        return call_llm_api(
            model=model,
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            task_type=task_type,
            system_prompt=system_prompt,
        )

    def _validate_knowledge_map_scope(self, scope: str, source_id: Optional[str]):
        if scope not in {"collection", "source"}:
            raise ValueError("scope must be collection or source")
        if scope == "source" and not source_id:
            raise ValueError("source_id is required for source knowledge map")

    def _knowledge_map_model(self) -> str:
        return self.llm_config.get("model") or self.llm_config.get("summary_model") or "gpt-4o-mini"

    def _generate_knowledge_map_json(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.knowledge_map_generator:
            return self.knowledge_map_generator(payload)

        model = self._knowledge_map_model()
        reasoning_effort = self.llm_config.get("summary_reasoning_effort")
        result = call_llm_api(
            model=model,
            prompt=build_knowledge_map_prompt(payload),
            reasoning_effort=reasoning_effort,
            task_type="knowledge_map",
            system_prompt=KNOWLEDGE_MAP_SYSTEM_PROMPT,
            response_schema=KNOWLEDGE_MAP_SCHEMA,
        )
        if not getattr(result, "success", False):
            raise ValueError(f"knowledge map generation failed: {getattr(result, 'error', '')}")
        return result.data or {}


def should_generate_collection_summary_directly(
    sources: List[Dict[str, Any]], direct_char_limit: int
) -> bool:
    return sum(len(str(source.get("transcript") or "")) for source in sources) <= direct_char_limit


def collection_direct_source_char_limit(llm_config: Dict[str, Any]) -> int:
    explicit_limit = llm_config.get("collection_direct_char_limit")
    if explicit_limit is not None:
        return max(0, int(explicit_limit))

    context_tokens = int(
        llm_config.get(
            "collection_summary_context_tokens",
            COLLECTION_SUMMARY_CONTEXT_TOKENS,
        )
    )
    reserved_output_tokens = int(
        llm_config.get(
            "collection_summary_reserved_output_tokens",
            COLLECTION_SUMMARY_RESERVED_OUTPUT_TOKENS,
        )
    )
    safety_ratio = float(
        llm_config.get(
            "collection_summary_context_safety_ratio",
            COLLECTION_SUMMARY_CONTEXT_SAFETY_RATIO,
        )
    )
    chars_per_token = float(
        llm_config.get(
            "collection_summary_chars_per_token",
            COLLECTION_SUMMARY_CHARS_PER_TOKEN,
        )
    )
    usable_tokens = max(0, context_tokens - reserved_output_tokens)
    safe_input_tokens = int(usable_tokens * max(0.0, min(safety_ratio, 1.0)))
    return int(safe_input_tokens * max(chars_per_token, 0.1))


def build_collection_summary_prompt(
    collection: Dict[str, Any],
    sources: List[Dict[str, Any]],
    content_mode: str = "compact",
) -> str:
    source_blocks = build_collection_source_blocks(sources, content_mode=content_mode)

    return f"""请基于同一专题下的多个 source，生成一篇“全系列解读”Markdown。

这份全系列解读服务两个场景：
- 课前导览：刚开始学习时，先知道这个系列讲什么、对我有什么价值、课程如何串联。
- 课后复习：学完后，快速回忆核心内容，并按复习目的定位到具体章节。

核心要求：
- 不要逐篇拼接摘要。
- 不要写泛泛而谈的课程介绍。
- 要像先给出大树树干，再说明每片叶子挂在哪个枝干上一样，先建立全局主线，再解释章节作用。
- 章节地图必须覆盖每个 source，但每个 source 只写它在全局中的作用和子内容，不要复述完整摘要。
- 章节地图不要使用“Source 1 / Source 2”作为标题，要使用原始标题或“第 N 节 + 该节作用”。
- 复习索引要按用户复习目的组织，帮助用户决定该回看哪几节。
- 成本优先：优先依据“已有单篇 AI 解读摘要”，只把“原文补充”作为校准和证据来源。

专题名称：{collection.get('title', '')}
专题类型：{collection.get('collection_type', '')}
用户目标：{collection.get('goal', '') or '先建立全局视角，再选择性深度学习和复习'}
素材数量：共 {len(sources)} 个 source。章节地图必须覆盖这 {len(sources)} 个 source，不得只覆盖前几节。

输出要求：
1. 使用 Obsidian 友好的 Markdown，包含 YAML front matter。
2. front matter 必须提供 description，20-40 个中文字，说明这个系列对学习者的核心价值。
3. 不要使用 ``` 或任何代码围栏包裹 YAML/front matter/正文。
4. 正文必须按以下 6 个二级标题输出，标题文字不要改：
   - ## 这个系列解决什么问题
   - ## 为什么值得学
   - ## 全系列主线
   - ## 章节地图
   - ## 核心框架
   - ## 复习索引
5. “这个系列解决什么问题”：用 3-5 句话提炼全集中心问题。
6. “为什么值得学”：说明学完能获得什么判断力、方法、认知框架或行动能力。
7. “全系列主线”：讲清楚课程从哪里开始、如何推进、最后落到哪里。
8. “章节地图”：按 source 顺序列出每节的全局作用、子内容、适合复看的时机。
9. “核心框架”：沉淀 3-7 个核心概念、判断标准、方法步骤或行动原则。
10. “复习索引”：按复习目的分组，例如“抓主线”“补概念”“找行动方法”“回看案例”，每组列出应回看的章节标题。

素材如下：

{chr(10).join(source_blocks)}
"""


def build_collection_source_blocks(
    sources: List[Dict[str, Any]], content_mode: str = "compact"
) -> List[str]:
    source_blocks = []
    source_count = max(1, len(sources))
    per_source_limit = max(220, min(1800, 36000 // source_count))
    for index, source in enumerate(sources, start=1):
        transcript = str(source.get("transcript") or "")
        single_summary = str(source.get("single_summary") or "").strip()
        if content_mode == "full":
            summary_excerpt = single_summary
            transcript_excerpt = transcript
        elif single_summary:
            summary_limit = max(140, int(per_source_limit * 0.75))
            transcript_limit = max(0, per_source_limit - summary_limit)
            summary_excerpt = _content_excerpt(single_summary, summary_limit)
            transcript_excerpt = _content_excerpt(transcript, transcript_limit)
        else:
            summary_excerpt = ""
            transcript_excerpt = _content_excerpt(transcript, per_source_limit)
        source_blocks.append(
            f"## Source {index}: {source.get('title', '')}\n"
            f"位置: {source.get('position') or index}\n"
            f"类型: {source.get('source_type', '')}\n"
            f"已有单篇 AI 解读摘要:\n{summary_excerpt or '无'}\n"
            f"原文补充:\n{transcript_excerpt or '无'}"
        )
    return source_blocks


COLLECTION_MODULE_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mainline", "modules"],
    "properties": {
        "mainline": {"type": "string"},
        "modules": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "role", "rationale", "source_numbers"],
                "properties": {
                    "title": {"type": "string"},
                    "role": {"type": "string"},
                    "rationale": {"type": "string"},
                    "source_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
            },
        },
    },
}


def build_collection_module_plan_prompt(
    collection: Dict[str, Any], sources: List[Dict[str, Any]]
) -> str:
    source_lines = []
    for index, source in enumerate(sources, start=1):
        single_summary = str(source.get("single_summary") or "").strip()
        transcript = str(source.get("transcript") or "")
        evidence = single_summary or transcript
        source_lines.append(
            f"{index}. {source.get('title', '')}\n"
            f"   位置: {source.get('position') or index}\n"
            f"   内容线索: {_content_excerpt(evidence, 520) or '无'}"
        )

    return f"""请先为学习合集做“作者主线与模块规划”，不要生成最终笔记。

目标：识别内容作者的讲课节奏，再按内容逻辑划分模块。不要按固定数量机械切块。

专题名称：{collection.get('title', '')}
用户目标：{collection.get('goal', '') or '建立全局视角，并能按复习目的定位章节'}
素材数量：共 {len(sources)} 个 source。

规划要求：
1. mainline 说明作者从哪里切入、如何推进、最终落到哪里。
2. modules 必须覆盖 1 到 {len(sources)} 的全部 source_numbers，不能遗漏。
3. 模块边界必须基于主题转折、方法递进、案例/练习/答疑等内容节奏。
4. 每个模块的 source_numbers 必须保持原顺序。
5. rationale 要解释为什么这些章节应该放在一起。

章节线索如下：

{chr(10).join(source_lines)}
"""


def normalize_collection_module_plan(
    plan_data: Optional[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    target_source_count: int = COLLECTION_MODULE_TARGET_SOURCE_COUNT,
) -> List[Dict[str, Any]]:
    valid_numbers = set(range(1, len(sources) + 1))
    modules = []
    used = set()
    raw_modules = []
    if isinstance(plan_data, dict) and isinstance(plan_data.get("modules"), list):
        raw_modules = plan_data["modules"]

    for index, raw in enumerate(raw_modules, start=1):
        if not isinstance(raw, dict):
            continue
        numbers = []
        for value in raw.get("source_numbers") or []:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number in valid_numbers and number not in used:
                numbers.append(number)
                used.add(number)
        if not numbers:
            continue
        modules.append(
            {
                "title": str(raw.get("title") or f"模块 {index}").strip() or f"模块 {index}",
                "role": str(raw.get("role") or "").strip(),
                "rationale": str(raw.get("rationale") or "").strip(),
                "source_numbers": sorted(numbers),
            }
        )

    if not modules:
        chunk_size = max(1, target_source_count)
        for start in range(1, len(sources) + 1, chunk_size):
            end = min(len(sources), start + chunk_size - 1)
            modules.append(
                {
                    "title": f"模块 {len(modules) + 1}：第 {start}-{end} 节",
                    "role": "按原始顺序形成的备用模块",
                    "rationale": "主线规划未返回可用模块，按相邻章节保持顺序兜底。",
                    "source_numbers": list(range(start, end + 1)),
                }
            )
        return modules

    missing = [number for number in range(1, len(sources) + 1) if number not in used]
    for number in missing:
        nearest = min(
            modules,
            key=lambda module: min(abs(existing - number) for existing in module["source_numbers"]),
        )
        nearest["source_numbers"].append(number)
        nearest["source_numbers"] = sorted(nearest["source_numbers"])
    return modules


def split_oversized_collection_modules(
    modules: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    module_char_limit: int = COLLECTION_MODULE_SOURCE_CHAR_LIMIT,
) -> List[Dict[str, Any]]:
    split_modules = []
    limit = max(1, module_char_limit)
    for module in modules:
        current_numbers = []
        current_size = 0
        part = 1
        for number in module["source_numbers"]:
            source = sources[number - 1]
            source_size = len(str(source.get("transcript") or ""))
            if current_numbers and current_size + source_size > limit:
                split_modules.append(_module_part(module, current_numbers, part))
                part += 1
                current_numbers = []
                current_size = 0
            current_numbers.append(number)
            current_size += source_size
        if current_numbers:
            split_modules.append(_module_part(module, current_numbers, part if part > 1 else 0))
    return split_modules


def _module_part(module: Dict[str, Any], source_numbers: List[int], part: int) -> Dict[str, Any]:
    title = module["title"] if part <= 0 else f"{module['title']}（第 {part} 部分）"
    return {
        **module,
        "title": title,
        "source_numbers": source_numbers,
    }


def build_collection_module_summary_prompt(
    collection: Dict[str, Any],
    sources: List[Dict[str, Any]],
    module: Dict[str, Any],
) -> str:
    module_sources = [sources[number - 1] for number in module["source_numbers"]]
    return f"""请基于完整源内容，生成这个模块的深度解读。不要生成全集最终稿。

专题名称：{collection.get('title', '')}
模块名称：{module.get('title', '')}
模块作用：{module.get('role', '')}
划分理由：{module.get('rationale', '')}
包含章节：{', '.join(str(number) for number in module.get('source_numbers', []))}

输出要求：
1. 说明这个模块在作者主线里承担什么功能。
2. 说明模块内部章节如何递进。
3. 区分主干章节、案例/练习/答疑章节和补充章节。
4. 沉淀这个模块的核心框架、判断标准或行动方法。
5. 给出适合复看的场景。

完整源内容如下：

{chr(10).join(build_collection_source_blocks(module_sources, content_mode="full"))}
"""


def build_layered_collection_summary_prompt(
    collection: Dict[str, Any],
    sources: List[Dict[str, Any]],
    modules: List[Dict[str, Any]],
) -> str:
    index_lines = []
    module_by_number = {}
    for module in modules:
        for number in module.get("source_numbers", []):
            module_by_number[number] = module.get("title", "")
    for index, source in enumerate(sources, start=1):
        index_lines.append(
            f"{index}. {source.get('title', '')} | 所属模块: {module_by_number.get(index, '未分配')}"
        )
    module_blocks = []
    for index, module in enumerate(modules, start=1):
        module_blocks.append(
            f"## 模块 {index}: {module.get('title', '')}\n"
            f"包含章节: {', '.join(str(number) for number in module.get('source_numbers', []))}\n"
            f"模块作用: {module.get('role', '')}\n"
            f"模块解读:\n{module.get('markdown', '')}"
        )

    return f"""请把模块深度解读合并成最终“全系列解读”Markdown。

专题名称：{collection.get('title', '')}
用户目标：{collection.get('goal', '') or '先建立全局视角，再选择性深度学习和复习'}
素材数量：共 {len(sources)} 个 source。章节地图和复习索引必须覆盖全部章节。

合并原则：
- 不要机械拼接模块内容，要抽象出全集主线。
- 允许按模块展示章节，但不能遗漏任何 source。
- 章节地图必须让用户知道每节在全集中的作用和适合复看的时机。
- 保留模块划分背后的作者主线节奏。

完整章节索引：
{chr(10).join(index_lines)}

模块深度解读：
{chr(10).join(module_blocks)}

输出要求：
1. 使用 Obsidian 友好的 Markdown，包含 YAML front matter。
2. front matter 必须提供 description，20-40 个中文字，说明这个系列对学习者的核心价值。
3. 不要使用 ``` 或任何代码围栏包裹 YAML/front matter/正文。
4. 正文必须按以下 6 个二级标题输出，标题文字不要改：
   - ## 这个系列解决什么问题
   - ## 为什么值得学
   - ## 全系列主线
   - ## 章节地图
   - ## 核心框架
   - ## 复习索引
"""


def missing_source_positions(markdown: str, sources: List[Dict[str, Any]]) -> List[int]:
    mentioned = mentioned_source_positions(markdown)
    missing = []
    for index, source in enumerate(sources, start=1):
        title = str(source.get("title") or "")
        position = int(source.get("position") or index)
        if position in mentioned or (title and title in markdown):
            continue
        missing.append(position)
    return missing


def mentioned_source_positions(markdown: str) -> set:
    mentioned = set()
    for match in re.finditer(r"第\s*([0-9０-９][0-9０-９\s、,，/]*)\s*节", markdown):
        for value in re.findall(r"[0-9０-９]+", match.group(1)):
            try:
                mentioned.add(int(value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))))
            except ValueError:
                continue
    return mentioned


def build_collection_summary_repair_prompt(
    collection: Dict[str, Any],
    sources: List[Dict[str, Any]],
    markdown: str,
    missing_positions: List[int],
) -> str:
    missing_set = set(missing_positions)
    missing_sources = [
        source
        for index, source in enumerate(sources, start=1)
        if int(source.get("position") or index) in missing_set
    ]
    return f"""下面这份“全系列解读”遗漏了部分章节。请保持原有结构和高质量表达，补全遗漏章节后输出完整修正版。

专题名称：{collection.get('title', '')}
遗漏章节：{', '.join(f'第 {position} 节' for position in missing_positions)}

修正要求：
1. 必须把遗漏章节补入“章节地图”。
2. 如果遗漏章节影响模块结构或复习索引，请同步修正。
3. 不要只输出补丁，要输出完整修正版 Markdown。
4. 不要使用 ``` 或任何代码围栏。

原始全系列解读：
{markdown}

遗漏章节源内容：
{chr(10).join(build_collection_source_blocks(missing_sources, content_mode="full"))}
"""


KNOWLEDGE_MAP_SYSTEM_PROMPT = (
    "你是严谨的中文学习内容结构化专家。知识地图的目的不是罗列摘要，也不是套固定模板，"
    "而是帮助学习者快速看懂内容的核心主线、它对自己有什么用，以及应该跳回哪段原文深学。"
    "请先理解材料，再输出少而精的节点。每个节点都必须有明确用户价值和证据锚点。"
)


KNOWLEDGE_MAP_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version",
        "scope",
        "title",
        "central_question",
        "user_value",
        "layout",
        "nodes",
        "edges",
        "path",
    ],
    "properties": {
        "version": {"type": "integer"},
        "scope": {"type": "string", "enum": ["collection", "source"]},
        "title": {"type": "string"},
        "central_question": {"type": "string"},
        "user_value": {"type": "string"},
        "layout": {"type": "string"},
        "nodes": {
            "type": "array",
            "minItems": 3,
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "title",
                    "summary",
                    "user_value",
                    "evidence",
                    "kind",
                    "anchor",
                    "source_ids",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "user_value": {"type": "string"},
                    "evidence": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["core", "concept", "evidence", "action"],
                    },
                    "anchor": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "label", "seconds"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["global", "video_time", "document_section", "source"],
                            },
                            "label": {"type": "string"},
                            "seconds": {"type": ["number", "null"]},
                        },
                    },
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "to", "label"],
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "label": {"type": "string"},
                },
            },
        },
        "path": {"type": "array", "items": {"type": "string"}},
    },
}


def build_knowledge_map_prompt(payload: Dict[str, Any]) -> str:
    scope = payload.get("scope")
    if scope == "collection":
        source_maps = payload.get("source_maps", [])
        return f"""请为这个学习集合生成一张“集合级知识地图”。

集合级地图要回答：
1. 这个系列真正想解决的中心问题是什么？
2. 学完这个系列，用户能获得什么判断力、方法或行动能力？
3. 每个 source 在主线中承担什么角色？它贡献了哪个关键概念、证据或行动方法？
4. source 之间的递进关系是什么？

要求：
- 不要把文件名围成一圈；节点名称必须来自内容本身。
- 节点控制在 5-9 个，优先保留最能代表系列主线的节点。
- 每个 source 至少被某个节点关联一次。
- path 字段输出推荐学习路径，使用节点 id。
- 只输出合法 JSON。

集合信息：
{json.dumps(payload.get("collection", {}), ensure_ascii=False, indent=2)}

集合总结：
{_content_excerpt(payload.get("summary_markdown") or "", 12000) or "尚未生成集合总结，请主要依据 source 地图。"}

各 source 已生成的小节地图：
{json.dumps(source_maps, ensure_ascii=False, indent=2)}
"""

    source = payload.get("source", {})
    return f"""请为这个 source 生成一张“source 级知识地图”。

source 级地图要回答：
1. 这份视频/文档最核心要讲清楚的问题是什么？
2. 对用户有什么实际帮助？
3. 哪几个节点最值得用户点击回原文深看？

要求：
- 不要使用固定模板，例如不要强行套“问题定义/利益相关者/判断标准/SOP”。
- 节点名称必须从内容语义中提炼，宁少勿多，保留 4-7 个真正关键节点。
- 如果是视频，anchor 尽量使用逐字稿中的时间点；如果没有时间点，用“片段 N”。
- evidence 必须是能支撑该节点的原文摘要或短证据。
- path 字段输出推荐复看路径，使用节点 id。
- 只输出合法 JSON。

集合信息：
{json.dumps(payload.get("collection", {}), ensure_ascii=False, indent=2)}

source 信息：
{json.dumps({key: value for key, value in source.items() if key not in {"summary", "transcript"}}, ensure_ascii=False, indent=2)}

已有 AI 解读摘要：
{_content_excerpt(source.get("summary") or "", 12000) or "无"}

逐字稿/原文：
{_content_excerpt(source.get("transcript") or "", 60000)}
"""


def _collection_for_knowledge_map(collection: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": collection.get("id"),
        "title": collection.get("title", ""),
        "creator_name": collection.get("creator_name", ""),
        "collection_type": collection.get("collection_type", ""),
        "goal": collection.get("goal", ""),
        "description": collection.get("description", ""),
        "source_count": len(collection.get("sources", []) or []),
    }


def _source_for_knowledge_map(source: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": source.get("id"),
        "title": source.get("title", ""),
        "source_type": source.get("source_type", ""),
        "position": source.get("position"),
        "view_token": source.get("view_token", ""),
        "summary": source.get("summary", ""),
        "transcript": source.get("transcript", ""),
    }


def _media_id_from_local_url(value: str) -> str:
    try:
        parsed = urlparse(value or "")
    except ValueError:
        return ""
    if parsed.scheme != "local" or parsed.netloc != "collection-source":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else ""


def _content_excerpt(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n...（内容较长，已截断）"


def _normalize_knowledge_map(map_json: Dict[str, Any], scope: str) -> Dict[str, Any]:
    if not isinstance(map_json, dict):
        raise ValueError("knowledge map must be a JSON object")

    nodes = []
    seen = set()
    for index, raw_node in enumerate(map_json.get("nodes") or [], start=1):
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id") or f"node-{index}").strip()
        if not node_id or node_id in seen:
            node_id = f"node-{index}"
        seen.add(node_id)
        anchor = raw_node.get("anchor") if isinstance(raw_node.get("anchor"), dict) else {}
        kind = raw_node.get("kind") if raw_node.get("kind") in {"core", "concept", "evidence", "action"} else "concept"
        source_ids = raw_node.get("source_ids")
        if not isinstance(source_ids, list):
            source_ids = []
        nodes.append(
            {
                "id": node_id,
                "title": str(raw_node.get("title") or f"节点 {index}").strip(),
                "summary": str(raw_node.get("summary") or "").strip(),
                "user_value": str(raw_node.get("user_value") or raw_node.get("value") or "").strip(),
                "evidence": str(raw_node.get("evidence") or "").strip(),
                "kind": kind,
                "anchor": {
                    "type": str(anchor.get("type") or "global").strip(),
                    "label": str(anchor.get("label") or "").strip(),
                    "seconds": anchor.get("seconds"),
                },
                "source_ids": [str(item) for item in source_ids if item],
            }
        )

    if not nodes:
        raise ValueError("knowledge map must contain nodes")

    node_ids = {node["id"] for node in nodes}
    edges = []
    for raw_edge in map_json.get("edges") or []:
        if isinstance(raw_edge, dict):
            from_id = str(raw_edge.get("from") or "").strip()
            to_id = str(raw_edge.get("to") or "").strip()
            label = str(raw_edge.get("label") or "").strip()
        elif isinstance(raw_edge, (list, tuple)) and len(raw_edge) >= 2:
            from_id = str(raw_edge[0]).strip()
            to_id = str(raw_edge[1]).strip()
            label = ""
        else:
            continue
        if from_id in node_ids and to_id in node_ids and from_id != to_id:
            edges.append({"from": from_id, "to": to_id, "label": label})

    path = [str(item) for item in (map_json.get("path") or []) if str(item) in node_ids]
    if not path:
        path = [node["id"] for node in nodes[: min(len(nodes), 6)]]

    return {
        "version": int(map_json.get("version") or 1),
        "scope": scope,
        "title": str(map_json.get("title") or "知识地图").strip(),
        "central_question": str(map_json.get("central_question") or "").strip(),
        "user_value": str(map_json.get("user_value") or "").strip(),
        "layout": str(map_json.get("layout") or "semantic").strip(),
        "nodes": nodes,
        "edges": edges,
        "path": path,
    }


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _elapsed_seconds(started_at: Optional[str], completed_at: Optional[str]) -> Optional[int]:
    start = _parse_datetime(started_at)
    end = _parse_datetime(completed_at)
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds()))


def _derive_collection_description(markdown: str, limit: int = 80) -> str:
    text = (markdown or "").strip()
    if not text:
        return ""

    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            stripped = line.strip()
            if stripped == "---":
                break
            if stripped.lower().startswith("description:"):
                value = stripped.split(":", 1)[1].strip()
                return _short_description(value, limit)

    in_frontmatter = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("-", "*", ">", "|")):
            continue
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in {".", "、"}:
            continue
        return _short_description(stripped, limit)
    return ""


def _short_description(value: str, limit: int) -> str:
    text = (value or "").strip().strip("\"'")
    for marker in ("**", "__", "`"):
        text = text.replace(marker, "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，,；;、 ") + "..."
