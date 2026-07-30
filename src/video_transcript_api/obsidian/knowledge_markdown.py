"""Deterministic Markdown renderers for managed knowledge documents."""

from __future__ import annotations

import hashlib
from typing import Any

import yaml

from .knowledge_models import KnowledgeItem


def _normalise(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").rstrip() + "\n"


def content_hash(body: str) -> str:
    return "sha256:" + hashlib.sha256(_normalise(body).encode()).hexdigest()


def parse_knowledge_markdown(content: str) -> tuple[dict[str, Any], str]:
    """Parse one managed Markdown document into frontmatter and body."""
    if not content.startswith("---\n"):
        return {}, content
    marker = content.find("\n---\n", 4)
    if marker < 0:
        return {}, content
    parsed = yaml.safe_load(content[4:marker]) or {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, content[marker + 5:]


def managed_document_hash(content: str) -> str:
    fields, body = parse_knowledge_markdown(content)
    fields = dict(fields)
    fields.pop("synced_at", None)
    fields.pop("content_hash", None)
    canonical = yaml.safe_dump(fields, allow_unicode=True, sort_keys=True) + "---\n" + _normalise(body)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _render(item: KnowledgeItem, *, kind: str, category: str, body: str, synced_at: str, raw_relative_path: str = "") -> str:
    fields: dict[str, Any] = {
        "type": f"learnflux-{kind}", "source": "LearnFlux", "learnflux_context_key": item.context_key,
        "learnflux_view_token": item.view_token, "category": category,
    }
    if item.collection_id:
        fields.update({"learnflux_collection_id": item.collection_id, "learnflux_source_id": item.source_id, "collection": item.collection_title})
    if kind == "raw":
        fields["source_kind"] = item.source_kind
    else:
        fields["raw_note"] = f'[[{raw_relative_path.removesuffix(".md")}]]'
    fields.update({"source_access": item.source_access, "content_hash": content_hash(body), "synced_at": synced_at})
    dumped = yaml.safe_dump(fields, allow_unicode=True, sort_keys=False).strip()
    if kind == "analysis":
        raw_note = fields["raw_note"].replace('"', '\\"')
        dumped = dumped.replace(f"raw_note: '{fields['raw_note']}'", f'raw_note: "{raw_note}"')
    return "---\n" + dumped + "\n---\n\n" + body


def render_raw_knowledge_markdown(item: KnowledgeItem, *, category: str, relative_path: str, synced_at: str) -> str:
    body = f"# {item.title}\n\n## 原文 / 逐字稿\n\n{item.raw_content}\n"
    return _render(item, kind="raw", category=category, body=body, synced_at=synced_at)


def render_analysis_knowledge_markdown(item: KnowledgeItem, *, category: str, raw_relative_path: str, relative_path: str, synced_at: str) -> str:
    body = f"# {item.title}\n\n## AI 解读\n\n{item.analysis_content}\n"
    return _render(item, kind="analysis", category=category, body=body, synced_at=synced_at, raw_relative_path=raw_relative_path)
