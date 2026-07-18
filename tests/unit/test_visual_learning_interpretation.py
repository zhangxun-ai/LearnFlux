"""Tests for deterministic interpretation section building."""

import pytest

from video_transcript_api.visual_learning.interpretation import (
    InterpretationNotReady,
    build_interpretation_sections,
    normalize_interpretation_markdown,
)
from video_transcript_api.visual_learning.schemas import SourceReference


def _build(markdown: str):
    return build_interpretation_sections(
        markdown,
        owner_type="study",
        owner_id="view-1",
        source_refs=[],
        ref_texts={},
    )


def test_sections_preserve_heading_markdown_and_stable_ids():
    sections = _build(
        "## 起点\n当前**状态**。\n\n"
        "## 路径\n- 降低摩擦\n- 保持反馈\n\n"
        "## 终点\n目标行为。"
    )

    assert [item.id for item in sections] == [
        "section-01",
        "section-02",
        "section-03",
    ]
    assert [item.title for item in sections] == ["起点", "路径", "终点"]
    assert sections[1].markdown == "- 降低摩擦\n- 保持反馈\n\n"
    assert sections[0].source_ref_ids == (
        "study:view-1:summary:section:section-01",
    )


def test_deeper_markdown_headings_are_clean_section_titles():
    sections = _build(
        "### 1. 概述（Overview）\n总览内容。\n\n"
        "#### 🧭 核心概念：雇佣即采购，简历即广告\n概念内容。\n\n"
        "#### 💪 老板找人的四大特征\n特征内容。"
    )

    assert [item.title for item in sections] == [
        "1. 概述（Overview）",
        "🧭 核心概念：雇佣即采购，简历即广告",
        "💪 老板找人的四大特征",
    ]
    assert all("#" not in item.title for item in sections)


def test_heading_free_markdown_uses_non_empty_paragraphs():
    sections = _build("第一段。\n\n第二段第一行。\n第二段第二行。\n\n第三段。")

    assert [item.markdown for item in sections] == [
        "第一段。\n\n",
        "第二段第一行。\n第二段第二行。\n\n",
        "第三段。",
    ]


def test_more_than_eight_sections_are_merged_deterministically():
    markdown = "\n\n".join(f"## 主题 {index}\n内容 {index}" for index in range(1, 11))

    first = _build(markdown)
    second = _build(markdown)

    assert len(first) == 8
    assert first == second
    assert [item.id for item in first] == [
        f"section-{index:02d}" for index in range(1, 9)
    ]
    merged_markdown = "\n".join(item.markdown for item in first)
    assert all(f"内容 {index}" in merged_markdown for index in range(1, 11))


def test_long_multi_paragraph_section_is_split_to_minimum_three():
    sections = _build("## 单一主题\n第一段。\n\n第二段。\n\n第三段。")

    assert len(sections) == 3
    assert [item.markdown for item in sections] == [
        "第一段。\n\n",
        "第二段。\n\n",
        "第三段。",
    ]
    assert [item.title for item in sections] == ["单一主题"] * 3


def test_fewer_than_three_non_empty_sections_are_not_ready():
    with pytest.raises(InterpretationNotReady):
        _build("只有一段。\n\n只有第二段。")


def test_preamble_before_first_heading_is_preserved_as_intro_section():
    markdown = (
        "# 文档总览\n\n开场 **说明**。\n\n"
        "## 起点\n正文 A。\n\n"
        "## 路径\n正文 B。\n\n"
        "## 终点\n正文 C。"
    )

    sections = _build(markdown)

    assert [item.id for item in sections] == [
        "section-01",
        "section-02",
        "section-03",
        "section-04",
    ]
    assert sections[0].markdown == "# 文档总览\n\n开场 **说明**。\n\n"
    assert [item.title for item in sections[1:]] == ["起点", "路径", "终点"]


def test_document_wrappers_and_front_matter_are_removed_before_sectioning():
    wrapped = (
        "\ufeff```markdown\n"
        "---\n"
        "title: 示例课程\n"
        "source_type: video_course\n"
        "---\n"
        "## 第一节\n正文 A。\n\n"
        "## 第二节\n正文中的分隔线：\n\n---\n\n继续。\n\n"
        "## 第三节\n正文 C。\n"
        "```"
    )

    normalized = normalize_interpretation_markdown(wrapped)
    sections = _build(wrapped)

    assert normalized.startswith("## 第一节")
    assert "title: 示例课程" not in normalized
    assert "\n---\n" in normalized
    assert [section.title for section in sections] == ["第一节", "第二节", "第三节"]
    assert all(section.title != "---" for section in sections)


def test_split_preserves_exact_paragraph_separators_and_markdown_constructs():
    body = "- 第一项\n\n\n> 引用内容\n \n\n```text\n代码\n```\n\n"

    sections = _build(f"## 单一主题\n{body}")

    assert len(sections) == 3
    assert "".join(item.markdown for item in sections) == body
    assert sections[0].markdown == "- 第一项\n\n\n"
    assert sections[1].markdown == "> 引用内容\n \n\n"
    assert sections[2].markdown == "```text\n代码\n```\n\n"


def test_heading_inside_backtick_fence_is_not_a_section_boundary():
    fenced = "```markdown\n## not a heading\n内容\n```\n\n"
    sections = _build(
        f"## 第一节\n{fenced}正文。\n\n"
        "## 第二节\n第二段。\n\n"
        "## 第三节\n第三段。"
    )

    assert [item.title for item in sections] == ["第一节", "第二节", "第三节"]
    assert sections[0].markdown == f"{fenced}正文。\n\n"


def test_atx_headings_allow_up_to_three_leading_spaces_without_blank_lines():
    sections = _build(
        " ## 第一节\n内容一。\n"
        "  ## 第二节\n内容二。\n"
        "   ## 第三节\n"
        "    ## four-space indented code\n"
        "内容三。"
    )

    assert [item.title for item in sections] == ["第一节", "第二节", "第三节"]
    assert [item.markdown for item in sections] == [
        "内容一。\n",
        "内容二。\n",
        "    ## four-space indented code\n内容三。",
    ]


def test_blank_lines_inside_tilde_fence_do_not_split_the_fence():
    fenced = "~~~python\nfirst()\n\nsecond()\n~~~\n\n"
    sections = _build(
        f"## 单一主题\n{fenced}"
        "外部第二段。\n\n"
        "外部第三段。"
    )

    assert len(sections) == 3
    assert sections[0].markdown == fenced
    assert "".join(item.markdown for item in sections) == (
        f"{fenced}外部第二段。\n\n外部第三段。"
    )


def test_merge_preserves_exact_body_order_and_blank_line_separators():
    markdown = "".join(
        f"## 主题 {index}\n内容 {index}\n{' ' if index % 2 else ''}\n\n"
        for index in range(1, 11)
    )
    expected_body = "".join(
        f"内容 {index}\n{' ' if index % 2 else ''}\n\n"
        for index in range(1, 11)
    )

    sections = _build(markdown)

    assert len(sections) == 8
    assert "".join(item.markdown for item in sections) == expected_body


def _source_ref(ref_id: str, *, owner_type: str = "study") -> SourceReference:
    return SourceReference(
        id=ref_id,
        owner_type=owner_type,
        owner_id="view-1" if owner_type == "study" else "series-1",
        excerpt="Evidence excerpt",
    )


def test_sections_only_append_positive_overlap_evidence():
    matching_id = "study:view-1:line:1"
    unrelated_id = "study:view-1:line:unrelated"
    synthetic_id = "study:view-1:summary:section:old-section"
    sections = build_interpretation_sections(
        "## 机器学习\n模型训练方法。\n\n## 部署\n上线流程。\n\n## 复盘\n持续改进。",
        owner_type="study",
        owner_id="view-1",
        source_refs=[
            _source_ref(matching_id),
            _source_ref(unrelated_id),
            _source_ref(synthetic_id),
        ],
        ref_texts={
            matching_id: "机器学习模型需要训练。",
            unrelated_id: "今天天气晴朗。",
            synthetic_id: "机器学习模型训练方法。",
        },
    )

    assert sections[0].source_ref_ids == (
        "study:view-1:summary:section:section-01",
        matching_id,
    )
    assert unrelated_id not in sections[0].source_ref_ids
    assert synthetic_id not in sections[0].source_ref_ids


def test_real_collection_source_summary_remains_eligible():
    summary_id = "collection:series-1:source:source-1:summary"
    sections = build_interpretation_sections(
        "第一段讲增长飞轮。\n\n第二段讲产品定位。\n\n第三段讲用户反馈。",
        owner_type="collection",
        owner_id="series-1",
        source_refs=[_source_ref(summary_id, owner_type="collection")],
        ref_texts={summary_id: "增长飞轮依赖稳定反馈。"},
    )

    assert sections[0].source_ref_ids == (
        "collection:series-1:summary:section:section-01",
        summary_id,
    )


def test_ascii_evidence_uses_case_insensitive_whole_tokens():
    matching_id = "study:view-1:line:matching"
    unrelated_id = "study:view-1:line:unrelated-ascii"
    sections = build_interpretation_sections(
        "## Alpha model\nTraining flow.\n\n## Deploy\nRelease flow.\n\n## Review\nMetrics.",
        owner_type="study",
        owner_id="view-1",
        source_refs=[
            _source_ref(matching_id),
            _source_ref(unrelated_id),
        ],
        ref_texts={
            matching_id: "ALPHA baseline",
            unrelated_id: "alphabet soup",
        },
    )

    assert sections[0].source_ref_ids == (
        "study:view-1:summary:section:section-01",
        matching_id,
    )
    assert unrelated_id not in sections[0].source_ref_ids


def test_matching_evidence_is_capped_at_six_with_source_order_tie_break():
    ref_ids = [f"study:view-1:line:{index}" for index in range(1, 9)]
    sections = build_interpretation_sections(
        "## 反馈循环\n建立反馈循环。\n\n## 第二节\n其他内容。\n\n## 第三节\n更多内容。",
        owner_type="study",
        owner_id="view-1",
        source_refs=[_source_ref(ref_id) for ref_id in ref_ids],
        ref_texts={ref_id: "反馈循环" for ref_id in reversed(ref_ids)},
    )

    assert sections[0].source_ref_ids == (
        "study:view-1:summary:section:section-01",
        *ref_ids[:6],
    )
