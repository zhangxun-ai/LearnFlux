"""Prompts for constrained visual learning document generation."""

from __future__ import annotations

import json

from .source_resolver import VisualLearningSource


def build_outline_prompt(source: VisualLearningSource) -> str:
    return f"""请先分析整份材料，建立覆盖全文的结构化知识大纲。

标题：{source.title}
全文 AI 总结：
{source.summary}

跨全文代表性原文：
{source.content}

要求：
1. 输出 4-8 个互不重复的核心 section，覆盖材料不同部分，不能只关注开头。
2. section 按最适合学习的逻辑顺序排列，id 使用简短稳定的英文或拼音标识。
3. 每个 section 提供 2-8 个可用于回查原文的 evidence_queries，使用材料里的具体概念词。
4. thesis 必须表达全文的一条核心主线；不得添加材料没有支持的观点。
5. 只输出 VisualOutline schema 允许的 JSON。
"""


def build_visual_prompt(
    source: VisualLearningSource,
    document_type: str,
    diagram_type: str = "auto",
    *,
    outline: dict | None = None,
    evidence: str = "",
    interpretation_sections: list[dict] | None = None,
    correction: str = "",
) -> str:
    requirements = {
        "overview": (
            "生成 1 页、最多 5 个主要知识块的视觉速览，让用户在 30-60 秒内理解"
            "全部既有 section 之间的宏观关系；这是跨章节关系图，不是替代原解读的新摘要。"
        ),
        "full_note": (
            "根据既有 section 生成完整视觉笔记；每个 section 恰好生成一页，page.id "
            "必须保持 section id 和原顺序。基于 original_markdown 设计视觉块，不要重写一份"
            "平行解读；每页至少包含一个非 review_questions 视觉块，最后一页必须包含 "
            "review_questions 主动回忆题。"
        ),
        "diagram": (
            "根据内容生成图解。短内容输出 1-3 页；如果提供了知识大纲，必须输出 1 页全景图"
            "加每个 section 一页的核心笔记，并按大纲顺序排列；"
            f"当前指定类型为 {diagram_type}，auto 表示自动选择。"
        ),
    }[document_type]
    outline_text = (
        json.dumps(outline, ensure_ascii=False, indent=2) if outline else "无（短内容）"
    )
    evidence_text = evidence or source.content or "无"
    sections_text = (
        json.dumps(interpretation_sections, ensure_ascii=False, indent=2)
        if interpretation_sections
        else "无"
    )
    interpretation_text = ""
    interpretation_rules = ""
    if document_type in {"overview", "full_note"}:
        interpretation_text = f"""
既有解读 sections（original_markdown 必须完整保留为视觉设计输入）：
{sections_text}
"""
    if document_type == "overview":
        interpretation_rules = (
            "\n9. overview 必须表达全部既有 sections 的宏观关系，并引用不同 section 的"
            " allowed_source_ref_ids；不得生成替代原解读的平行 prose。"
        )
    elif document_type == "full_note":
        interpretation_rules = (
            "\n9. full_note 必须每个 section 恰好生成一页，page.id 与 section.id 完全一致且"
            "顺序不变；每页所有块（包括 review_questions）只能使用该 section 的 "
            "allowed_source_ref_ids。\n"
            "10. original_markdown 只作为视觉块设计依据，不要重写一份平行解读；最后一页"
            "必须同时包含至少一个非 review_questions 视觉块和 review_questions。"
        )
    correction_text = (
        f"\n上一次输出未通过结构校验：{correction}\n"
        "请只纠正这个结构问题，其他内容与 section 对应关系保持不变。\n"
        if correction
        else ""
    )
    return f"""请把下面内容转换成结构化 VisualDocument JSON。

内容标题：{source.title}
文档类型：{document_type}
任务要求：{requirements}

已有文字总结：
{source.summary or "无"}

全文知识大纲：
{outline_text}

带原文引用 ID 的内容：
{evidence_text}
{interpretation_text}

严格要求：
1. 只输出 schema 允许的字段和知识块类型，不输出 HTML。
2. 每个知识块的 source_ref_ids 至少引用一个上文真实存在的 ID，不得编造引用。
3. 图中只保留核心观点；详细解释留给原文字段，不要把长段文字塞进图中。
4. 所有内容使用简体中文，概念准确，短标签适合快速扫描。
5. document_type 必须等于 {document_type}。
6. 如果提供了知识大纲，第 1 页 id 必须为 overview；之后每页 id 必须与对应 section id 完全相同，顺序一致。
7. 全景页至少引用 3 个不同 section 的真实原文依据；章节页只讲对应 section，避免跨页重复。
8. diagram 的前 N-1 页必须填写 transition，用一句“当前能力缺口 → 为什么需要下一节”的承接语连接下一页；最后一页 transition 留空，并在正文块中完成全文收束。
{interpretation_rules}
{correction_text}
"""
