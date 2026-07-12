import pytest
from pydantic import ValidationError


def _source_ref():
    return {
        "id": "study:view-1:line:line-1",
        "owner_type": "study",
        "owner_id": "view-1",
        "excerpt": "LLM 负责生成文本，Agent Skill 负责把能力封装成可复用流程。",
        "line_id": "line-1",
        "paragraph_index": 0,
        "start_seconds": 12.5,
        "end_seconds": 18.0,
    }


def _hero_block(block_id="hero-1"):
    return {
        "id": block_id,
        "type": "hero_summary",
        "title": "核心结论",
        "source_ref_ids": ["study:view-1:line:line-1"],
        "headline": "从语言模型走向可执行能力",
        "summary": "模型提供推理能力，工具和 Skill 让能力可以稳定落地。",
        "points": ["LLM 是推理核心", "工具连接外部世界", "Skill 固化流程"],
    }


def _review_block():
    return {
        "id": "review-1",
        "type": "review_questions",
        "title": "主动回忆",
        "source_ref_ids": ["study:view-1:line:line-1"],
        "questions": [
            {"question": "LLM 和 Skill 的主要差异是什么？", "answer": "LLM 推理，Skill 固化可复用流程。"},
            {"question": "工具在 Agent 中承担什么作用？", "answer": "连接外部系统并执行动作。"},
        ],
    }


def _document(**overrides):
    payload = {
        "version": 1,
        "document_type": "overview",
        "title": "从 LLM 到 Agent Skill",
        "subtitle": "一条主线理解核心概念",
        "recommended_style": "study-notes",
        "selected_diagram_type": "concept_chain",
        "diagram_recommendations": [
            {
                "diagram_type": "concept_chain",
                "label": "概念链",
                "rationale": "内容围绕多个前后关联的概念展开。",
                "score": 0.92,
            }
        ],
        "pages": [
            {
                "id": "page-1",
                "title": "核心主线",
                "learning_goal": "理解 LLM、工具和 Skill 的关系",
                "blocks": [_hero_block()],
            }
        ],
        "source_refs": [_source_ref()],
    }
    payload.update(overrides)
    return payload


def test_visual_document_accepts_known_blocks_and_stable_refs():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    document = VisualDocument.model_validate(_document())

    assert document.pages[0].blocks[0].type == "hero_summary"
    assert document.pages[0].learning_goal == "理解 LLM、工具和 Skill 的关系"
    assert document.source_refs[0].id == "study:view-1:line:line-1"


def test_labeled_items_accept_learning_scaffold_fields():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    payload["pages"][0]["blocks"] = [
        {
            "id": "token-chain",
            "type": "concept_chain",
            "title": "Token 如何进入模型",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "items": [
                {
                    "id": "text",
                    "label": "人类文字",
                    "description": "用户输入自然语言。",
                    "why_needed": "这是用户真正想表达的意思，模型需要先接收它。",
                    "mechanism": "Tokenizer 会把文字切成更小的可编号单位。",
                    "example": "“我喜欢 AI”会先被切成若干 token。",
                    "misconception": "Token 不一定等于一个汉字或一个英文单词。",
                },
                {
                    "id": "token-id",
                    "label": "Token ID",
                    "description": "模型实际处理的是数字编号。",
                    "why_needed": "模型底层做数学计算，不能直接计算文字本身。",
                    "example": "文字片段会映射成类似 2512、9843 的编号。",
                },
            ],
        }
    ]

    document = VisualDocument.model_validate(payload)
    item = document.pages[0].blocks[0].items[0]

    assert item.why_needed == "这是用户真正想表达的意思，模型需要先接收它。"
    assert item.example == "“我喜欢 AI”会先被切成若干 token。"


def test_visual_document_rejects_unknown_block_type():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    payload["pages"][0]["blocks"] = [
        {
            "id": "bad-1",
            "type": "freeform_html",
            "title": "不受信任内容",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "html": "<script>alert(1)</script>",
        }
    ]

    with pytest.raises(ValidationError):
        VisualDocument.model_validate(payload)


def test_mind_map_enforces_branch_limits():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    payload["pages"][0]["blocks"] = [
        {
            "id": "mind-map-1",
            "type": "mind_map",
            "title": "Agent 能力地图",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "center_label": "Agent",
            "branches": [
                {"label": f"分支 {index}", "children": [f"节点 {child}" for child in range(7)]}
                for index in range(9)
            ],
        }
    ]

    with pytest.raises(ValidationError):
        VisualDocument.model_validate(payload)


def _contrast_pair(index=1, **overrides):
    pair = {
        "bad_label": f"错误表达 {index}",
        "bad_signal": "会释放负面信号",
        "risk_label": "风险判断",
        "better_label": f"替代表达 {index}",
        "better_signal": "更利于决策",
    }
    pair.update(overrides)
    return pair


def test_visual_document_accepts_paired_contrast_block():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document(
        selected_diagram_type="paired_contrast",
        diagram_recommendations=[
            {
                "diagram_type": "paired_contrast",
                "label": "配对转化",
                "rationale": "适合把错误表达转成可采购信号。",
                "score": 0.91,
            }
        ],
    )
    payload["pages"][0]["blocks"] = [
        {
            "id": "contrast-1",
            "type": "paired_contrast",
            "title": "错误信号转化",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "pairs": [
                _contrast_pair(
                    1,
                    bad_label="身体不好",
                    bad_signal="可能无法稳定出勤",
                    risk_label="出勤风险",
                    better_label="耐力运动",
                    better_signal="证明恢复力和稳定投入",
                ),
                _contrast_pair(
                    2,
                    bad_label="抱怨消耗",
                    bad_signal="低积累高消耗",
                    risk_label="负资产",
                    better_label="解决问题",
                ),
            ],
        }
    ]

    document = VisualDocument.model_validate(payload)

    assert document.pages[0].blocks[0].type == "paired_contrast"
    assert document.selected_diagram_type == "paired_contrast"


def test_paired_contrast_rejects_more_than_six_pairs():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    payload["pages"][0]["blocks"] = [
        {
            "id": "contrast-1",
            "type": "paired_contrast",
            "title": "错误信号转化",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "pairs": [_contrast_pair(index) for index in range(7)],
        }
    ]

    with pytest.raises(ValidationError):
        VisualDocument.model_validate(payload)


def test_visual_document_accepts_signal_flow_block():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document(selected_diagram_type="signal_flow")
    payload["pages"][0]["blocks"] = [
        {
            "id": "signal-1",
            "type": "signal_flow",
            "title": "老板决策信号流",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "steps": [
                {"label": "候选表达", "description": "我被上份工作消耗"},
                {"label": "老板解读", "description": "低积累高消耗"},
                {"label": "决策后果", "description": "无法向股东交代"},
            ],
            "outcome_label": "需要改成采购信号",
        }
    ]

    document = VisualDocument.model_validate(payload)

    assert document.pages[0].blocks[0].type == "signal_flow"
    assert document.pages[0].blocks[0].outcome_label == "需要改成采购信号"


def test_visual_document_accepts_decision_axis_block():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document(selected_diagram_type="decision_axis")
    payload["pages"][0]["blocks"] = [
        {
            "id": "axis-1",
            "type": "decision_axis",
            "title": "老板采购坐标",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "x_axis": {"low": "低积累", "high": "高积累"},
            "y_axis": {"low": "低消耗", "high": "高消耗"},
            "quadrants": [
                {
                    "label": "优先采购",
                    "description": "高积累、低消耗",
                    "x": "high",
                    "y": "low",
                    "tone": "good",
                },
                {
                    "label": "谨慎排除",
                    "description": "低积累、高消耗",
                    "x": "low",
                    "y": "high",
                    "tone": "bad",
                },
            ],
        }
    ]

    document = VisualDocument.model_validate(payload)

    assert document.pages[0].blocks[0].type == "decision_axis"
    assert document.pages[0].blocks[0].quadrants[0].tone == "good"


@pytest.mark.parametrize(
    "nodes",
    [
        [
            {"id": "root", "label": "根", "description": "根节点"},
            {"id": "root", "label": "重复", "description": "重复 ID", "parent_id": "root"},
        ],
        [
            {"id": "a", "label": "A", "description": "节点 A", "parent_id": "b"},
            {"id": "b", "label": "B", "description": "节点 B", "parent_id": "a"},
        ],
    ],
)
def test_hierarchy_rejects_duplicate_ids_and_cycles(nodes):
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    payload["pages"][0]["blocks"] = [
        {
            "id": "hierarchy-1",
            "type": "hierarchy",
            "title": "能力层级",
            "source_ref_ids": ["study:view-1:line:line-1"],
            "nodes": nodes,
        }
    ]

    with pytest.raises(ValidationError):
        VisualDocument.model_validate(payload)


def test_diagram_recommendations_are_sorted_and_limited():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document(
        selected_diagram_type=None,
        diagram_recommendations=[
            {"diagram_type": "timeline", "label": "时间线", "rationale": "有阶段", "score": 0.55},
            {"diagram_type": "comparison", "label": "对比图", "rationale": "有差异", "score": 0.72},
            {"diagram_type": "mind_map", "label": "思维导图", "rationale": "有分支", "score": 0.61},
            {"diagram_type": "process_flow", "label": "流程图", "rationale": "有步骤", "score": 0.96},
        ],
    )

    document = VisualDocument.model_validate(payload)

    assert [item.diagram_type for item in document.diagram_recommendations] == [
        "process_flow",
        "comparison",
        "mind_map",
    ]
    assert document.selected_diagram_type == "process_flow"


def test_page_requires_learning_goal():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    del payload["pages"][0]["learning_goal"]

    with pytest.raises(ValidationError):
        VisualDocument.model_validate(payload)


def test_visual_page_accepts_optional_transition_and_limits_length():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    payload = _document()
    payload["pages"][0]["transition"] = "模型有了语言能力，下一步需要把推理连接到真实行动。"

    document = VisualDocument.model_validate(payload)

    assert document.pages[0].transition == payload["pages"][0]["transition"]

    payload["pages"][0]["transition"] = "过" * 241
    with pytest.raises(ValidationError):
        VisualDocument.model_validate(payload)


def test_full_note_requires_review_questions_on_last_page():
    from video_transcript_api.visual_learning.schemas import VisualDocument

    pages = [
        {
            "id": f"page-{index}",
            "title": f"第 {index} 页",
            "learning_goal": "建立核心概念",
            "blocks": [_hero_block(f"hero-{index}")],
        }
        for index in range(1, 4)
    ]

    with pytest.raises(ValidationError):
        VisualDocument.model_validate(_document(document_type="full_note", pages=pages))

    pages[-1]["blocks"].append(_review_block())
    document = VisualDocument.model_validate(
        _document(document_type="full_note", pages=pages)
    )
    assert document.pages[-1].blocks[-1].type == "review_questions"


def test_source_reference_accepts_start_and_end_seconds():
    from video_transcript_api.visual_learning.schemas import SourceReference

    source_ref = SourceReference.model_validate(_source_ref())

    assert source_ref.start_seconds == 12.5
    assert source_ref.end_seconds == 18.0


def test_visual_outline_requires_four_to_eight_evidence_backed_sections():
    from video_transcript_api.visual_learning.schemas import VisualOutline

    payload = {
        "title": "高效学习的完整知识架构",
        "thesis": "学习效率取决于知识选择、搜索、理解与应用的完整闭环。",
        "audience_goal": "建立可执行的高效学习系统",
        "sections": [
            {
                "id": f"section-{index}",
                "title": title,
                "core_message": message,
                "key_points": ["关键原则", "落地动作"],
                "evidence_queries": [title, message[:8]],
                "recommended_block_type": "concept_grid",
            }
            for index, (title, message) in enumerate(
                [
                    ("知识选择", "先判断知识价值"),
                    ("知识搜索", "建立全景搜索视角"),
                    ("深度理解", "从思维模式理解知识"),
                    ("实践应用", "按需学习并立即使用"),
                ],
                1,
            )
        ],
    }

    outline = VisualOutline.model_validate(payload)
    assert len(outline.sections) == 4
    assert outline.sections[0].evidence_queries == ["知识选择", "先判断知识价值"]

    payload["sections"] = payload["sections"][:3]
    with pytest.raises(ValidationError):
        VisualOutline.model_validate(payload)
