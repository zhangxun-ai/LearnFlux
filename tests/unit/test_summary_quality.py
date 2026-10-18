"""Regression cases for complete summaries across short and long sources."""

from __future__ import annotations

import pytest

from video_transcript_api.llm.summary_quality import summary_incompleteness_reason
from video_transcript_api.llm.summary_quality import summary_source_issues


LONG_INTERVIEW = (
    "提问者：通用技术进入产业以后，应用和组织之间是什么关系？\n"
    "受访者：基础设施、应用探索和原生应用是不同阶段，时间判断有不确定性。\n"
    "提问者：企业应该怎样组织新的业务？\n"
    "受访者：需要结合技术条件、工作流程和实际客户反馈逐步验证。\n"
) * 450

OVERVIEW_ONLY_SUMMARY = """# 和曾鸣聊产业史观：AI三阶段与组织革命

## 1. 概述

本次访谈由张小珺对话战略学者、阿里巴巴集团前总参谋长曾鸣教授。
曾鸣结合自身横跨学术与阿里十九年实战的经验，提出了一套理解AI产业化的历史框架：
任何通用技术颠覆性创新都会经历三个阶段——技术成为社会基础设施、基于基础设施的
应用大爆发、以及诞生原生应用的第三阶段。他判断2026年是第一阶段基本完成、第二阶段
开启的标志年份，当前AI产业中许多应用仍在探索阶段。对话随后将技术变化与企业组织
的演进联系起来，并指出观察产业需要结合具体应用的变化。他讨论了创新过程、企业
战略和组织方式之间的关联，强调判断应当建立在实际探索的基础上。核心结论是：不确定"""


def test_long_interview_with_only_overview_is_incomplete():
    assert len(LONG_INTERVIEW) > 48000
    assert len(OVERVIEW_ONLY_SUMMARY) > 50
    assert summary_incompleteness_reason(
        LONG_INTERVIEW, OVERVIEW_ONLY_SUMMARY
    ) == "overview_without_analysis"


def test_short_single_topic_accepts_complete_prose_without_headings():
    source = (
        "保存重要文档前，先确认文件名和目标目录。保存后重新打开一次，"
        "确认内容可以读取。这个方法主要用于避免把文档误存到临时目录。"
    ) * 12
    summary = (
        "这段内容介绍保存文档时的两个检查动作：保存前确认文件名与目标目录，"
        "保存后重新打开检查内容。它解决的是误存位置和未成功保存的问题，"
        "适用于需要长期保留的重要文档。"
    )
    assert summary_incompleteness_reason(source, summary) is None


def test_short_source_accepts_overview_as_its_complete_analysis():
    assert summary_incompleteness_reason(
        "单一观点的短视频。" * 60,
        "## 概述\n\n先确认文件保存位置，再重新打开验证保存结果。",
    ) is None


def test_long_interview_accepts_expanded_themes_with_complete_ending():
    summary = """这场对话讨论通用技术发展阶段与企业组织变化之间的关系。

## 通用技术发展的不同阶段

受访者区分基础设施、应用探索和原生应用三个阶段。他把2026年描述为一个可能的
转折年份，这属于其产业判断，并非经过外部核验的确定时间表。

## 企业组织应当怎样响应变化

面对提问者关于新业务组织方式的追问，受访者强调结合技术条件、流程变化和客户
反馈逐步验证。对话将技术进展和组织调整联系起来，但没有提出所有企业通用的组织方案。
"""
    assert summary_incompleteness_reason(LONG_INTERVIEW, summary) is None


def test_long_source_does_not_require_a_fixed_number_of_headings():
    summary = (
        "对话围绕技术应用与组织变化展开。提问者提出新业务组织问题，"
        "受访者认为应该结合技术条件和实际客户反馈逐步验证。"
        "原文没有给出可直接应用于所有企业的组织方案。"
    )
    assert summary_incompleteness_reason(LONG_INTERVIEW, summary) is None


@pytest.mark.parametrize("summary", [None, "", " \n\t"])
def test_missing_or_whitespace_summary_is_incomplete(summary):
    assert summary_incompleteness_reason("source", summary) == "empty_summary"


@pytest.mark.parametrize("ending", ["：", ":"])
def test_explanation_marker_without_explanation_is_incomplete(ending):
    assert summary_incompleteness_reason(
        LONG_INTERVIEW, "## 关键结论\n\n这个方法的适用条件是" + ending
    ) == "dangling_explanation"


def test_final_section_without_body_is_incomplete():
    assert summary_incompleteness_reason(
        LONG_INTERVIEW,
        "## 技术阶段\n\n技术进入产业后需要持续验证。\n\n### 组织方式",
    ) == "empty_final_section"


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_unclosed_code_block_is_incomplete(fence):
    assert summary_incompleteness_reason(
        "操作教程。" * 100,
        "## 验证命令\n\n" + fence + "shell\npython main.py --help",
    ) == "unclosed_code_block"


def test_different_fence_type_does_not_close_code_block():
    assert summary_incompleteness_reason(
        "操作教程。" * 100,
        "## 验证命令\n\n```shell\npython main.py --help\n~~~",
    ) == "unclosed_code_block"


def test_closed_code_block_in_complete_tutorial_is_valid():
    assert summary_incompleteness_reason(
        "操作教程。" * 100,
        "## 验证命令\n\n```shell\npython main.py --help\n```\n\n应显示命令帮助。",
    ) is None


@pytest.mark.parametrize("heading", ["概述", "1. 概述", "概述（Overview）", "Overview"])
def test_overview_only_variants_are_rejected_for_long_sources(heading):
    assert summary_incompleteness_reason(
        LONG_INTERVIEW, "# 访谈主题\n\n## " + heading + "\n\n仅介绍了开场问题。"
    ) == "overview_without_analysis"


def test_invented_technical_reference_triggers_source_correction():
    assert summary_source_issues("IBM evolved after computers appeared.", "IBM relied on OS/360.") == [
        "reference absent from source: OS/360"
    ]


def test_quote_check_ignores_punctuation_and_markdown_emphasis():
    source = "未来的每个人就是一个一人公司，你就这个六边形战士。"
    assert summary_source_issues(source, "他认为：‘个人能力增强’。原话是：“未来的**每个人**就是一个一人公司”。") == []


def test_paraphrase_is_not_mistaken_for_a_direct_quote():
    assert summary_source_issues("Source description.", "This is a normal paraphrase without quotation marks.") == []


def test_fabricated_direct_quote_triggers_source_correction():
    issues = summary_source_issues("原文仅讨论组织变化。", "他断言：“所有企业都必须在三年内完成转型”。")
    assert len(issues) == 1
    assert "direct quote" in issues[0]
