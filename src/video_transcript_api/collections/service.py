import os
from datetime import datetime, timezone
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
        llm_config: Optional[Dict[str, Any]] = None,
    ):
        self.repository = repository
        self.cache_manager = cache_manager
        self.summary_generator = summary_generator
        self.llm_config = llm_config or {}

    def create_collection(
        self, title: str, collection_type: str, goal: str = ""
    ) -> Dict[str, Any]:
        return self.repository.create_collection(title, collection_type, goal)

    def list_collections(self) -> List[Dict[str, Any]]:
        return self.repository.list_collections()

    def get_collection_detail(self, collection_id: str) -> Dict[str, Any]:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        detail["sources"] = [self._decorate_source(source) for source in detail["sources"]]
        detail["metrics"] = self._build_metrics(detail["sources"])
        return detail

    def get_source_detail(self, collection_id: str, source_id: str) -> Dict[str, Any]:
        detail = self.get_collection_detail(collection_id)
        source = next((item for item in detail["sources"] if item["id"] == source_id), None)
        if not source:
            raise ValueError("source not found")

        cache_data = self.cache_manager.get_cache_by_view_token(source["view_token"])
        if not cache_data:
            return {
                **source,
                "summary": "",
                "transcript": "",
                "raw_transcript": "",
                "content_ready": False,
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
        self.repository.save_summary(collection_id, markdown)
        return self.get_collection_detail(collection_id)

    def get_export_markdown(self, collection_id: str) -> str:
        detail = self.repository.get_collection_detail(collection_id)
        if not detail:
            raise ValueError("collection not found")
        markdown = detail.get("summary_markdown")
        if not markdown:
            raise ValueError("collection summary not generated")
        return markdown

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
1. 先给出系列整体主题，不要逐篇拼接。
2. 提炼核心概念。
3. 说明知识结构。
4. 说明每个章节/视频/文档在整体中的作用。
5. 说明内容之间的递进关系。
6. 提炼关键论点和证据。
7. 生成适合复习的精华笔记。
8. 沉淀 SOP / 判断标准 / 行动清单。
9. 使用 Obsidian 友好的 Markdown，包含 YAML front matter。

素材如下：

{chr(10).join(source_blocks)}
"""


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
