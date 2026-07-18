"""Resolve learning collections into traceable visual-learning sources."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .interpretation import (
    InterpretationNotReady,
    build_interpretation_sections,
    normalize_interpretation_markdown,
)
from .schemas import SourceReference
from .source_resolver import (
    VisualLearningSource,
    VisualLearningSourceNotFound,
    VisualLearningSourceNotReady,
)


class CollectionSourceResolver:
    """Build a visual-learning source from a completed learning collection."""

    def __init__(self, collection_service: Any, max_content_chars: int = 60000):
        self.collection_service = collection_service
        self.max_content_chars = max_content_chars

    def resolve(self, collection_id: str) -> VisualLearningSource:
        try:
            collection = self.collection_service.get_collection_detail(collection_id)
        except ValueError as exc:
            raise VisualLearningSourceNotFound("collection source not found") from exc
        if not collection:
            raise VisualLearningSourceNotFound("collection source not found")

        full_summary = normalize_interpretation_markdown(
            collection.get("summary_markdown") or ""
        ).strip()
        if not full_summary:
            raise self._terminal_not_ready("collection summary is not ready")

        summary_ref_id = f"collection:{collection_id}:summary"
        summary_ref = SourceReference(
            id=summary_ref_id,
            owner_type="collection",
            owner_id=collection_id,
            excerpt=full_summary[:500],
        )
        ref_texts = {summary_ref_id: full_summary}
        try:
            build_interpretation_sections(
                full_summary,
                owner_type="collection",
                owner_id=collection_id,
                source_refs=[summary_ref],
                ref_texts=ref_texts,
            )
        except InterpretationNotReady as exc:
            raise self._terminal_not_ready(
                "collection summary interpretation is not ready"
            ) from exc

        map_ref = None
        map_text = ""
        evidence_remaining = self.max_content_chars
        try:
            knowledge_map = self.collection_service.get_knowledge_map(
                collection_id, "collection"
            )
        except ValueError:
            knowledge_map = None
        if knowledge_map:
            map_value = knowledge_map.get("map_json")
            if isinstance(map_value, str):
                map_text = map_value
            elif map_value:
                map_text = json.dumps(
                    map_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            if map_text.strip():
                map_evidence = map_text.strip()[:evidence_remaining]
                if map_evidence:
                    map_ref_id = f"collection:{collection_id}:knowledge-map"
                    map_ref = SourceReference(
                        id=map_ref_id,
                        owner_type="collection",
                        owner_id=collection_id,
                        excerpt=map_evidence[:500],
                    )
                    ref_texts[map_ref_id] = map_evidence
                    evidence_remaining -= len(map_evidence)

        summary_refs: list[SourceReference] = []
        summary_rows: list[tuple[str, str]] = []
        transcript_refs: list[SourceReference] = []
        transcript_rows: list[tuple[str, str]] = []
        transcript_candidates: list[tuple[str, str, int, str]] = []
        transcript_candidate_remaining = self.max_content_chars
        total_content_chars = len(full_summary) + len(map_text)
        usable_sources = 0
        source_hasher = hashlib.sha256()
        self._update_hash_field(
            source_hasher, "title", str(collection.get("title") or "")
        )
        self._update_hash_field(source_hasher, "summary", full_summary)
        self._update_hash_field(source_hasher, "knowledge_map", map_text)
        for source in collection.get("sources") or []:
            if str(source.get("task_status") or source.get("status") or "") != "success":
                continue
            source_id = str(source.get("id") or "").strip()
            if not source_id:
                continue
            try:
                detail = self.collection_service.get_source_detail(
                    collection_id, source_id
                )
            except ValueError:
                continue
            detail_status = str(
                detail.get("task_status") or detail.get("status") or "success"
            )
            if detail_status != "success":
                continue

            full_source_summary = str(detail.get("summary") or "")
            full_transcript = str(detail.get("transcript") or "")
            source_summary = full_source_summary.strip()
            transcript = full_transcript.strip()
            if not source_summary and not transcript:
                continue
            usable_sources += 1
            total_content_chars += len(full_source_summary) + len(full_transcript)
            self._update_hash_field(source_hasher, "source_id", source_id)
            self._update_hash_field(
                source_hasher, "source_summary", full_source_summary
            )
            self._update_hash_field(
                source_hasher, "source_transcript", full_transcript
            )

            if source_summary:
                evidence_summary = source_summary[:evidence_remaining]
                if evidence_summary:
                    ref_id = f"collection:{collection_id}:source:{source_id}:summary"
                    summary_refs.append(
                        SourceReference(
                            id=ref_id,
                            owner_type="collection",
                            owner_id=collection_id,
                            excerpt=evidence_summary[:500],
                        )
                    )
                    summary_rows.append((ref_id, evidence_summary))
                    ref_texts[ref_id] = evidence_summary
                    evidence_remaining -= len(evidence_summary)

            if transcript_candidate_remaining > 0:
                candidates = self._transcript_evidence(
                    transcript, transcript_candidate_remaining
                )
                for ref_suffix, paragraph_index, text in candidates:
                    transcript_candidates.append(
                        (source_id, ref_suffix, paragraph_index, text)
                    )
                    transcript_candidate_remaining -= len(text)

        for source_id, ref_suffix, paragraph_index, candidate in transcript_candidates:
            if evidence_remaining <= 0:
                break
            text = candidate[:evidence_remaining]
            if not text:
                continue
            ref_id = (
                f"collection:{collection_id}:source:{source_id}:paragraph:"
                f"{ref_suffix}"
            )
            transcript_refs.append(
                SourceReference(
                    id=ref_id,
                    owner_type="collection",
                    owner_id=collection_id,
                    excerpt=text[:500],
                    paragraph_index=paragraph_index,
                )
            )
            transcript_rows.append((ref_id, text))
            ref_texts[ref_id] = text
            evidence_remaining -= len(text)

        if not usable_sources:
            raise self._terminal_not_ready(
                "collection has no readable successful source"
            )

        evidence_refs = [summary_ref]
        if map_ref is not None:
            evidence_refs.append(map_ref)
        evidence_refs.extend(summary_refs)
        evidence_refs.extend(transcript_refs)
        try:
            interpretation_sections = build_interpretation_sections(
                full_summary,
                owner_type="collection",
                owner_id=collection_id,
                source_refs=evidence_refs,
                ref_texts=ref_texts,
            )
        except InterpretationNotReady as exc:
            raise self._terminal_not_ready(
                "collection summary interpretation is not ready"
            ) from exc

        section_refs = []
        for section in interpretation_sections:
            ref_id = section.source_ref_ids[0]
            section_refs.append(
                SourceReference(
                    id=ref_id,
                    owner_type="collection",
                    owner_id=collection_id,
                    excerpt=section.markdown[:500],
                )
            )
            ref_texts[ref_id] = section.markdown

        refs = [summary_ref, *section_refs]
        if map_ref is not None:
            refs.append(map_ref)
        refs.extend(summary_refs)
        refs.extend(transcript_refs)
        rows = [(summary_ref_id, full_summary)]
        if map_ref is not None:
            rows.append((map_ref.id, ref_texts[map_ref.id]))
        rows.extend(summary_rows)
        rows.extend(transcript_rows)
        content = self._bounded_content(rows)
        source_hash = source_hasher.hexdigest()
        title = str(collection.get("title") or "未命名学习集合").strip()[:160]
        return VisualLearningSource(
            owner_type="collection",
            owner_id=collection_id,
            title=title,
            summary=full_summary[:12000],
            content=content,
            source_refs=refs,
            source_hash=source_hash,
            source_progress={
                "stage": "ready_for_generation",
                "stage_label": "集合总结已完成",
                "percent": 100,
                "analysis_mode": "collection",
            },
            source_kind=str(collection.get("collection_type") or "collection"),
            source_filename=title,
            total_content_chars=total_content_chars,
            ref_texts=ref_texts,
            interpretation_sections=interpretation_sections,
        )

    def _bounded_content(self, rows: list[tuple[str, str]]) -> str:
        parts: list[str] = []
        remaining = self.max_content_chars
        for ref_id, text in rows:
            if remaining <= 0:
                break
            separator = "\n" if parts else ""
            prefix = f"[{ref_id}] "
            if len(separator) + len(prefix) + 1 > remaining:
                continue
            if separator:
                parts.append(separator)
                remaining -= len(separator)
            parts.append(prefix)
            remaining -= len(prefix)
            if remaining <= 0:
                break
            excerpt = text[:remaining]
            parts.append(excerpt)
            remaining -= len(excerpt)
        return "".join(parts)

    @staticmethod
    def _update_hash_field(hasher: Any, field: str, value: str) -> None:
        for item in (field.encode("utf-8"), value.encode("utf-8")):
            hasher.update(len(item).to_bytes(8, "big"))
            hasher.update(item)

    def _transcript_evidence(
        self, transcript: str, budget: int
    ) -> list[tuple[str, int, str]]:
        if not transcript or budget <= 0:
            return []
        chunk_chars = min(4000, max(1, budget // 2))
        retained: list[tuple[str, int, str]] = []
        retained_chars = 0
        last_chunk: tuple[str, int, str] | None = None
        for chunk in self._iter_transcript_chunks(transcript, chunk_chars):
            last_chunk = chunk
            text = chunk[2]
            if retained_chars + len(text) <= budget:
                retained.append(chunk)
                retained_chars += len(text)
        if last_chunk is not None and (
            not retained or last_chunk[0] != retained[-1][0]
        ):
            while len(retained) > 1 and retained_chars + len(last_chunk[2]) > budget:
                retained_chars -= len(retained.pop()[2])
            if retained_chars + len(last_chunk[2]) <= budget:
                retained.append(last_chunk)
        return retained

    @staticmethod
    def _iter_transcript_chunks(transcript: str, chunk_chars: int):
        start = 0
        paragraph_index = 0
        for boundary in re.finditer(
            r"(?:\r?\n)[ \t]*(?:\r?\n)+", transcript
        ):
            paragraph = transcript[start : boundary.start()].strip()
            if paragraph:
                yield from CollectionSourceResolver._paragraph_chunks(
                    paragraph, paragraph_index, chunk_chars
                )
                paragraph_index += 1
            start = boundary.end()
        paragraph = transcript[start:].strip()
        if paragraph:
            yield from CollectionSourceResolver._paragraph_chunks(
                paragraph, paragraph_index, chunk_chars
            )

    @staticmethod
    def _paragraph_chunks(paragraph: str, paragraph_index: int, chunk_chars: int):
        if len(paragraph) <= chunk_chars:
            yield str(paragraph_index), paragraph_index, paragraph
            return
        for chunk_index, offset in enumerate(
            range(0, len(paragraph), chunk_chars), start=1
        ):
            yield (
                f"{paragraph_index}:chunk:{chunk_index}",
                paragraph_index,
                paragraph[offset : offset + chunk_chars],
            )

    @staticmethod
    def _terminal_not_ready(message: str) -> VisualLearningSourceNotReady:
        return VisualLearningSourceNotReady(
            message,
            source_progress={
                "stage": "failed",
                "stage_label": message,
                "percent": 0,
                "analysis_mode": "collection",
            },
            terminal=True,
        )
