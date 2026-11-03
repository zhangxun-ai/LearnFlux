"""Complete source snapshots with stable positions and deterministic chapters."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def snapshot_session(session: dict[str, Any]) -> dict[str, Any]:
    """Snapshot every non-empty transcript line without silently truncating it."""
    paragraphs = []
    for index, line in enumerate((session.get("transcript") or {}).get("lines") or []):
        raw_text = str(line.get("text") or "")
        text = raw_text.strip()
        leading = len(raw_text) - len(raw_text.lstrip())
        if not text:
            continue
        # Preserve both the original line and its exact character positions.
        for offset in range(0, len(text), 2000):
            paragraphs.append({
                "id": f"P{len(paragraphs) + 1}",
                "text": text[offset:offset + 2000],
                "line_id": str(line.get("id") or f"line-{index + 1}"),
                "paragraph_index": index,
                "char_start": leading + offset,
                "char_end": leading + min(len(text), offset + 2000),
                "start_seconds": line.get("start_seconds"),
            })
    if not paragraphs:
        raise ValueError("source_not_ready")
    summary = str((session.get("ai") or {}).get("overview") or "")
    title = str((session.get("metadata") or {}).get("title") or "学习内容")[:160]
    payload = {"title": title, "paragraphs": paragraphs, "summary": summary}
    source_hash = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    payload.update({
        "source_hash": source_hash,
        "source_chars": sum(len(p["text"]) for p in paragraphs),
        "coverage": "full",
        "sections": source_sections(paragraphs),
    })
    source = session.get("source") or {}
    if source.get("kind") in {"feishu", "document"}:
        payload["visual_limitations"] = "图解依据可读取的文字；原文图片、画板或附件可能未展开。"
    return payload


def source_sections(paragraphs: list[dict], target_chars: int = 6000) -> list[dict]:
    """Group all source positions into adjacent sections, preserving every line."""
    groups: list[list[dict]] = []
    pending: list[dict] = []
    used = 0
    for paragraph in paragraphs:
        heading = re.match(r"^#{1,4}\s+(.+)", paragraph["text"])
        if pending and (used >= target_chars or (heading and used >= 1500)):
            groups.append(pending)
            pending, used = [], 0
        pending.append(paragraph)
        used += len(paragraph["text"])
    if pending:
        groups.append(pending)
    result = []
    for index, group in enumerate(groups):
        first_sentence = re.split(r"[。！？\n]", group[0]["text"], maxsplit=1)[0]
        title = re.sub(r"^#+\s*", "", first_sentence).strip()[:32]
        result.append({
            "id": f"section-{index + 1}",
            "title": f"第 {index + 1} 节 · {title or '原文片段'}",
            "source_ref_ids": [p["id"] for p in group],
            "start_seconds": group[0].get("start_seconds"),
        })
    return result


def select_source(source: dict, request: dict) -> dict:
    """Return a real chapter plus bounded whole-source context, or the full text."""
    if request.get("scope", "overview") == "overview":
        return source
    section = next((s for s in source["sections"] if s["id"] == request.get("section_id")), None)
    if section is None:
        raise ValueError("invalid_section")
    allowed = set(section["source_ref_ids"])
    return {
        **source,
        "title": f"{source['title']} · {section['title']}",
        "paragraphs": [p for p in source["paragraphs"] if p["id"] in allowed],
        "sections": [section],
        "source_chars": sum(len(p["text"]) for p in source["paragraphs"] if p["id"] in allowed),
        "coverage": "selected_section",
        "whole_source_context": [{"id": s["id"], "title": s["title"]} for s in source["sections"]],
    }
