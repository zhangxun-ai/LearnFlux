"""Bounded, best-effort category recommendations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .knowledge_models import KnowledgeItem

_TITLE_LIMIT = 300
_ANALYSIS_LIMIT = 1200
_RAW_LIMIT = 800
_COLLECTION_ITEMS_LIMIT = 8
_ITEM_ANALYSIS_LIMIT = 300


@dataclass(frozen=True)
class CategoryRecommendation:
    category: str
    confidence: float = 0.0
    reason: str = ""
    recommended_by: str = "fallback"


class ObsidianCategoryRecommender:
    def __init__(self, llm_callable: Callable[..., Any]):
        self.llm_callable = llm_callable

    @staticmethod
    def _fallback(candidates: Sequence[str], reason: str) -> CategoryRecommendation:
        if not candidates:
            return CategoryRecommendation(
                "", reason="category_not_configured"
            )
        category = (
            "其他"
            if "其他" in candidates
            else sorted(candidates, key=lambda value: (value.casefold(), value))[0]
        )
        return CategoryRecommendation(category, reason=reason)

    @staticmethod
    def _response_schema(candidates: Sequence[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(candidates)},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "reason": {"type": "string", "maxLength": 300},
            },
            "required": ["category", "confidence", "reason"],
            "additionalProperties": False,
        }

    @staticmethod
    def _coerce_response(value: Any) -> Mapping[str, Any]:
        if hasattr(value, "success") and hasattr(value, "data"):
            if not value.success or not isinstance(value.data, Mapping):
                raise ValueError("structured_llm_failure")
            return value.data
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, Mapping):
                return parsed
        raise ValueError("invalid_llm_response")

    def recommend(
        self,
        *,
        candidates: Sequence[str],
        title: str,
        analysis_excerpt: str,
        raw_excerpt: str,
    ) -> CategoryRecommendation:
        unique_candidates = list(dict.fromkeys(str(item) for item in candidates))
        if not unique_candidates:
            return self._fallback(unique_candidates, "category_not_configured")
        prompt = json.dumps(
            {
                "instruction": "只能从 candidates 中选择一个一级分类。",
                "candidates": unique_candidates,
                "title": str(title or "")[:_TITLE_LIMIT],
                "analysis_excerpt": str(analysis_excerpt or "")[
                    :_ANALYSIS_LIMIT
                ],
                "raw_excerpt": str(raw_excerpt or "")[:_RAW_LIMIT],
            },
            ensure_ascii=False,
        )
        try:
            response = self.llm_callable(
                prompt=prompt,
                response_schema=self._response_schema(unique_candidates),
            )
            data = self._coerce_response(response)
            category = str(data.get("category") or "")
            if category not in unique_candidates:
                return self._fallback(
                    unique_candidates, "invalid_llm_category"
                )
            confidence = min(
                1.0, max(0.0, float(data.get("confidence", 0.0)))
            )
            return CategoryRecommendation(
                category=category,
                confidence=confidence,
                reason=str(data.get("reason") or "")[:300],
                recommended_by="llm",
            )
        except Exception:
            return self._fallback(unique_candidates, "llm_unavailable")

    def recommend_collection(
        self,
        *,
        candidates: Sequence[str],
        collection: Mapping[str, Any],
        items: Sequence[KnowledgeItem],
    ) -> CategoryRecommendation:
        ordered = sorted(
            items,
            key=lambda item: (
                item.position,
                item.source_id,
                item.view_token,
            ),
        )[:_COLLECTION_ITEMS_LIMIT]
        item_excerpt = "\n".join(
            f"{item.position}. {item.title}: "
            f"{item.analysis_content[:_ITEM_ANALYSIS_LIMIT]}"
            for item in ordered
        )
        creator = (
            collection.get("creator_name")
            or collection.get("creator")
            or ""
        )
        return self.recommend(
            candidates=candidates,
            title=(
                f"{creator} {collection.get('title') or ''}".strip()
            ),
            analysis_excerpt=(
                f"简介：{collection.get('description') or ''}\n"
                f"主线解读：{str(collection.get('summary_markdown') or '')[:700]}\n"
                f"分集：\n{item_excerpt}"
            ),
            raw_excerpt="",
        )
