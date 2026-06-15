import os
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional

from ..cache.cache_manager import CacheManager
from ..llm import call_llm_api
from ..utils.logging import setup_logger
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
        model = self.llm_config.get("model") or self.llm_config.get("summary_model") or "gpt-4o-mini"
        reasoning_effort = self.llm_config.get("summary_reasoning_effort")
        prompt = build_collection_summary_prompt(collection, sources)
        system_prompt = (
            "你是严谨的中文学习内容整理专家。你的任务是把同一专题下的多个 source "
            "综合成可复用的方法论、判断标准、SOP 和行动清单。不要逐篇拼接摘要。"
        )
        return call_llm_api(
            model=model,
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            task_type="collection_summary",
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


def build_collection_summary_prompt(
    collection: Dict[str, Any], sources: List[Dict[str, Any]]
) -> str:
    source_blocks = []
    total_limit = 60000
    used = 0
    for index, source in enumerate(sources, start=1):
        transcript = source["transcript"]
        remaining = max(0, total_limit - used)
        if remaining <= 0:
            break
        excerpt = transcript[: min(len(transcript), remaining, 10000)]
        used += len(excerpt)
        source_blocks.append(
            f"## Source {index}: {source.get('title', '')}\n"
            f"类型: {source.get('source_type', '')}\n"
            f"已有单篇总结: {source.get('single_summary', '') or '无'}\n"
            f"原文/逐字稿:\n{excerpt}"
        )

    return f"""请基于同一专题下的多个 source，生成适合 Obsidian 沉淀的 Markdown。

专题名称：{collection.get('title', '')}
专题类型：{collection.get('collection_type', '')}
用户目标：{collection.get('goal', '') or '沉淀为可复用的方法论、判断标准、SOP 和行动清单'}

输出要求：
1. 在 YAML front matter 中提供 description，20-40 个中文字，简短说明这个专题是干嘛的。
2. 先给出系列整体主题，不要逐篇拼接。
3. 提炼核心概念。
4. 说明知识结构。
5. 说明每个章节/视频/文档在整体中的作用。
6. 说明内容之间的递进关系。
7. 提炼关键论点和证据。
8. 生成适合复习的精华笔记。
9. 沉淀 SOP / 判断标准 / 行动清单。
10. 使用 Obsidian 友好的 Markdown，包含 YAML front matter。

素材如下：

{chr(10).join(source_blocks)}
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
