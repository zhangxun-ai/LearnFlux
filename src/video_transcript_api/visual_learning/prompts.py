"""Prompts for constrained visual learning document generation."""

from __future__ import annotations

import json

from .source_resolver import VisualLearningSource


VISUAL_BRIEF_PROMPT_VERSION = 2
DIAGRAM_STRATEGY_PROMPT_VERSION = 1
VISUAL_BLOCK_SET_VERSION = 3

VISUAL_BRIEF_RESPONSE_SCHEMA = {
    "title": "VisualBrief",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "core_thesis",
        "learner_level",
        "audience_task",
        "content_archetype",
        "must_answer",
        "must_show",
        "concrete_examples",
        "confusing_terms",
        "evidence_ref_ids",
    ],
    "properties": {
        "core_thesis": {"type": "string"},
        "learner_level": {"type": "string"},
        "audience_task": {"type": "string"},
        "content_archetype": {"type": "string"},
        "must_answer": {"type": "array", "items": {"type": "string"}},
        "must_show": {"type": "array", "items": {"type": "string"}},
        "concrete_examples": {"type": "array", "items": {"type": "string"}},
        "confusing_terms": {"type": "array", "items": {"type": "string"}},
        "evidence_ref_ids": {"type": "array", "items": {"type": "string"}},
    },
}

DIAGRAM_STRATEGY_RESPONSE_SCHEMA = {
    "title": "DiagramStrategy",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidate_strategies",
        "selected_strategy",
        "rejected_reasoning",
    ],
    "properties": {
        "candidate_strategies": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "diagram_type",
                    "why_it_fits",
                    "layout_intent",
                    "text_budget",
                    "risk",
                    "score_breakdown",
                ],
                "properties": {
                    "diagram_type": {"type": "string"},
                    "why_it_fits": {"type": "string"},
                    "layout_intent": {"type": "string"},
                    "text_budget": {"type": "string"},
                    "risk": {"type": "string"},
                    "score_breakdown": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "task_fit",
                            "cognitive_compression",
                            "visual_relation",
                            "evidence_fidelity",
                            "space_efficiency",
                            "total",
                        ],
                        "properties": {
                            "task_fit": {"type": "number", "minimum": 0, "maximum": 25},
                            "cognitive_compression": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 25,
                            },
                            "visual_relation": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 20,
                            },
                            "evidence_fidelity": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 20,
                            },
                            "space_efficiency": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 10,
                            },
                            "total": {"type": "number", "minimum": 0, "maximum": 100},
                        },
                    },
                },
            },
        },
        "selected_strategy": {"type": "string"},
        "rejected_reasoning": {"type": "string"},
    },
}


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


def build_visual_brief_prompt(
    source: VisualLearningSource,
    document_type: str,
    *,
    outline: dict | None = None,
    evidence: str = "",
) -> str:
    outline_text = (
        json.dumps(outline, ensure_ascii=False, indent=2) if outline else "无（短内容）"
    )
    evidence_text = evidence or source.content or "无"
    return f"""请先把材料整理成面向学习者的 Visual Brief，用于后续选择图解策略。

内容标题：{source.title}
文档类型：{document_type}

已有文字总结：
{source.summary or "无"}

全文知识大纲：
{outline_text}

带原文引用 ID 的内容：
{evidence_text}

要求：
1. 不要输出 VisualDocument，不要输出 HTML，也不要开始排版。
2. 默认用户是“不懂但想学会”的学习者；除非材料明确面向专家，否则 learner_level 写 beginner。
3. `core_thesis` 写出一条最重要的主线，不超过 80 字。
4. `audience_task` 写用户看完图后应该能用自己的话完成的动作。
5. `content_archetype` 使用英文短枚举，例如 signal_interpretation、process、decision、causal_chain、taxonomy。
6. `must_answer` 列出新手看图后必须被回答的问题，优先包含“为什么需要它”“它怎么工作”“具体例子是什么”。
7. `must_show` 列必须画出来的关系或机制，不要只列抽象名词。
8. `concrete_examples` 列材料中最适合降低理解门槛的例子；没有现成例子时基于原文概念给出最小示例，不得加入材料外的新结论。
9. `confusing_terms` 列最容易让新手卡住的术语，并在后续图解中用白话拆开。
10. `evidence_ref_ids` 只基于真实 source_ref_ids，不得编造引用。
11. 只输出 JSON，字段包含 core_thesis、learner_level、audience_task、content_archetype、must_answer、must_show、concrete_examples、confusing_terms、evidence_ref_ids。
"""


def build_diagram_strategy_prompt(
    source: VisualLearningSource,
    brief: dict,
    document_type: str,
    diagram_type: str = "auto",
    *,
    correction: str = "",
) -> str:
    brief_text = json.dumps(brief, ensure_ascii=False, indent=2)
    correction_text = (
        f"\n上一次策略没有通过校验：{correction}\n请重新选择策略，必须满足所有硬性门槛。\n"
        if correction
        else ""
    )
    return f"""请基于 Visual Brief 选择最适合的图解表达策略。

内容标题：{source.title}
文档类型：{document_type}
用户指定图解类型：{diagram_type}

Visual Brief：
{brief_text}

可选策略：
- paired_contrast：适合把错误表达、误解、雷区转化成更好的表达。
- signal_flow：适合展示“表达 -> 解读 -> 风险/结果 -> 修正”的流动。
- decision_axis：适合展示两个关键判断维度如何影响选择。
- process_flow：适合真实步骤和流程。
- hierarchy / mind_map / timeline / concept_chain：仅在结构确实匹配时使用。
- comparison：只用于纯分类差异；如果只是雷区 vs 加分项，优先考虑 paired_contrast 或 decision_axis。

评分规则（满分 100）：
- 任务匹配 25：是否直接服务 audience_task。
- 认知脚手架 25：是否让不懂的学习者看懂原因、机制和例子，而不是把术语换成卡片。
- 视觉关系 20：是否能画出明确关系，如 pairs、axis、flow steps、parent、timeline。
- 证据忠实 20：是否能只基于真实 source_ref_ids 落地。
- 空间效率 10：移动端是否紧凑，空间效率必须 >= 6/10。

硬性门槛：
1. candidate_strategies 必须给出 2-3 个候选。
2. 每个候选包含 diagram_type、why_it_fits、layout_intent、text_budget、risk、score_breakdown。
3. score_breakdown 的所有分数必须是 JSON number，例如 88；禁止字符串、百分比、"88/100" 或嵌套对象。
4. selected_strategy 必须选择总分最高的候选。
5. 总分必须 >= 80。
6. task_fit 必须 >= 18/25，cognitive_compression 必须 >= 18/25，visual_relation 必须 >= 14/20，evidence_fidelity 必须 >= 16/20，空间效率必须 >= 6/10。
7. 如果任何门槛不满足，重新选择策略，不要勉强输出。
8. 只输出 JSON，不输出 VisualDocument。
{correction_text}
"""


def build_visual_prompt(
    source: VisualLearningSource,
    document_type: str,
    diagram_type: str = "auto",
    *,
    outline: dict | None = None,
    evidence: str = "",
    interpretation_sections: list[dict] | None = None,
    brief: dict | None = None,
    strategy: dict | None = None,
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
            "根据内容生成一个完整、可连续阅读的教学型知识地图，帮助不熟悉主题的用户"
            "真正理解核心概念、原因、机制和例子。"
            "短内容输出 1-3 页；如果提供了知识大纲，必须输出 1 页全景图"
            "加每个 section 一页的核心笔记，并按大纲顺序排列；不要做成需要来回切换的幻灯片。"
            "全景页优先呈现核心主线、关键节点、节点关系和最终结论；章节页必须把"
            "支撑这条主线的关键概念讲到新手能复述。"
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
    strategy_context_text = ""
    if document_type == "diagram":
        brief_text = json.dumps(brief, ensure_ascii=False, indent=2) if brief else "无"
        strategy_text = (
            json.dumps(strategy, ensure_ascii=False, indent=2) if strategy else "无"
        )
        strategy_context_text = f"""
Visual Brief：
{brief_text}

已选图解策略：
{strategy_text}
"""
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
{strategy_context_text}
{interpretation_text}

严格要求：
1. 只输出 schema 允许的字段和知识块类型，不输出 HTML。
2. 每个知识块的 source_ref_ids 至少引用一个上文真实存在的 ID，不得编造引用。
3. diagram 默认面向“不懂但想学会”的用户，不能假设用户已经理解专业术语。
4. 所有抽象概念必须用白话解释清楚：它是什么、为什么需要、怎么工作、具体例子；禁止只写“桥梁作用”“底层逻辑”“赋能”“闭环”等空泛词。
5. concept_chain、process_flow、hierarchy、concept_grid 中的核心 item 应优先填写 why_needed 和 example；涉及转换、运算、传递时填写 mechanism；容易误解时填写 misconception。
6. 所有内容使用简体中文，概念准确；短标签用于定位，解释必须服务理解而不是制造黑话。
7. document_type 必须等于 {document_type}。
8. 如果提供了知识大纲，第 1 页 id 必须为 overview；之后每页 id 必须与对应 section id 完全相同，顺序一致。
9. 全景页至少引用 3 个不同 section 的真实原文依据；章节页只讲对应 section，避免跨页重复。
10. diagram 的前 N-1 页必须填写 transition，用一句“当前能力缺口 → 为什么需要下一节”的承接语连接下一页；最后一页 transition 留空，并在正文块中完成全文收束。
11. diagram 必须优先使用关系型视觉块（paired_contrast、signal_flow、decision_axis、concept_chain、hierarchy、process_flow、mind_map、comparison），每页最多 2 个主要视觉块，优先 1 个关系型主图 + 1 个辅助 callout；不要把解释写成长段散文，应该拆成“定义 / 原因 / 机制 / 例子”的短句槽位。
11a. 不得在同一页同时放 hero_summary、mind_map、comparison、process_flow 等三种以上主块；内容多时拆页，或合并进 selected_strategy 对应的主图结构。
12. 如果提供了已选图解策略，最终 VisualDocument 必须按 selected_strategy 落地，不要重新发明结构。
13. comparison 只用于纯分类差异；对比、纠错、雷区转化、决策判断优先使用 paired_contrast、signal_flow 或 decision_axis。
{interpretation_rules}
{correction_text}
"""
