"""Resolve existing Study sessions into stable visual-learning sources."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .interpretation import (
    InterpretationNotReady,
    InterpretationSection,
    build_interpretation_sections,
    normalize_interpretation_markdown,
)
from .schemas import SourceReference


class VisualLearningSourceNotFound(LookupError):
    """Raised when an owner cannot be resolved."""


class VisualLearningSourceNotReady(RuntimeError):
    """Raised when an owner exists but has no usable learning content yet."""

    def __init__(
        self,
        message: str = "study source is not ready",
        *,
        source_progress: dict[str, Any] | None = None,
        terminal: bool = False,
    ):
        super().__init__(message)
        self.source_progress = source_progress or {}
        self.terminal = terminal


@dataclass(frozen=True)
class VisualLearningSource:
    owner_type: str
    owner_id: str
    title: str
    summary: str
    content: str
    source_refs: list[SourceReference]
    source_hash: str
    source_progress: dict[str, Any]
    source_kind: str
    source_filename: str
    total_content_chars: int
    ref_texts: dict[str, str]
    interpretation_sections: tuple[InterpretationSection, ...] = ()


class StudySourceResolver:
    """Build a traceable visual-learning source from StudyService output."""

    def __init__(self, study_service: Any, max_content_chars: int = 60000):
        self.study_service = study_service
        self.max_content_chars = max_content_chars

    def resolve(self, view_token: str) -> VisualLearningSource:
        session = self.study_service.get_session(view_token)
        if session is None:
            raise VisualLearningSourceNotFound("study source not found")

        metadata = session.get("metadata") or {}
        ai = session.get("ai") or {}
        source_progress = self._source_progress(session)
        full_summary = normalize_interpretation_markdown(
            ai.get("overview") or ""
        ).strip()
        summary = full_summary[:12000]
        if source_progress["stage"] != "ready_for_generation":
            raise VisualLearningSourceNotReady(
                source_progress.get("stage_label") or "full analysis is not ready",
                source_progress=source_progress,
                terminal=source_progress["stage"] in {"failed", "canceled"},
            )
        transcript = session.get("transcript") or {}
        source_metadata = session.get("source") or {}
        title = (metadata.get("title") or "未命名学习内容").strip()[:160]
        lines = [
            line
            for line in (transcript.get("lines") or [])
            if (line.get("text") or "").strip()
        ]

        refs: list[SourceReference] = []
        rows: list[tuple[str, str]] = []
        ref_texts: dict[str, str] = {}
        next_seekable_starts = self._next_seekable_starts(lines)

        for paragraph_index, line in enumerate(lines):
            raw_text = (line.get("text") or "").strip()
            cleaned_text = self._clean_visual_text(raw_text)
            if not cleaned_text:
                continue
            line_id = str(line.get("id") or "").strip()
            base_ref_id = (
                f"study:{view_token}:line:{line_id}"
                if line_id
                else f"study:{view_token}:paragraph:{paragraph_index}"
            )
            start_seconds = self._seconds(line.get("start_seconds"))
            chunks = [
                cleaned_text[offset : offset + 4000]
                for offset in range(0, len(cleaned_text), 4000)
            ]
            for chunk_index, text in enumerate(chunks):
                ref_id = (
                    base_ref_id
                    if len(chunks) == 1
                    else f"{base_ref_id}:chunk:{chunk_index + 1}"
                )
                ref = SourceReference(
                    id=ref_id,
                    owner_type="study",
                    owner_id=view_token,
                    excerpt=text[:500],
                    line_id=line_id or None,
                    paragraph_index=paragraph_index,
                    start_seconds=start_seconds,
                    end_seconds=(
                        next_seekable_starts[paragraph_index]
                        if start_seconds is not None
                        else None
                    ),
                )
                refs.append(ref)
                rows.append((ref_id, text))
                ref_texts[ref_id] = text

        if not refs and summary:
            ref_id = f"study:{view_token}:summary"
            refs.append(
                SourceReference(
                    id=ref_id,
                    owner_type="study",
                    owner_id=view_token,
                    excerpt=summary[:500],
                )
            )
            text = summary[:self.max_content_chars]
            rows.append((ref_id, text))
            ref_texts[ref_id] = text

        interpretation_sections: tuple[InterpretationSection, ...] = ()
        if full_summary:
            try:
                interpretation_sections = build_interpretation_sections(
                    full_summary,
                    owner_type="study",
                    owner_id=view_token,
                    source_refs=refs,
                    ref_texts=ref_texts,
                )
            except InterpretationNotReady:
                pass
            else:
                for section in interpretation_sections:
                    ref_id = section.source_ref_ids[0]
                    refs.append(
                        SourceReference(
                            id=ref_id,
                            owner_type="study",
                            owner_id=view_token,
                            excerpt=section.markdown[:500],
                        )
                    )
                    ref_texts[ref_id] = section.markdown

        total_content_chars = sum(len(text) for _, text in rows)
        content = self._representative_content(rows)
        if not summary and not content:
            raise VisualLearningSourceNotReady("study source has no transcript or summary")

        hash_payload = {
            "title": title,
            "summary": full_summary,
            "content": content,
            "source_refs": [ref.model_dump(mode="json") for ref in refs],
            "full_content_hash": hashlib.sha256(
                "\n".join(text for _, text in rows).encode("utf-8")
            ).hexdigest(),
        }
        source_hash = hashlib.sha256(
            json.dumps(
                hash_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return VisualLearningSource(
            owner_type="study",
            owner_id=view_token,
            title=title,
            summary=summary,
            content=content,
            source_refs=refs,
            source_hash=source_hash,
            source_progress=source_progress,
            source_kind=str(source_metadata.get("kind") or "unknown"),
            source_filename=str(source_metadata.get("filename") or title),
            total_content_chars=total_content_chars,
            ref_texts=ref_texts,
            interpretation_sections=interpretation_sections,
        )

    @staticmethod
    def _clean_visual_text(text: str) -> str:
        control_count = sum(
            1 for char in text if ord(char) < 32 and char not in {"\t", "\n", "\r"}
        )
        denominator = max(1, len(text))
        replacement_count = text.count("\ufffd")
        if (
            control_count >= 2 and control_count / denominator > 0.001
        ) or replacement_count / denominator > 0.001:
            return ""
        cleaned = text.replace("\ufffd", "")
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
        return re.sub(r"[ \t]+", " ", cleaned).strip()

    def _representative_content(self, rows: list[tuple[str, str]]) -> str:
        rendered = [f"[{ref_id}] {text}" for ref_id, text in rows]
        if sum(len(row) + 1 for row in rendered) <= self.max_content_chars:
            return "\n".join(rendered)
        if not rendered:
            return ""

        target_count = min(len(rendered), 24)
        if target_count == 1:
            indices = [0]
        else:
            indices = sorted(
                {
                    round(index * (len(rendered) - 1) / (target_count - 1))
                    for index in range(target_count)
                }
            )
        selected: list[tuple[int, str]] = []
        used = 0
        for index in [indices[0], indices[-1], *indices[1:-1]]:
            row = rendered[index]
            remaining = self.max_content_chars - used - (1 if selected else 0)
            if remaining <= 0:
                break
            if len(row) > remaining:
                row = row[:remaining]
            selected.append((index, row))
            used += len(row) + (1 if len(selected) > 1 else 0)
        return "\n".join(row for _, row in sorted(selected))

    @staticmethod
    def _source_progress(session: dict[str, Any]) -> dict[str, Any]:
        state = str(session.get("state") or "unknown")
        ai = session.get("ai") or {}
        progress = session.get("progress") or {}
        source = session.get("source") or {}
        analysis = session.get("analysis") or {}
        summary = (ai.get("overview") or "").strip()
        summary_missing = bool(ai.get("summary_missing"))
        fast_document_ready = (
            source.get("kind") == "document"
            and analysis.get("mode") == "document_fast"
            and analysis.get("visual_ready") is True
        )
        raw_stage = str(progress.get("stage") or "")
        if state in {"ready", "source_missing"} and (summary or fast_document_ready):
            stage = "ready_for_generation"
            label = "文档解析已完成" if fast_document_ready else "全文分析已完成"
            percent = 100
        elif state in {"failed", "canceled"} or summary_missing:
            stage = "canceled" if state == "canceled" else "failed"
            label = "全文分析已取消" if stage == "canceled" else "全文分析失败"
            percent = 0
        elif state in {"generating_ai", "calibrating"}:
            stage = "waiting_analysis"
            label = progress.get("stage_label") or "正在生成全文总结"
            percent = progress.get("percent")
        elif raw_stage == "document_quality":
            stage = "assessing_quality"
            label = progress.get("stage_label") or "正在检查文档质量"
            percent = progress.get("percent")
        else:
            stage = "extracting"
            label = progress.get("stage_label") or "正在提取和解析内容"
            percent = progress.get("percent")
        return {
            "stage": stage,
            "stage_label": label,
            "percent": percent if isinstance(percent, (int, float)) else None,
            "updated_at": progress.get("updated_at"),
            "message": progress.get("message") or "",
            "analysis_mode": analysis.get("mode") or "legacy",
            "raw_stage": raw_stage,
            "basis": progress.get("basis"),
            "evidence": progress.get("evidence") or {},
        }

    @staticmethod
    def _seconds(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return seconds if seconds >= 0 else None

    def _next_seekable_starts(self, lines: list[dict]) -> list[float | None]:
        result: list[float | None] = [None] * len(lines)
        next_start = None
        for index in range(len(lines) - 1, -1, -1):
            result[index] = next_start
            current = self._seconds(lines[index].get("start_seconds"))
            if current is not None:
                next_start = current
        return result
