"""Deterministic Markdown renderers for managed knowledge documents."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

import yaml

from .knowledge_models import KnowledgeItem
from .paths import sanitize_markdown_filename

COLLECTION_INDEX_SOURCE_ID = "__collection_index__"
COLLECTION_INDEX_TITLE = "00-合集总览"


def is_collection_index_item(item: KnowledgeItem) -> bool:
    return str(item.source_id or "") == COLLECTION_INDEX_SOURCE_ID


def collection_index_view_token(collection_id: str) -> str:
    return f"collection-index:{collection_id}"


def _normalise(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").rstrip() + "\n"


def _truncate_text(value: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _chapter_note_stem(title: str) -> str:
    return sanitize_markdown_filename(title).removesuffix(".md")


def build_collection_index_bodies(
    *,
    creator: str,
    collection_title: str,
    description: str,
    summary_markdown: str,
    chapters: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    """Build raw/processed bodies for a collection-level AI overview note.

    The processed body is the primary metadata surface for multi-course
    reasoning: read this first, then open chapter notes only when needed.
    """
    display_title = " - ".join(
        part for part in (str(creator or "").strip(), str(collection_title or "").strip()) if part
    ) or "未命名合集"
    description = str(description or "").strip()
    summary = str(summary_markdown or "").strip()
    chapter_rows: list[str] = []
    linked_rows: list[str] = []
    for chapter in chapters:
        position = int(chapter.get("position") or 0)
        title = str(chapter.get("title") or chapter.get("source_id") or "未命名章节").strip()
        ready = bool(chapter.get("ready"))
        excerpt = _truncate_text(str(chapter.get("summary") or ""), 120)
        label = f"{position:02d}. {title}" if position > 0 else title
        status = "已就绪" if ready else "未就绪"
        chapter_rows.append(f"- {label}（{status}）")
        note_stem = _chapter_note_stem(title)
        if ready:
            line = f"- {position:02d}. [[{note_stem}]]"
            if excerpt:
                line += f" — {excerpt}"
            linked_rows.append(line)
        else:
            linked_rows.append(f"- {position:02d}. {title}（未就绪，尚未沉淀）")

    chapter_block = "\n".join(chapter_rows) if chapter_rows else "- （暂无章节）"
    linked_block = "\n".join(linked_rows) if linked_rows else "- （暂无章节）"
    meta_block = "\n".join(
        [
            f"- IP / 作者：{creator or '未填写'}",
            f"- 专题名称：{collection_title or '未填写'}",
            f"- 章节数：{len(chapters)}",
            f"- 简介：{description or '（无）'}",
        ]
    )
    usage = (
        "本文件是合集级索引元数据，供 AI 先建立全局视角。"
        "跨课综合分析时优先阅读本文件；需要证据或细节时再打开对应章节笔记。"
    )

    raw_body = (
        f"# {display_title}\n\n"
        f"> {usage}\n\n"
        f"## 合集元数据\n\n{meta_block}\n\n"
        f"## 章节目录\n\n{chapter_block}\n"
    )
    if summary:
        mainline = summary
    else:
        mainline = "（尚未生成全系列主线总结。可在 LearnFlux 生成后重新沉淀本合集。）"
    analysis_body = (
        f"# {display_title}\n\n"
        f"> {usage}\n\n"
        f"## 合集元数据\n\n{meta_block}\n\n"
        f"## 全系列主线总结\n\n{mainline}\n\n"
        f"## 章节目录\n\n{linked_block}\n\n"
        f"## 阅读建议\n\n"
        f"1. 先读「全系列主线总结」理解课程整体问题、结构与价值。\n"
        f"2. 根据章节目录挑选相关分集，再打开对应 AI 解读或原文。\n"
        f"3. 多门课对比时，先并排阅读各课的 `00-合集总览`，再下钻章节。\n"
    )
    return raw_body, analysis_body


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
    if is_collection_index_item(item):
        fields["learnflux_role"] = "collection_index"
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
    if is_collection_index_item(item):
        body = _normalise(item.raw_content)
    else:
        body = f"# {item.title}\n\n## 原文 / 逐字稿\n\n{item.raw_content}\n"
    return _render(item, kind="raw", category=category, body=body, synced_at=synced_at)


def render_analysis_knowledge_markdown(item: KnowledgeItem, *, category: str, raw_relative_path: str, relative_path: str, synced_at: str) -> str:
    if is_collection_index_item(item):
        body = _normalise(item.analysis_content)
    else:
        body = f"# {item.title}\n\n## AI 解读\n\n{item.analysis_content}\n"
    return _render(item, kind="analysis", category=category, body=body, synced_at=synced_at, raw_relative_path=raw_relative_path)
