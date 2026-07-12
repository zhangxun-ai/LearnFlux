"""Generation orchestration for visual learning documents."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from typing import Any, Callable

from pydantic import ValidationError

from ..llm import StructuredResult, call_llm_api
from .prompts import build_outline_prompt, build_visual_prompt
from .progress import compose_workflow_progress
from .repository import VisualLearningRepository
from .schemas import (
    DIAGRAM_TYPES,
    DOCUMENT_TYPES,
    THEME_IDS,
    SourceReference,
    VisualDocument,
    VisualOutline,
)
from .source_resolver import (
    StudySourceResolver,
    VisualLearningSource,
    VisualLearningSourceNotFound,
    VisualLearningSourceNotReady,
)


normalization_logger = logging.getLogger(__name__)


class VisualLearningGenerationError(RuntimeError):
    """Raised when a generated document cannot cross the validation boundary."""


def _log_resize(path: str, old_length: int, new_length: int) -> None:
    normalization_logger.info(
        "Normalized %s length %s -> %s",
        path,
        old_length,
        new_length,
    )


def normalize_visual_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Clamp model output before strict Pydantic validation without logging content."""
    normalized = copy.deepcopy(payload)

    def trim_text(value: Any, limit: int, path: str) -> Any:
        if not isinstance(value, str) or len(value) <= limit:
            return value
        _log_resize(path, len(value), limit)
        return value[:limit]

    def trim_list(node: dict, key: str, limit: int, path: str) -> None:
        value = node.get(key)
        if isinstance(value, list) and len(value) > limit:
            _log_resize(f"{path}.{key}" if path else key, len(value), limit)
            node[key] = value[:limit]

    def walk(value: Any, path: str = "", parent_key: str = "") -> None:
        if isinstance(value, dict):
            block_type = value.get("type")
            block_limits = {
                "hero_summary": {"points": 5},
                "concept_chain": {"items": 10},
                "process_flow": {"steps": 10},
                "comparison": {"columns": 4},
                "hierarchy": {"nodes": 16},
                "timeline": {"events": 12},
                "concept_grid": {"items": 12},
                "mind_map": {"branches": 8},
                "review_questions": {"questions": 8},
            }.get(block_type, {})
            for key, limit in block_limits.items():
                trim_list(value, key, limit, path)
            trim_list(value, "source_ref_ids", 16, path)
            if "diagram_recommendations" in value:
                recommendations = value.get("diagram_recommendations")
                if isinstance(recommendations, list):
                    recommendations.sort(
                        key=lambda item: (
                            item.get("score", 0) if isinstance(item, dict) else 0
                        ),
                        reverse=True,
                    )
                trim_list(value, "diagram_recommendations", 3, path)
            if parent_key == "columns":
                trim_list(value, "items", 8, path)
            if parent_key == "branches":
                trim_list(value, "children", 6, path)

            for key in list(value):
                item_path = f"{path}.{key}" if path else key
                item = value[key]
                if key in {"label", "time_label", "center_label", "headline"}:
                    value[key] = trim_text(item, 40, item_path)
                elif key == "title":
                    value[key] = trim_text(item, 160 if not path else 40, item_path)
                elif key in {"description", "summary", "answer", "rationale", "text", "subtitle"}:
                    value[key] = trim_text(item, 240, item_path)
                elif key in {"question", "learning_goal"}:
                    value[key] = trim_text(item, 160, item_path)
                elif isinstance(item, (dict, list)):
                    walk(item, item_path, key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                item_path = f"{path}[{index}]"
                if isinstance(item, str) and parent_key in {"points", "children"}:
                    value[index] = trim_text(item, 40, item_path)
                else:
                    walk(item, item_path, parent_key)

    walk(normalized)
    return normalized


class VisualLearningService:
    """Generate, validate and version visual learning documents."""

    def __init__(
        self,
        repository: VisualLearningRepository,
        source_resolver: StudySourceResolver,
        llm_callable: Callable[..., Any] = call_llm_api,
        llm_config: dict[str, Any] | None = None,
        collection_source_resolver: Any | None = None,
    ):
        self.repository = repository
        self.source_resolver = source_resolver
        self.collection_source_resolver = collection_source_resolver
        self.llm_callable = llm_callable
        self.llm_config = llm_config or {}

    def generate_study(
        self,
        view_token: str,
        document_type: str,
        style: str = "study-notes",
        diagram_type: str = "auto",
        force: bool = False,
    ) -> dict[str, Any]:
        source, record, model = self._prepare(
            view_token=view_token,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
            force=force,
        )
        return self._generate_record(
            source,
            record,
            model,
            document_type,
            style,
            diagram_type,
        )

    def generate_collection(
        self,
        collection_id: str,
        document_type: str,
        style: str = "study-notes",
        diagram_type: str = "auto",
        force: bool = False,
    ) -> dict[str, Any]:
        source, record, model = self._prepare_owner(
            owner_type="collection",
            owner_id=collection_id,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
            force=force,
        )
        return self._generate_record(
            source,
            record,
            model,
            document_type,
            style,
            diagram_type,
        )

    def _generate_record(
        self,
        source: VisualLearningSource,
        record: dict[str, Any],
        model: str,
        document_type: str,
        style: str,
        diagram_type: str,
    ) -> dict[str, Any]:
        if record.get("status") in {"success", "generating"}:
            return record

        generation_token = self.repository.claim_generation(
            record["id"],
            previous_token=record.get("generation_token") or "",
        )
        if generation_token is None:
            return self.repository.get_document(record["id"]) or record

        try:
            long_diagram = self._is_long_diagram(source, document_type)
            outline = None
            evidence_by_section: dict[str, list[SourceReference]] = {}
            source_refs = source.source_refs
            evidence_text = ""
            if long_diagram:
                self._update_progress(
                    record["id"], generation_token, "analyzing_outline", "正在建立全文知识架构", 50
                )
                outline = self._call_outline(source, self._outline_model())
                self._update_progress(
                    record["id"], generation_token, "selecting_evidence", "正在回查原文依据", 65
                )
                evidence_by_section = self._select_evidence(source, outline)
                if len(evidence_by_section) < 4:
                    raise VisualLearningGenerationError(
                        "fewer than four outline sections have source evidence"
                    )
                self._update_progress(
                    record["id"],
                    generation_token,
                    "selecting_evidence",
                    "正在回查原文依据",
                    65,
                    basis="completed_sections",
                    completed_units=len(evidence_by_section),
                    total_units=len(outline.sections),
                )
                source_refs = self._flatten_evidence_refs(evidence_by_section)
                evidence_text = self._render_evidence(source, evidence_by_section)
            elif document_type == "full_note":
                allowed_ids = {
                    ref_id
                    for section in source.interpretation_sections
                    for ref_id in section.source_ref_ids
                }
                source_refs = [
                    ref for ref in source.source_refs if ref.id in allowed_ids
                ]
            self._update_progress(
                record["id"], generation_token, "generating_visual", "正在生成多页图解" if long_diagram else "正在生成图解", 75
            )
            previous_success = self.repository.get_latest(
                source.owner_type,
                source.owner_id,
                document_type,
                successful_only=True,
            )
            correction = ""
            attempt_count = 2
            for attempt in range(attempt_count):
                if (
                    document_type == "overview"
                    and previous_success is None
                    and attempt == 1
                ):
                    raw_document = self._build_overview_fallback(source)
                else:
                    raw_document = self._call_llm(
                        source,
                        document_type,
                        diagram_type,
                        model,
                        outline=outline,
                        evidence=evidence_text,
                        correction=correction,
                    )
                raw_document["source_refs"] = [
                    ref.model_dump(mode="json") for ref in source_refs
                ]
                raw_document["recommended_style"] = style
                if document_type == "diagram" and diagram_type != "auto":
                    raw_document["selected_diagram_type"] = diagram_type
                normalized = normalize_visual_document(raw_document)
                pages = normalized.get("pages")
                if (
                    document_type == "overview"
                    and isinstance(pages, list)
                    and len(pages) > 1
                    and isinstance(pages[0], dict)
                    and pages[0].get("id") == "overview"
                ):
                    _log_resize("pages", len(pages), 1)
                    normalized["pages"] = pages[:1]
                try:
                    self._validate_requested_shape(normalized, document_type, outline)
                    self._filter_source_refs(normalized, source)
                    if outline is not None:
                        self._validate_outline_coverage(
                            normalized,
                            outline,
                            evidence_by_section,
                        )
                    elif document_type == "full_note":
                        self._validate_full_note_alignment(
                            normalized,
                            source.interpretation_sections,
                        )
                    elif document_type == "overview":
                        self._validate_overview_coverage(
                            normalized,
                            source.interpretation_sections,
                            source.owner_type,
                        )
                    document = VisualDocument.model_validate(normalized)
                    if document.document_type != document_type:
                        raise VisualLearningGenerationError(
                            "generated document type mismatch"
                        )
                    break
                except (VisualLearningGenerationError, ValidationError) as exc:
                    correction_message = self._generation_correction(exc)
                    retryable = (
                        attempt == 0
                        and previous_success is None
                        and document_type in {"overview", "full_note", "diagram"}
                    )
                    if not retryable:
                        raise
                    correction = correction_message or "generated structure is invalid"
            self._update_progress(
                record["id"], generation_token, "validating", "正在校验结构与原文引用", 95
            )
            saved = self.repository.save_success(
                record["id"],
                generation_token,
                document.model_dump(mode="json"),
                model,
            )
            if not saved:
                return self.repository.get_document(record["id"]) or record
        except Exception as exc:  # Boundary: model output and remote provider are untrusted.
            error_message = self._safe_error(exc)
            self.repository.save_failure(record["id"], generation_token, error_message)
        return self.repository.get_document(record["id"]) or record

    def prepare_study_generation(
        self,
        view_token: str,
        document_type: str,
        style: str = "study-notes",
        diagram_type: str = "auto",
        force: bool = False,
    ) -> dict[str, Any]:
        """Create or reuse a generation record without calling the LLM."""
        _, record, _ = self._prepare(
            view_token=view_token,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
            force=force,
        )
        return record

    def prepare_collection_generation(
        self,
        collection_id: str,
        document_type: str,
        style: str = "study-notes",
        diagram_type: str = "auto",
        force: bool = False,
    ) -> dict[str, Any]:
        """Create or reuse a collection generation record without calling the LLM."""
        _, record, _ = self._prepare_owner(
            owner_type="collection",
            owner_id=collection_id,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
            force=force,
        )
        return record

    def generate_prepared_study(
        self,
        document_id: str,
        view_token: str,
        document_type: str,
        style: str = "study-notes",
        diagram_type: str = "auto",
    ) -> dict[str, Any]:
        """Generate the exact record prepared by an asynchronous API request."""
        return self._generate_prepared_owner(
            owner_type="study",
            owner_id=view_token,
            document_id=document_id,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
        )

    def generate_prepared_collection(
        self,
        document_id: str,
        collection_id: str,
        document_type: str,
        style: str = "study-notes",
        diagram_type: str = "auto",
    ) -> dict[str, Any]:
        """Generate the exact collection record prepared by an API request."""
        return self._generate_prepared_owner(
            owner_type="collection",
            owner_id=collection_id,
            document_id=document_id,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
        )

    def _generate_prepared_owner(
        self,
        *,
        owner_type: str,
        owner_id: str,
        document_id: str,
        document_type: str,
        style: str,
        diagram_type: str,
    ) -> dict[str, Any]:
        self._validate_options(document_type, style, diagram_type)
        source = self._resolve_source(owner_type, owner_id)
        if source.owner_type != owner_type or source.owner_id != owner_id:
            raise VisualLearningGenerationError("resolved source owner mismatch")
        self._validate_interpretation_ready(source, document_type)
        record = self.repository.get_document(document_id)
        if record is None:
            raise VisualLearningGenerationError("prepared document not found")
        if (
            record.get("owner_type") != owner_type
            or record.get("owner_id") != owner_id
            or record.get("document_type") != document_type
            or record.get("style") != style
        ):
            raise VisualLearningGenerationError("prepared document options mismatch")
        if record.get("source_hash") != source.source_hash:
            token = self.repository.claim_generation(
                record["id"],
                previous_token=record.get("generation_token") or "",
            )
            if token:
                self.repository.save_failure(
                    record["id"], token, "source changed before generation"
                )
            return self.repository.get_document(record["id"]) or record
        expected_request_key = self._request_key(
            source,
            document_type,
            style,
            diagram_type,
            self._outline_model(),
            self._outline_reasoning_effort(),
            self._render_model(),
            self._render_reasoning_effort(),
        )
        actual_request_key = record.get("request_key") or ""
        valid_force_key = bool(
            re.fullmatch(
                rf"{re.escape(expected_request_key)}:[0-9a-f]{{32}}",
                actual_request_key,
            )
        )
        if actual_request_key != expected_request_key and not valid_force_key:
            raise VisualLearningGenerationError("prepared document options mismatch")
        return self._generate_record(
            source,
            record,
            self._render_model(),
            document_type,
            style,
            diagram_type,
        )

    def get_study_state(
        self,
        view_token: str,
        document_type: str = "overview",
    ) -> dict[str, Any]:
        return self._get_owner_state("study", view_token, document_type)

    def get_collection_state(
        self,
        collection_id: str,
        document_type: str = "overview",
    ) -> dict[str, Any]:
        return self._get_owner_state("collection", collection_id, document_type)

    def _get_owner_state(
        self,
        owner_type: str,
        owner_id: str,
        document_type: str,
    ) -> dict[str, Any]:
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("invalid document_type")
        try:
            source = self._resolve_source(owner_type, owner_id)
            if source.owner_type != owner_type or source.owner_id != owner_id:
                raise VisualLearningGenerationError(
                    "resolved source owner mismatch"
                )
            self._validate_interpretation_ready(source, document_type)
        except VisualLearningSourceNotReady as exc:
            phase = "failed" if exc.terminal else "source_processing"
            return {
                "document": None,
                "latest_attempt": None,
                "diagram_recommendations": [],
                "selected_diagram_type": None,
                "stale": False,
                "phase": phase,
                "source_progress": exc.source_progress,
                "generation_progress": None,
                "interpretation_sections": [],
                "interpretation_available": False,
                "workflow_progress": compose_workflow_progress(
                    phase, exc.source_progress, None
                ),
            }
        latest_attempt = self.repository.get_latest(
            owner_type, owner_id, document_type
        )
        latest_success = self.repository.get_latest(
            owner_type, owner_id, document_type, successful_only=True
        )
        document = latest_success or latest_attempt
        document_json = (document or {}).get("document_json") or {}
        phase = "ready_for_generation"
        if latest_attempt and latest_attempt.get("status") in {"pending", "generating"}:
            phase = "generating_visual"
        elif document and document.get("status") == "success":
            phase = "completed"
        elif latest_attempt and latest_attempt.get("status") == "failed":
            phase = "failed"
        generation_progress = (latest_attempt or {}).get("progress_json")
        result = {
            "document": document,
            "latest_attempt": latest_attempt,
            "diagram_recommendations": document_json.get(
                "diagram_recommendations", []
            ),
            "selected_diagram_type": document_json.get(
                "selected_diagram_type"
            ),
            "stale": bool(
                latest_success
                and latest_success.get("source_hash") != source.source_hash
            ),
            "phase": phase,
            "source_progress": source.source_progress,
            "generation_progress": generation_progress,
            "interpretation_sections": self._serialize_interpretation_sections(
                source
            ),
            "interpretation_available": bool(source.interpretation_sections),
        }
        result["workflow_progress"] = compose_workflow_progress(
            phase, source.source_progress, generation_progress
        )
        return result

    def get_document_state(self, document_id: str) -> dict[str, Any] | None:
        record = self.repository.get_document(document_id)
        if record is None:
            return None
        source = None
        try:
            resolved_source = self._resolve_source(
                record["owner_type"],
                record["owner_id"],
            )
            if (
                resolved_source.owner_type != record["owner_type"]
                or resolved_source.owner_id != record["owner_id"]
            ):
                raise VisualLearningGenerationError(
                    "resolved source owner mismatch"
                )
            source = resolved_source
            stale = record.get("source_hash") != source.source_hash
        except (
            VisualLearningGenerationError,
            VisualLearningSourceNotFound,
            VisualLearningSourceNotReady,
        ):
            stale = True
        document_json = record.get("document_json") or {}
        source_progress = getattr(source, "source_progress", None) if not stale else None
        phase = "completed" if record.get("status") == "success" else record.get("status")
        generation_progress = record.get("progress_json")
        result = {
            "document": record,
            "latest_attempt": self.repository.get_latest(
                record["owner_type"],
                record["owner_id"],
                record["document_type"],
            ),
            "diagram_recommendations": document_json.get(
                "diagram_recommendations", []
            ),
            "selected_diagram_type": document_json.get(
                "selected_diagram_type"
            ),
            "stale": stale,
            "phase": phase,
            "source_progress": source_progress,
            "generation_progress": generation_progress,
            "interpretation_sections": (
                self._serialize_interpretation_sections(source)
                if source is not None
                else []
            ),
            "interpretation_available": bool(
                source is not None and source.interpretation_sections
            ),
        }
        result["workflow_progress"] = compose_workflow_progress(
            phase, source_progress, generation_progress
        )
        return result

    def _prepare(
        self,
        *,
        view_token: str,
        document_type: str,
        style: str,
        diagram_type: str,
        force: bool,
    ) -> tuple[VisualLearningSource, dict[str, Any], str]:
        return self._prepare_owner(
            owner_type="study",
            owner_id=view_token,
            document_type=document_type,
            style=style,
            diagram_type=diagram_type,
            force=force,
        )

    def _prepare_owner(
        self,
        *,
        owner_type: str,
        owner_id: str,
        document_type: str,
        style: str,
        diagram_type: str,
        force: bool,
    ) -> tuple[VisualLearningSource, dict[str, Any], str]:
        self._validate_options(document_type, style, diagram_type)
        source = self._resolve_source(owner_type, owner_id)
        if source.owner_type != owner_type or source.owner_id != owner_id:
            raise VisualLearningGenerationError("resolved source owner mismatch")
        self._validate_interpretation_ready(source, document_type)
        outline_model = self._outline_model()
        outline_reasoning_effort = self._outline_reasoning_effort()
        render_model = self._render_model()
        render_reasoning_effort = self._render_reasoning_effort()
        request_key = self._request_key(
            source,
            document_type,
            style,
            diagram_type,
            outline_model,
            outline_reasoning_effort,
            render_model,
            render_reasoning_effort,
        )
        record = self.repository.create_or_get_pending(
            owner_type=source.owner_type,
            owner_id=source.owner_id,
            document_type=document_type,
            request_key=request_key,
            source_hash=source.source_hash,
            style=style,
            force=force,
        )
        return source, record, render_model

    def _resolve_source(
        self,
        owner_type: str,
        owner_id: str,
    ) -> VisualLearningSource:
        if owner_type == "study":
            resolver = self.source_resolver
        elif owner_type == "collection":
            resolver = self.collection_source_resolver
        else:
            resolver = None
        if resolver is None:
            raise VisualLearningGenerationError(
                f"{owner_type} source resolver is not configured"
            )
        return resolver.resolve(owner_id)

    @staticmethod
    def _validate_interpretation_ready(
        source: VisualLearningSource,
        document_type: str,
    ) -> None:
        if document_type == "diagram" or source.interpretation_sections:
            return
        source_progress = {
            **source.source_progress,
            "stage": "failed",
            "stage_label": "原解读尚未形成可用章节",
            "percent": 0,
        }
        raise VisualLearningSourceNotReady(
            "source interpretation is not ready",
            source_progress=source_progress,
            terminal=True,
        )

    @staticmethod
    def _serialize_interpretation_sections(
        source: VisualLearningSource,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": section.id,
                "title": section.title,
                "markdown": section.markdown,
                "source_ref_ids": list(section.source_ref_ids),
            }
            for section in source.interpretation_sections
        ]

    @staticmethod
    def _prompt_interpretation_sections(
        source: VisualLearningSource,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": section.id,
                "title": section.title,
                "original_markdown": section.markdown,
                "allowed_source_ref_ids": list(section.source_ref_ids),
            }
            for section in source.interpretation_sections
        ]

    def _call_llm(
        self,
        source: VisualLearningSource,
        document_type: str,
        diagram_type: str,
        model: str,
        *,
        outline: VisualOutline | None = None,
        evidence: str = "",
        correction: str = "",
    ) -> dict[str, Any]:
        result = self.llm_callable(
            model=model,
            prompt=build_visual_prompt(
                source,
                document_type,
                diagram_type,
                outline=outline.model_dump(mode="json") if outline else None,
                evidence=evidence,
                interpretation_sections=(
                    self._prompt_interpretation_sections(source)
                    if document_type in {"overview", "full_note"}
                    else None
                ),
                correction=correction,
            ),
            reasoning_effort=self._render_reasoning_effort(),
            task_type=f"visual_{document_type}",
            response_schema=VisualDocument.model_json_schema(),
            config={"llm": self.llm_config},
            system_prompt=(
                "你是严谨的中文视觉学习设计师。只基于提供的材料组织知识，"
                "所有主要知识块必须引用真实 source ref，不得编造事实或引用。"
            ),
        )
        if isinstance(result, StructuredResult):
            if not result.success or not isinstance(result.data, dict):
                raise VisualLearningGenerationError("structured LLM generation failed")
            return copy.deepcopy(result.data)
        if isinstance(result, dict):
            return copy.deepcopy(result)
        raise VisualLearningGenerationError("LLM returned an invalid structured result")

    def _call_outline(
        self,
        source: VisualLearningSource,
        model: str,
    ) -> VisualOutline:
        result = self.llm_callable(
            model=model,
            prompt=build_outline_prompt(source),
            reasoning_effort=self._outline_reasoning_effort(),
            task_type="visual_outline",
            response_schema=VisualOutline.model_json_schema(),
            config={"llm": self.llm_config},
            system_prompt=(
                "你是严谨的中文知识架构师。必须覆盖整份材料的不同部分，"
                "先建立主线和章节，再交给视觉设计阶段；不得编造材料没有的结论。"
            ),
        )
        if isinstance(result, StructuredResult):
            if not result.success or not isinstance(result.data, dict):
                raise VisualLearningGenerationError("structured outline generation failed")
            payload = result.data
        elif isinstance(result, dict):
            payload = result
        else:
            raise VisualLearningGenerationError("LLM returned an invalid outline")
        return VisualOutline.model_validate(payload)

    @staticmethod
    def _validate_requested_shape(
        document: dict[str, Any],
        document_type: str,
        outline: VisualOutline | None = None,
    ) -> None:
        pages = document.get("pages")
        if not isinstance(pages, list):
            raise VisualLearningGenerationError("generated document has no pages")
        if document_type == "overview":
            if len(pages) != 1:
                raise VisualLearningGenerationError("overview must contain one page")
            blocks = pages[0].get("blocks") if isinstance(pages[0], dict) else None
            if isinstance(blocks, list) and len(blocks) > 5:
                _log_resize("pages[0].blocks", len(blocks), 5)
                pages[0]["blocks"] = blocks[:5]
        elif document_type == "full_note" and not 3 <= len(pages) <= 8:
            raise VisualLearningGenerationError(
                "full_note must contain between three and eight pages"
            )
        elif document_type == "diagram":
            if outline is not None and not 5 <= len(pages) <= 9:
                raise VisualLearningGenerationError(
                    "long diagram must contain between five and nine pages"
                )
            if outline is None and not 1 <= len(pages) <= 3:
                raise VisualLearningGenerationError(
                    "short diagram must contain between one and three pages"
                )

    def _is_long_diagram(
        self,
        source: VisualLearningSource,
        document_type: str,
    ) -> bool:
        threshold = int(
            self.llm_config.get("visual_learning_long_content_chars") or 30000
        )
        return document_type == "diagram" and source.total_content_chars > threshold

    def _update_progress(
        self,
        document_id: str,
        generation_token: str,
        stage: str,
        stage_label: str,
        percent: int,
        **details: Any,
    ) -> None:
        payload = {
            "stage": stage,
            "stage_label": stage_label,
            "percent": percent,
            "basis": details.pop("basis", "stage_transition"),
            **details,
        }
        self.repository.update_progress(
            document_id,
            generation_token,
            payload,
        )

    @staticmethod
    def _tokens(text: str) -> set[str]:
        tokens: set[str] = set()
        for part in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part):
                if len(part) == 1:
                    tokens.add(part)
                else:
                    tokens.update(part[index : index + 2] for index in range(len(part) - 1))
            else:
                tokens.add(part)
        return tokens

    def _select_evidence(
        self,
        source: VisualLearningSource,
        outline: VisualOutline,
    ) -> dict[str, list[SourceReference]]:
        ref_by_id = {ref.id: ref for ref in source.source_refs}
        indexed = [
            (ref_id, self._tokens(text), position)
            for position, (ref_id, text) in enumerate(source.ref_texts.items())
            if ref_id in ref_by_id
        ]
        selected: dict[str, list[SourceReference]] = {}
        for section in outline.sections:
            query_text = " ".join(
                [section.title, section.core_message, *section.evidence_queries]
            )
            query_tokens = self._tokens(query_text)
            ranked = sorted(
                indexed,
                key=lambda item: (
                    len(query_tokens & item[1]),
                    -item[2],
                ),
                reverse=True,
            )
            matches = [item for item in ranked if len(query_tokens & item[1]) > 0][:6]
            if matches:
                selected[section.id] = [ref_by_id[item[0]] for item in matches]
        return selected

    @staticmethod
    def _flatten_evidence_refs(
        evidence_by_section: dict[str, list[SourceReference]],
    ) -> list[SourceReference]:
        seen: set[str] = set()
        result: list[SourceReference] = []
        for refs in evidence_by_section.values():
            for ref in refs:
                if ref.id not in seen:
                    seen.add(ref.id)
                    result.append(ref)
        return result

    @staticmethod
    def _render_evidence(
        source: VisualLearningSource,
        evidence_by_section: dict[str, list[SourceReference]],
    ) -> str:
        rows: list[str] = []
        for section_id, refs in evidence_by_section.items():
            rows.append(f"## section:{section_id}")
            for ref in refs:
                text = source.ref_texts.get(ref.id) or ref.excerpt
                rows.append(f"[{ref.id}] {text}")
        return "\n".join(rows)

    @staticmethod
    def _validate_outline_coverage(
        document: dict[str, Any],
        outline: VisualOutline,
        evidence_by_section: dict[str, list[SourceReference]],
    ) -> None:
        pages = document.get("pages") or []
        expected_ids = ["overview", *[section.id for section in outline.sections]]
        actual_ids = [page.get("id") for page in pages if isinstance(page, dict)]
        if actual_ids != expected_ids:
            raise VisualLearningGenerationError(
                "diagram pages do not match outline sections"
            )
        overview_refs = {
            ref_id
            for block in (pages[0].get("blocks") or [])
            for ref_id in (block.get("source_ref_ids") or [])
        }
        covered_sections = sum(
            1
            for refs in evidence_by_section.values()
            if overview_refs & {ref.id for ref in refs}
        )
        if covered_sections < 3:
            raise VisualLearningGenerationError(
                "overview must cite evidence from at least three sections"
            )

    @staticmethod
    def _validate_full_note_alignment(
        document: dict[str, Any],
        sections: tuple[Any, ...],
    ) -> None:
        pages = document.get("pages") or []
        if [page.get("id") for page in pages] != [
            section.id for section in sections
        ]:
            raise VisualLearningGenerationError(
                "full_note pages do not match interpretation sections"
            )
        for page, section in zip(pages, sections):
            blocks = page.get("blocks") or []
            if not any(
                block.get("type") != "review_questions"
                for block in blocks
                if isinstance(block, dict)
            ):
                raise VisualLearningGenerationError(
                    "full_note page requires a visual block"
                )
            allowed_refs = set(section.source_ref_ids)
            for block in blocks:
                refs = set(block.get("source_ref_ids") or [])
                if not refs.issubset(allowed_refs):
                    raise VisualLearningGenerationError(
                        "full_note block references outside its section"
                    )

    @staticmethod
    def _validate_overview_coverage(
        document: dict[str, Any],
        sections: tuple[Any, ...],
        owner_type: str,
    ) -> None:
        used_refs = {
            ref_id
            for page in (document.get("pages") or [])
            for block in (page.get("blocks") or [])
            for ref_id in (block.get("source_ref_ids") or [])
        }
        base_requirement = 3 if owner_type == "collection" else 2
        required = min(base_requirement, len(sections))
        covered_sections = sum(
            1
            for section in sections
            if used_refs & set(section.source_ref_ids)
        )
        if covered_sections < required:
            label = (
                "three"
                if required == 3
                else "two"
                if required == 2
                else str(required)
            )
            raise VisualLearningGenerationError(
                f"overview must cite at least {label} interpretation sections"
            )

    @staticmethod
    def _filter_source_refs(
        document: dict[str, Any],
        source: VisualLearningSource,
    ) -> None:
        valid_ids = {ref.id for ref in source.source_refs}
        valid_block_count = 0
        for page_index, page in enumerate(document.get("pages") or []):
            blocks = page.get("blocks") if isinstance(page, dict) else None
            if not isinstance(blocks, list):
                continue
            valid_blocks = []
            for block_index, block in enumerate(blocks):
                if not isinstance(block, dict):
                    continue
                refs = block.get("source_ref_ids")
                if not isinstance(refs, list):
                    refs = []
                filtered = list(dict.fromkeys(ref for ref in refs if ref in valid_ids))
                if len(filtered) != len(refs):
                    _log_resize(
                        f"pages[{page_index}].blocks[{block_index}].source_ref_ids",
                        len(refs),
                        len(filtered),
                    )
                if not filtered:
                    continue
                block["source_ref_ids"] = filtered
                valid_blocks.append(block)
                valid_block_count += 1
            page["blocks"] = valid_blocks
        if valid_block_count == 0:
            raise VisualLearningGenerationError("no valid source references")

    def _model(self) -> str:
        """Return the legacy-compatible final rendering model."""
        return self._render_model()

    def _render_model(self) -> str:
        return (
            self.llm_config.get("visual_learning_render_model")
            or self.llm_config.get("visual_learning_model")
            or self.llm_config.get("collection_summary_model")
            or self.llm_config.get("summary_model")
            or "deepseek-v4-pro"
        )

    def _reasoning_effort(self):
        """Return the legacy-compatible final rendering reasoning effort."""
        return self._render_reasoning_effort()

    def _render_reasoning_effort(self):
        return self.llm_config.get(
            "visual_learning_render_reasoning_effort",
            self.llm_config.get(
                "visual_learning_reasoning_effort",
                self.llm_config.get("collection_summary_reasoning_effort", "high"),
            ),
        )

    def _outline_model(self) -> str:
        return (
            self.llm_config.get("visual_learning_outline_model")
            or self.llm_config.get("visual_learning_model")
            or self.llm_config.get("collection_summary_model")
            or self.llm_config.get("summary_model")
            or "deepseek-v4-pro"
        )

    def _outline_reasoning_effort(self):
        return self.llm_config.get(
            "visual_learning_outline_reasoning_effort",
            self.llm_config.get(
                "visual_learning_reasoning_effort",
                self.llm_config.get("collection_summary_reasoning_effort", "high"),
            ),
        )

    @staticmethod
    def _request_key(
        source: VisualLearningSource,
        document_type: str,
        style: str,
        diagram_type: str,
        outline_model: str,
        outline_reasoning_effort: Any,
        render_model: str,
        render_reasoning_effort: Any,
    ) -> str:
        payload = {
            "pipeline_version": 4,
            "owner_type": source.owner_type,
            "owner_id": source.owner_id,
            "document_type": document_type,
            "source_hash": source.source_hash,
            "style": style,
            "diagram_type": diagram_type,
            "analysis_mode": source.source_progress.get("analysis_mode"),
            "outline_model": outline_model,
            "outline_reasoning_effort": outline_reasoning_effort,
            "render_model": render_model,
            "render_reasoning_effort": render_reasoning_effort,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _validate_options(
        document_type: str,
        style: str,
        diagram_type: str,
    ) -> None:
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("invalid document_type")
        if style not in THEME_IDS:
            raise ValueError("invalid style")
        if diagram_type not in DIAGRAM_TYPES:
            raise ValueError("invalid diagram_type")
        if document_type != "diagram" and diagram_type != "auto":
            raise ValueError("diagram_type is only valid for diagram documents")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return "visual document validation failed"
        if isinstance(exc, VisualLearningGenerationError):
            return str(exc)[:1000]
        return "visual document generation failed"

    @staticmethod
    def _generation_correction(exc: Exception) -> str | None:
        if isinstance(exc, VisualLearningGenerationError):
            return str(exc)[:300]
        if isinstance(exc, ValidationError):
            errors = exc.errors()
            if errors:
                return str(errors[0].get("msg") or "")[:300]
        return None

    @staticmethod
    def _build_overview_fallback(source: VisualLearningSource) -> dict[str, Any]:
        sections = source.interpretation_sections
        section_refs = [
            section.source_ref_ids[0]
            for section in sections
            if section.source_ref_ids
        ]
        items = []
        for section in sections:
            plain_text = re.sub(r"[#*_>`~\[\]()]", " ", section.markdown)
            plain_text = re.sub(r"\s+", " ", plain_text).strip()
            items.append(
                {
                    "id": section.id,
                    "label": (section.title or section.id)[:40],
                    "description": (plain_text or section.title)[:240],
                }
            )
        return {
            "version": 1,
            "document_type": "overview",
            "title": source.title[:160],
            "subtitle": "从全局脉络理解各小节之间的关系",
            "selected_diagram_type": "concept_chain",
            "diagram_recommendations": [],
            "pages": [
                {
                    "id": "overview",
                    "title": "全局知识脉络",
                    "learning_goal": "先建立全局视野，再逐节对照原解读",
                    "blocks": [
                        {
                            "id": "overview-section-chain",
                            "type": "concept_chain",
                            "title": "全系列主线",
                            "source_ref_ids": section_refs,
                            "items": items,
                        }
                    ],
                }
            ],
        }
