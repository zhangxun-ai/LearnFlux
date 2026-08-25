"""Deterministic, user-preserving Markdown for review synchronization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

import yaml

from ..obsidian.markdown import MarkdownFormatError, parse_markdown_document


MANAGED_START = "<!-- LEARNFLUX_REVIEW_START -->"
MANAGED_END = "<!-- LEARNFLUX_REVIEW_END -->"


class ReviewMarkdownConflict(ValueError):
    """An existing file is not safely managed by the review module."""


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _bullets(values: Any, *, empty: str = "暂无记录") -> str:
    items = values if isinstance(values, list) else []
    rendered: list[str] = []
    for value in items:
        if isinstance(value, Mapping):
            text = _clean_text(
                value.get("text")
                or value.get("statement")
                or value.get("title")
                or value.get("quote")
                or value.get("id")
            )
        else:
            text = _clean_text(value)
        if text:
            rendered.append(f"- {text}")
    return "\n".join(rendered) if rendered else f"- {empty}"


def _source_lines(source_ids: Any) -> str:
    values = source_ids if isinstance(source_ids, list) else []
    lines = []
    for value in values:
        if isinstance(value, Mapping):
            source_id = _clean_text(value.get("id") or value.get("source_id"))
            source_type = _clean_text(value.get("type") or value.get("source_type") or "daily")
            label = _clean_text(value.get("label") or value.get("date") or source_id)
            obsidian_link = _clean_text(value.get("obsidian_link"))
        else:
            source_id = _clean_text(value)
            source_type = "daily"
            label = source_id
            obsidian_link = ""
        if source_id:
            target = f"[[{obsidian_link}|{label}]]" if obsidian_link else label
            lines.append(f"- {target} (`{source_type}:{source_id}`)")
    return "\n".join(lines) if lines else "- 暂无显式来源"


def _daily_body(record: Mapping[str, Any]) -> str:
    sections: list[str] = [f"# {record.get('period')} 每日复盘"]
    for index, event in enumerate(record.get("events") or [], start=1):
        past = event.get("past") or {}
        present = event.get("present") or {}
        emotions = event.get("emotions") or []
        emotion_text = "、".join(
            _clean_text(item.get("name") if isinstance(item, Mapping) else item)
            for item in emotions
            if _clean_text(item.get("name") if isinstance(item, Mapping) else item)
        )
        sections.extend(
            [
                "",
                f"## {index}. {_clean_text(event.get('title')) or '未命名事件'}",
                "",
                f"- 事件 ID：`{event.get('id')}` ^{event.get('id')}",
                f"- 快速事实：{_clean_text(event.get('fact')) or '—'}",
                f"- 快速意义：{_clean_text(event.get('quick_meaning')) or '—'}",
                f"- 意义类型：{'、'.join(_clean_text(value) for value in event.get('meaning_types') or []) or _clean_text(event.get('meaning_type')) or '—'}",
                f"- 涉及人物：{'、'.join(_clean_text(value) for value in event.get('people') or []) or '—'}",
                f"- 关键词：{'、'.join(_clean_text(value) for value in event.get('keywords') or []) or '—'}",
                f"- 情绪：{emotion_text or '—'}",
                "",
                "### 当时",
                "",
                f"- 想法与感受：{_clean_text(past.get('thoughts')) or '—'}",
                f"- 行动：{_clean_text(past.get('action')) or '—'}",
                f"- 结果：{_clean_text(past.get('result')) or '—'}",
                "",
                "### 现在",
                "",
                f"- 新视角：{_clean_text(present.get('new_view')) or '—'}",
                f"- 自我发现：{_clean_text(present.get('self_discovery')) or '—'}",
                f"- 当前可控行动：{_clean_text(present.get('action')) or '—'}",
                f"- 预期结果：{_clean_text(present.get('expected_result')) or '—'}",
                f"- 后续实际结果：{_clean_text(present.get('actual_result') or present.get('result')) or '—'}",
            ]
        )
    if len(sections) == 1:
        sections.extend(["", "今天还没有事件记录。"])
    sections.extend(
        [
            "",
            "## 相关周度、月度与行动实验",
            "",
            _source_lines(record.get("related_ids")),
        ]
    )
    return "\n".join(sections)


def _weekly_body(record: Mapping[str, Any]) -> str:
    abstraction = record.get("abstraction") or {}
    lines = [
        f"# {record.get('period')} 周度复盘",
        "",
        "## 本周聚焦",
        "",
        _source_lines(record.get("focus_sources") or record.get("focus_ids")),
        "",
        "## 连接",
        "",
        _bullets(record.get("connections")),
        "",
        "## 八级抽象",
        "",
    ]
    for level in range(1, 9):
        value = abstraction.get(str(level), abstraction.get(level, ""))
        lines.append(f"- L{level}：{_clean_text(value) or '—'}")
    lines.extend(
        [
            "",
            "## 本周总结",
            "",
            _clean_text(record.get("summary")) or "暂无总结。",
            "",
            "## 行动实验",
            "",
            _bullets(record.get("experiments")),
        ]
    )
    return "\n".join(lines)


def _monthly_body(record: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"# {record.get('period')} 月度复盘",
            "",
            "> 四列彼此独立；并列不代表存在因果关系。",
            "",
            "## 内心",
            "",
            _bullets(record.get("inner")),
            "",
            "## 行动",
            "",
            _bullets(record.get("actions")),
            "",
            "## 结果",
            "",
            _bullets(record.get("results")),
            "",
            "## 备注",
            "",
            _bullets(record.get("notes")),
            "",
            "## 跨月连接",
            "",
            _bullets(record.get("cross_month")),
            "",
            "## 给自己的确认",
            "",
            _clean_text(record.get("affirmation")) or "暂无。",
            "",
            "## 来源",
            "",
            _source_lines(record.get("source_ids")),
        ]
    )


def _annual_body(record: Mapping[str, Any]) -> str:
    lines = [f"# {record.get('period')} 年度复盘", "", "## 十二个月全景", ""]
    for month in record.get("months") or []:
        source_ref = month.get("source_ref") or {}
        source_line = (
            f"- 来源：[[{source_ref.get('obsidian_link')}|{month.get('month_key')} 月度复盘]]"
            if source_ref.get("obsidian_link")
            else "- 来源：—"
        )
        lines.extend(
            [
                f"### {month.get('month_key')}",
                "",
                f"- 内心：{'; '.join(_clean_text(v) for v in month.get('inner') or []) or '—'}",
                f"- 行动：{'; '.join(_clean_text(v) for v in month.get('actions') or []) or '—'}",
                f"- 结果：{'; '.join(_clean_text(v) for v in month.get('results') or []) or '—'}",
                f"- 备注：{'; '.join(_clean_text(v) for v in month.get('notes') or []) or '—'}",
                source_line,
                "",
            ]
        )
    lines.extend(
        [
            "## 关键词",
            "",
            _bullets(record.get("keywords")),
            "",
            "## 年度总结",
            "",
            _clean_text(record.get("summary")) or "暂无总结。",
            "",
            "## 来源",
            "",
            _source_lines(record.get("source_ids")),
        ]
    )
    return "\n".join(lines)


def _insight_body(record: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"# {_clean_text(record.get('statement')) or '内在洞察'}",
            "",
            f"- 层级：{record.get('tier')} / L{record.get('level')}",
            f"- 状态：{record.get('status')}",
            f"- 类别：{_clean_text(record.get('category')) or '—'}",
            f"- 不确定性说明：{_clean_text(record.get('uncertainty_note')) or record.get('uncertainty')}",
            f"- 证据跨度：{_clean_text((record.get('evidence_span') or {}).get('start')) or '—'} → {_clean_text((record.get('evidence_span') or {}).get('end')) or '—'}",
            f"- 证据强度：{_clean_text((record.get('evidence_strength') or {}).get('label')) or '证据较少'}",
            "",
            "## 支持证据",
            "",
            _bullets(record.get("evidence")),
            "",
            "## 反例与不同解释",
            "",
            _bullets(record.get("counter_evidence")),
            "",
            "## 验证行动",
            "",
            _clean_text(record.get("verification_experiment")) or "尚未设置。",
            "",
            "## 来源",
            "",
            _source_lines(record.get("source_ids")),
        ]
    )


def _experiment_body(record: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"# {_clean_text(record.get('title')) or '行动实验'}",
            "",
            f"- Why：{_clean_text(record.get('why')) or '—'}",
            f"- What：{_clean_text(record.get('what')) or '—'}",
            f"- Who：{_clean_text(record.get('who')) or '—'}",
            f"- When：{_clean_text(record.get('when')) or '—'}",
            f"- Where：{_clean_text(record.get('where')) or '—'}",
            f"- How：{_clean_text(record.get('how')) or '—'}",
            f"- 资源：{_clean_text(record.get('resources')) or '—'}",
            f"- 预算：{_clean_text(record.get('budget')) or '—'}",
            f"- 成功信号：{_clean_text(record.get('success_signal')) or '—'}",
            f"- 真正想尝试：{_clean_text(record.get('desire_check')) or '—'}",
            f"- 主要由自己控制：{_clean_text(record.get('control_check')) or '—'}",
            f"- 最小第一步：{_clean_text(record.get('first_step')) or '—'}",
            f"- 复查日期：{_clean_text(record.get('review_date')) or '—'}",
            f"- 状态：{_clean_text(record.get('status')) or '—'}",
            "",
            "## 后续结果",
            "",
            _clean_text(record.get("result")) or "尚未复查。",
            "",
            f"- 是否执行：{_clean_text(record.get('executed')) or '—'}",
            f"- 原认识是否成立：{_clean_text(record.get('insight_result')) or '—'}",
            f"- 下一步：{_clean_text(record.get('next_decision')) or '—'}",
            "",
            "## 来源",
            "",
            _source_lines(record.get("source_ids")),
        ]
    )


_BODY_RENDERERS = {
    "daily": _daily_body,
    "weekly": _weekly_body,
    "monthly": _monthly_body,
    "annual": _annual_body,
    "insight": _insight_body,
    "experiment": _experiment_body,
}


def build_frontmatter(record_type: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Build the stable public metadata contract for one managed note."""

    source_ids = record.get("source_ids") or [
        event.get("id") for event in record.get("events") or [] if event.get("id")
    ]
    return {
        "id": str(record.get("id") or f"{record_type}:{record.get('period')}"),
        "type": record_type,
        "period": str(record.get("period") or ""),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "source_ids": source_ids,
        "related_ids": record.get("related_ids") or [],
        "status": str(record.get("status") or "draft"),
        "learnflux_managed": True,
    }


def render_review_markdown(record_type: str, record: Mapping[str, Any]) -> str:
    """Render a complete new LearnFlux-managed Markdown document."""

    renderer = _BODY_RENDERERS.get(record_type)
    if renderer is None:
        raise ValueError(f"unsupported review record type: {record_type}")
    frontmatter = build_frontmatter(record_type, record)
    body = renderer(record).strip()
    managed = f"{MANAGED_START}\n{body}\n{MANAGED_END}"
    dumped = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{dumped}\n---\n\n{managed}\n"


def merge_review_markdown(
    existing: str | None, record_type: str, record: Mapping[str, Any]
) -> str:
    """Update only the managed block and preserve user frontmatter/body additions."""

    fresh = render_review_markdown(record_type, record)
    if existing is None:
        return fresh
    try:
        current = parse_markdown_document(existing)
        incoming = parse_markdown_document(fresh)
    except MarkdownFormatError as exc:
        raise ReviewMarkdownConflict("existing review Markdown is invalid") from exc
    if current.frontmatter.get("learnflux_managed") is not True:
        raise ReviewMarkdownConflict("existing file is not managed by LearnFlux")
    if str(current.frontmatter.get("id") or "") != str(incoming.frontmatter.get("id") or ""):
        raise ReviewMarkdownConflict("existing file belongs to another review record")
    if current.body.count(MANAGED_START) != 1 or current.body.count(MANAGED_END) != 1:
        raise ReviewMarkdownConflict("managed review markers are missing or ambiguous")
    start = current.body.index(MANAGED_START)
    end = current.body.index(MANAGED_END, start) + len(MANAGED_END)
    incoming_start = incoming.body.index(MANAGED_START)
    incoming_end = incoming.body.index(MANAGED_END, incoming_start) + len(MANAGED_END)
    body = current.body[:start] + incoming.body[incoming_start:incoming_end] + current.body[end:]
    frontmatter = dict(current.frontmatter)
    frontmatter.update(incoming.frontmatter)
    dumped = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{dumped}\n---\n\n{body.strip()}\n"


def synced_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
