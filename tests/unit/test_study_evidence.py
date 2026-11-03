"""Source coverage, bounded context and grounded multi-source comparisons."""

from unittest.mock import Mock
import pytest

from video_transcript_api.study.evidence import retrieve_evidence
from video_transcript_api.study.service import StudyService


def _long_lines():
    lines = [{"id": f"line-{index + 1}", "text": "基础练习和日常记录。" * 10,
              "seekable": True, "start_seconds": index * 30} for index in range(800)]
    lines[40]["text"] = "稀疏检索采用关键词匹配，优势在于可解释性。"
    lines[-2]["text"] = "最后一章：混合检索把稀疏检索与语义召回结合，再用重排提高准确性。"
    return lines


def test_long_course_retrieves_tail_and_cross_chapter_evidence():
    evidence = retrieve_evidence(_long_lines(), "稀疏检索与混合检索有什么不同？", max_chars=4500)
    text = "\n".join(item["text"] for item in evidence["passages"])
    assert "最后一章" in text
    assert "可解释性" in text
    assert evidence["mode"] == "retrieved"
    assert evidence["context_chars"] <= 4500
    tail = next(item for item in evidence["passages"] if "最后一章" in item["text"])
    assert tail["line_id"].startswith("line-")
    assert tail["start_seconds"] > 20000


def test_long_course_miss_does_not_substitute_first_chapter():
    evidence = retrieve_evidence(_long_lines(), "猕猴桃种植需要哪些肥料？")
    assert not evidence["matched"]
    assert evidence["passages"] == []
    assert evidence["context_chars"] == 0


def test_overview_samples_whole_course_and_discloses_partial_coverage():
    lines = _long_lines()
    lines[0]["text"] = "开篇内容。"
    lines[-1]["text"] = "课程收尾内容。"
    evidence = retrieve_evidence(lines, "总结这门课程的主要内容", max_chars=16000)
    text = "\n".join(item["text"] for item in evidence["passages"])
    assert "开篇内容" in text and "课程收尾内容" in text
    assert evidence["mode"] == "sampled"
    assert evidence["context_chars"] <= 16000


def test_short_source_keeps_complete_original_and_stable_locations():
    lines = [{"id": "line-1", "text": "开场", "start_seconds": 12, "seekable": True},
             {"id": "line-2", "text": "尾部", "start_seconds": 50, "seekable": True}]
    evidence = retrieve_evidence(lines, "尾部说了什么？")
    assert evidence["mode"] == "full"
    assert "尾部" in evidence["passages"][0]["text"]
    assert evidence["passages"][0]["label"] == "00:12"
    assert evidence["passages"][0]["line_id"] == "line-1"


def test_unsegmented_long_line_cannot_overflow_context_or_duplicate_citations():
    evidence = retrieve_evidence([{"text": "蒸馏规则需要核对原始材料。" * 10000}], "蒸馏规则是什么？", max_chars=5000)
    assert evidence["context_chars"] <= 5000
    ids = [item["id"] for item in evidence["passages"]]
    assert len(ids) == len(set(ids))


def _service(sessions):
    service = StudyService.__new__(StudyService)
    service.llm_config = {}
    service.get_session = Mock(side_effect=lambda token: sessions.get(token))
    service.llm_answerer = Mock(return_value="资料一建议缓存，资料二反对缓存 [S1:P1] [S2:P1]。")
    return service


def test_comparison_keeps_opposing_views_and_real_source_identifiers():
    def session(title, text):
        return {"metadata": {"title": title}, "transcript": {"lines": [{"id": "line-1", "text": text}]}}
    service = _service({"first": session("Author A", "建议缓存以加快读取。"),
                        "second": session("Author B", "反对缓存，因为容易读取旧结果。")})
    result = service.compare_sources(["first", "second"], "缓存的优缺点有什么不同？")
    prompt = service.llm_answerer.call_args.kwargs["prompt"]
    assert "建议缓存" in prompt and "反对缓存" in prompt
    assert "[S1:P1" in prompt and "[S2:P1" in prompt
    assert [source["title"] for source in result["sources"]] == ["Author A", "Author B"]
    assert result["sources"][1]["passages"][0]["text"].startswith("反对缓存")


def test_long_question_miss_returns_explanation_without_model_cost():
    service = _service({"long": {"transcript": {"lines": _long_lines()}, "ai": {"overview": "课程概览"}}})
    result = service.ask_ai("long", "猕猴桃种植需要哪些肥料？")
    assert "未在" in result["answer"]
    service.llm_answerer.assert_not_called()


def test_all_comparison_sources_miss_without_model_cost():
    sessions = {token: {"transcript": {"lines": _long_lines()}} for token in ("first", "second")}
    service = _service(sessions)
    result = service.compare_sources(["first", "second"], "猕猴桃种植需要哪些肥料？")
    assert result["coverage"]["matched_sources"] == 0
    service.llm_answerer.assert_not_called()


def test_invented_source_reference_is_rejected_before_delivery():
    sessions = {token: {"transcript": {"lines": [{"text": "原文依据。"}]}} for token in ("first", "second")}
    service = _service(sessions)
    service.llm_answerer.return_value = "结论来自不存在的资料 [S9:P88]"
    with pytest.raises(ValueError, match="引用"):
        service.compare_sources(["first", "second"], "对照原文")


def test_overview_under_comparison_budget_still_reaches_end():
    lines = _long_lines()
    lines[-1]["text"] = "课程结束的最后结论。"
    evidence = retrieve_evidence(lines, "视频讲了什么？", max_chars=8500)
    assert evidence["mode"] == "sampled"
    assert "最后结论" in "\n".join(item["text"] for item in evidence["passages"])


def test_retrieved_citations_are_sequential_but_preserve_original_location():
    evidence = retrieve_evidence(_long_lines(), "混合检索如何召回与重排？", max_chars=3500)
    passages = evidence["passages"]
    assert passages
    assert [item["id"] for item in passages] == [f"P{index}" for index in range(1, len(passages) + 1)]
    tail = next(item for item in passages if "最后一章" in item["text"])
    assert tail["original_id"] != tail["id"]
    assert int(tail["line_id"].split("-")[1]) > 700
    assert tail["start_seconds"] > 20000


def test_comparison_prompt_examples_only_reference_current_passages():
    sessions = {token: {"transcript": {"lines": _long_lines()}} for token in ("first", "second")}
    service = _service(sessions)
    result = service.compare_sources(["first", "second"], "混合检索如何召回与重排？")
    prompt = service.llm_answerer.call_args.kwargs["prompt"]
    assert "[S1:P1]" in prompt and "[S2:P1]" in prompt
    examples = prompt.split("示例：", 1)[1].split("。", 1)[0]
    assert "[S1:P1]" in examples and "[S1:P2]" in examples
    assert "[S1:P3]" not in examples
    assert result["sources"][0]["passages"][0]["original_id"] != "P1"


def test_invalid_citation_log_contains_only_identifiers_and_allowed_count(monkeypatch):
    from video_transcript_api.study import service as module

    logger = Mock()
    monkeypatch.setattr(module, "logger", logger)
    with pytest.raises(ValueError, match="引用"):
        module._check_citations("PRIVATE_ANSWER_AND_SOURCE [S9:P88]", {"S1:P1"})
    rendered = str(logger.warning.call_args)
    assert "S9:P88" in rendered
    assert "allowed_count" in rendered
    assert "PRIVATE_ANSWER_AND_SOURCE" not in rendered


def test_interactive_prompts_prefer_focused_final_answers_but_respect_explicit_detail():
    sessions = {token: {"transcript": {"lines": [{"text": "缓存能加速重复读取，但需要处理过期。"}]}}
                for token in ("first", "second")}
    service = _service(sessions)
    question = "请详细解释缓存的适用条件，并完整展开局限。"
    service.llm_answerer.return_value = "依据原文 [P1]"
    service.ask_ai("first", question)
    single_prompt = service.llm_answerer.call_args.kwargs["prompt"]
    service.llm_answerer.return_value = "对照原文 [S1:P1] [S2:P1]"
    service.compare_sources(["first", "second"], question)
    comparison_prompt = service.llm_answerer.call_args.kwargs["prompt"]
    for prompt in (single_prompt, comparison_prompt):
        assert question in prompt
        assert "最多 3 个" in prompt
        assert "600–1000 字" in prompt
        assert "不受上述默认篇幅限制" in prompt
        assert "引用前核对资料归属" in prompt
        assert "整理后的最终版" in prompt
    assert "主题不同时" in comparison_prompt
    assert "不硬凑对立观点" in comparison_prompt


@pytest.mark.parametrize("config, expected_model, expected_reasoning", [
    ({}, "deepseek-v4-pro", "medium"),
    ({"summary_model": "deepseek-v4-flash", "study_chat_model": None,
      "study_chat_reasoning_effort": None}, "deepseek-v4-flash", "medium"),
    ({"summary_model": "deepseek-v4-flash", "study_chat_model": "explicit-chat",
      "study_chat_reasoning_effort": "high"}, "explicit-chat", "high"),
    ({"summary_model": "deepseek-v4-flash", "study_chat_model": "",
      "study_chat_reasoning_effort": "disabled"}, "deepseek-v4-flash", "disabled"),
])
def test_interactive_model_priority_and_actual_response_fields(config, expected_model, expected_reasoning):
    sessions = {token: {"transcript": {"lines": [{"text": "可核对的原文。"}]}}
                for token in ("first", "second")}
    service = _service(sessions)
    service.llm_config = config
    service.llm_answerer.return_value = "依据原文 [P1]"
    single = service.ask_ai("first", "解释原文")
    assert single["model"] == expected_model
    assert single["reasoning_effort"] == expected_reasoning
    assert service.llm_answerer.call_args.kwargs["model"] == expected_model
    assert service.llm_answerer.call_args.kwargs["reasoning_effort"] == expected_reasoning

    service.llm_answerer.return_value = "对照原文 [S1:P1] [S2:P1]"
    comparison = service.compare_sources(["first", "second"], "对照原文")
    assert comparison["model"] == expected_model
    assert comparison["reasoning_effort"] == expected_reasoning
    assert service.llm_answerer.call_args.kwargs["model"] == expected_model
    assert service.llm_answerer.call_args.kwargs["reasoning_effort"] == expected_reasoning
