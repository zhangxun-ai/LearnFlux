"""Evidence-bounded AI candidate generation for personal reviews."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from typing import Any, Callable, Mapping

from ..llm import StructuredResult, call_llm_api
from .repository import ReviewDataError, ReviewRepository


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "category", "statement", "tier", "level", "evidence",
                    "counter_evidence", "uncertainty", "uncertainty_note",
                    "follow_up_questions", "verification_experiment",
                ],
                "properties": {
                    "category": {"type": "string"},
                    "statement": {"type": "string"},
                    "tier": {"type": "string", "enum": ["branch", "trunk", "root"]},
                    "level": {"type": "integer", "minimum": 1, "maximum": 8},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["source_id", "observation"],
                            "properties": {
                                "source_id": {"type": "string"},
                                "observation": {"type": "string"},
                            },
                        },
                    },
                    "counter_evidence": {"type": "array", "items": {"type": "string"}},
                    "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
                    "uncertainty_note": {"type": "string"},
                    "follow_up_questions": {"type": "array", "items": {"type": "string"}},
                    "verification_experiment": {"type": "string"},
                },
            },
        }
    },
}


_PURPOSES = {
    "daily_reframe": "区分事实、感受与现在可控的选择，不强迫积极解释",
    "weekly_focus": "从所选记录中提出最多三个值得用户确认的聚焦候选",
    "weekly_connections": "提出直接、间接或意外连接，并说明每条连接的来源",
    "weekly_abstraction": "从具体事件提出可证伪的枝叶、树干或树根候选",
    "action_experiment": "把用户已认可的方向具体化为小型验证实验",
    "annual_summary": "基于月度来源提出年度关键词与总结候选",
    "inner_insight": "提出带支持证据、反例和不确定性的内在洞察候选",
}

_ANALYSIS_GUIDANCE = {
    "daily_reframe": (
        "检查客观事实中是否混入评价或动机猜测；区分事实、感受和更准确的情绪词；"
        "提出视角切换问题；检查未来行动是否由用户控制、是否写成现在可做的表达。"
    ),
    "weekly_focus": "最多提出三个聚焦候选，并在陈述中说明为什么它值得继续理解。",
    "weekly_connections": (
        "只描述直接、间接或意外关系，不把共同出现写成因果；每条关系引用两端来源。"
    ),
    "weekly_abstraction": (
        "依照 L1 状态、L2 在意、L3 人物、L4 兴趣、L5 优势、L6 模式、"
        "L7 信念与固有观念、L8 真实想法与愿望逐层提出候选。"
    ),
    "action_experiment": (
        "验证实验要包含何时、何地、和谁、做什么、怎么做、预算或时间上限、"
        "预期信号，并指出最小第一步与主要可控部分。"
    ),
    "annual_summary": (
        "按来源充分程度，优先分别覆盖这些年度候选类别：important_event 全年重要事件、"
        "inner_change 内在变化、key_action 关键行动、delayed_result 延迟结果、"
        "important_person 关键人物、interest 兴趣、strength 优势、thought_pattern 思维模式、"
        "behavior_pattern 行为模式、belief_change 信念变化、open_question 待观察问题、"
        "next_experiment 下一年验证方向。证据不足的类别可以不生成，不得凑满。"
    ),
    "inner_insight": (
        "观察重复主题、人物、兴趣、优势与思维/行为模式；只有程序允许时才探索信念、"
        "固有观念和愿望，并提出现实中的最小验证行动。"
    ),
}


class ReviewAIAnalyzer:
    """Call the configured model only after the server resolves every source."""

    def __init__(
        self,
        repository: ReviewRepository,
        config: Mapping[str, Any] | None,
        answerer: Callable[..., Any] | None = None,
    ) -> None:
        self.repository = repository
        self.config = dict(config or {})
        self.answerer = answerer or call_llm_api

    def analyze(
        self,
        user_id: str,
        analysis_type: str,
        scope: list[Mapping[str, str]],
        purpose: str = "",
    ) -> list[dict[str, Any]]:
        if analysis_type not in _PURPOSES:
            raise ReviewDataError("unsupported AI review analysis type")
        if not scope or len(scope) > 60:
            raise ReviewDataError("AI scope must contain between 1 and 60 records")
        resolved: list[dict[str, Any]] = []
        allowed_sources: dict[str, dict[str, Any]] = {}
        clean_scope: list[dict[str, str]] = []
        for reference in scope:
            source_type = str(reference.get("type") or "").strip()
            source_id = str(reference.get("id") or "").strip()
            if not source_type or not source_id:
                raise ReviewDataError("every AI source requires type and id")
            record = self.repository.source(user_id, source_type, source_id)
            if record is None:
                raise ReviewDataError(f"AI source not found: {source_type}:{source_id}")
            allowed_sources[source_id] = {"type": source_type, "record": record}
            clean_scope.append({"type": source_type, "id": source_id})
            resolved.append({"type": source_type, "id": source_id, "record": record})
        model, effort = self._model_settings()
        readiness = self.repository.evidence_overview(user_id)
        max_level = readiness["max_level"] if analysis_type in {"weekly_abstraction", "inner_insight"} else 8
        candidate_limit = 12 if analysis_type == "annual_summary" else 5
        response_schema = deepcopy(_RESPONSE_SCHEMA)
        response_schema["properties"]["candidates"]["maxItems"] = candidate_limit
        result = self.answerer(
            model=model,
            prompt=self._prompt(analysis_type, purpose, resolved, max_level, readiness),
            reasoning_effort=effort,
            task_type=f"review_{analysis_type}",
            response_schema=response_schema,
            config=self.config,
            system_prompt=(
                "你是克制、严谨的中文复盘助手。你只能基于给定来源提出候选，不能进行心理诊断、"
                "人格定论、道德评判、强迫积极解释，也不能把相关性写成确定因果。每个判断必须"
                "标出证据、可能反例和不确定性，并明确等待用户确认。"
            ),
        )
        if isinstance(result, StructuredResult):
            if not result.success or not isinstance(result.data, dict):
                raise RuntimeError(result.error or "structured AI review failed")
            data = result.data
        elif isinstance(result, dict):
            data = result
        else:
            raise RuntimeError("AI review did not return structured data")
        candidates = self._validate_candidates(
            data.get("candidates"), allowed_sources,
            max_level=max_level, limit=candidate_limit,
        )
        return self.repository.create_ai_candidates(
            user_id, analysis_type, purpose or _PURPOSES[analysis_type], clean_scope, candidates, model
        )

    def describe_scope(
        self, analysis_type: str, scope: list[Mapping[str, str]]
    ) -> dict[str, Any]:
        if analysis_type not in _PURPOSES:
            raise ReviewDataError("unsupported AI review analysis type")
        return {
            "analysis_type": analysis_type,
            "purpose": _PURPOSES[analysis_type],
            "source_count": len(scope),
            "sources": [{"type": str(item.get("type") or ""), "id": str(item.get("id") or "")} for item in scope],
        }

    def _model_settings(self) -> tuple[str, str | None]:
        llm = self.config.get("llm") or {}
        model = str(
            llm.get("review_analysis_model")
            or llm.get("journal_review_model")
            or llm.get("summary_model")
            or "deepseek-v4-flash"
        )
        effort = llm.get("review_analysis_reasoning_effort")
        if effort is None:
            effort = llm.get("journal_review_reasoning_effort", "high")
        return model, effort

    @staticmethod
    def _prompt(
        analysis_type: str,
        purpose: str,
        resolved: list[dict[str, Any]],
        max_level: int,
        readiness: Mapping[str, Any],
    ) -> str:
        source_json = json.dumps(resolved, ensure_ascii=False, indent=2, default=str)
        if len(source_json) > 90_000:
            source_json = source_json[:90_000] + "\n[来源过长，已截断]"
        return f"""本次任务：{analysis_type}
用户看到的目的：{purpose or _PURPOSES[analysis_type]}

来源记录（id 必须原样用于 evidence.source_id）：
{source_json}

证据就绪度（由程序根据数量和跨度计算，不是模型置信度）：
{json.dumps(dict(readiness), ensure_ascii=False)}
本次允许提出的最深抽象级别：L{max_level or 0}
本类分析的额外要求：{_ANALYSIS_GUIDANCE[analysis_type]}

要求：
1. 只输出候选，不把候选写成用户已经认可的事实。
2. 陈述尽量贴近来源中的具体词语，但不要大段复制。
3. 证据必须引用本次给出的 source id；证据不足要写明 uncertainty_note。
4. 主动寻找反例、另一种解释或缺失信息。
5. 验证实验应小、可逆、可在近期观察结果，不变成泛化待办清单。
6. 不得提出高于本次允许级别的候选；如果只适合枝叶，就停在枝叶。
7. 使用简体中文。
"""

    @staticmethod
    def _source_excerpt(record: Mapping[str, Any]) -> str:
        for key in ("fact", "quick_meaning", "summary", "statement", "title"):
            value = str(record.get(key) or "").strip()
            if value:
                return value[:240]
        for key in ("inner", "actions", "results", "notes"):
            values = record.get(key) or []
            if values:
                return str(values[0])[:240]
        return ""

    @staticmethod
    def _record_date(record: Mapping[str, Any]) -> str:
        return str(
            record.get("review_date")
            or record.get("week_start")
            or record.get("month_key")
            or record.get("year_key")
            or ""
        )

    @staticmethod
    def _evidence_metrics(
        evidence: list[dict[str, Any]], counter_evidence: list[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        dates = sorted({str(item.get("record_date") or "") for item in evidence if item.get("record_date")})
        span_days = 0
        if dates:
            try:
                span_days = (date.fromisoformat(dates[-1][:10]) - date.fromisoformat(dates[0][:10])).days + 1
            except ValueError:
                span_days = 0
        independent = len({(item.get("source_type"), item.get("source_id")) for item in evidence})
        label = "证据较少"
        if independent >= 2 and span_days >= 7:
            label = "正在形成"
        if independent >= 4 and span_days >= 21:
            label = "跨周期重复"
        return (
            {"start": dates[0] if dates else None, "end": dates[-1] if dates else None, "days": span_days},
            {
                "label": label,
                "independent_sources": independent,
                "source_types": sorted({str(item.get("source_type") or "daily") for item in evidence}),
                "counter_evidence": len(counter_evidence),
            },
        )

    @classmethod
    def _validate_candidates(
        cls,
        raw: Any,
        allowed_sources: Mapping[str, Mapping[str, Any]],
        *,
        max_level: int = 8,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise RuntimeError("AI review returned no candidates")
        candidates: list[dict[str, Any]] = []
        for item in raw[:limit]:
            if not isinstance(item, dict) or not str(item.get("statement") or "").strip():
                continue
            evidence = []
            for entry in item.get("evidence") or []:
                if not isinstance(entry, dict):
                    continue
                source_id = str(entry.get("source_id") or "")
                source = allowed_sources.get(source_id)
                if source is None:
                    continue
                record = source.get("record") or {}
                evidence.append({
                    "source_id": source_id,
                    "source_type": str(source.get("type") or "daily"),
                    "record_date": cls._record_date(record),
                    "source_excerpt": cls._source_excerpt(record),
                    "observation": str(entry.get("observation") or "").strip(),
                })
            if not evidence:
                continue
            tier = str(item.get("tier") or "branch")
            level = max(1, min(int(item.get("level") or 1), 8))
            if level > max_level:
                continue
            uncertainty = max(0.0, min(float(item.get("uncertainty", 0.5)), 1.0))
            counter_evidence = [
                str(value).strip()
                for value in item.get("counter_evidence") or []
                if str(value).strip()
            ]
            evidence_span, evidence_strength = cls._evidence_metrics(evidence, counter_evidence)
            candidates.append({
                "category": str(item.get("category") or "pattern").strip(),
                "statement": str(item["statement"]).strip(),
                "tier": tier if tier in {"branch", "trunk", "root"} else "branch",
                "level": level,
                "evidence": evidence,
                "counter_evidence": counter_evidence,
                "evidence_span": evidence_span,
                "evidence_strength": evidence_strength,
                "uncertainty": uncertainty,
                "uncertainty_note": str(item.get("uncertainty_note") or "仍需更多独立记录验证").strip(),
                "follow_up_questions": [str(value).strip() for value in item.get("follow_up_questions") or [] if str(value).strip()],
                "verification_experiment": str(item.get("verification_experiment") or "").strip(),
                "label": "AI 候选",
            })
        if not candidates:
            if max_level < 1:
                raise ReviewDataError("目前证据不足，建议先继续记录，再请求洞察分析")
            raise ReviewDataError("目前证据不足，或候选超出当前适合观察的层级")
        return candidates
