import copy
import hashlib
import json
import logging

import pytest

from video_transcript_api.llm import StructuredResult


class FakeStudyService:
    def __init__(self, session):
        self.session = session

    def get_session(self, view_token):
        if view_token != "view-1":
            return None
        return self.session


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, StructuredResult):
            return response
        return StructuredResult(success=True, data=response)


def _session():
    return {
        "state": "ready",
        "metadata": {"view_token": "view-1", "title": "从 LLM 到 Agent Skill"},
        "transcript": {
            "lines": [
                {
                    "id": "line-1",
                    "text": "LLM 提供推理和语言能力。",
                    "seekable": True,
                    "start_seconds": 2.0,
                },
                {
                    "id": "line-2",
                    "text": "工具把模型连接到外部世界。",
                    "seekable": False,
                    "start_seconds": None,
                },
                {
                    "id": "line-3",
                    "text": "Skill 把流程固化成可复用能力。",
                    "seekable": True,
                    "start_seconds": 15.5,
                },
            ]
        },
        "ai": {
            "overview": (
                "## 模型层\nLLM 提供推理和语言能力。\n\n"
                "## 工具层\n工具把模型连接到外部世界。\n\n"
                "## Skill 层\nSkill 把流程固化成可复用能力。"
            )
        },
    }


def _ref_id(line_id="line-1"):
    return f"study:view-1:line:{line_id}"


def _section_ref(index, owner_type="study", owner_id="view-1"):
    return f"{owner_type}:{owner_id}:summary:section:section-{index:02d}"


def _source_ref(ref_id=None):
    ref_id = ref_id or _ref_id()
    return {
        "id": ref_id,
        "owner_type": "study",
        "owner_id": "view-1",
        "excerpt": "LLM 提供推理和语言能力。",
        "line_id": "line-1",
        "paragraph_index": 0,
        "start_seconds": 2.0,
        "end_seconds": 15.5,
    }


def _hero(block_id="hero-1", refs=None, **overrides):
    block = {
        "id": block_id,
        "type": "hero_summary",
        "title": "核心结论",
        "source_ref_ids": refs or [_section_ref(1), _section_ref(2)],
        "headline": "模型走向可执行能力",
        "summary": "模型负责推理，工具负责行动，Skill 负责复用。",
        "points": ["模型推理", "工具执行", "Skill 复用"],
    }
    block.update(overrides)
    return block


def _review(refs=None):
    return {
        "id": "review-1",
        "type": "review_questions",
        "title": "主动回忆",
        "source_ref_ids": refs or [_section_ref(3)],
        "questions": [
            {"question": "LLM 的核心作用是什么？", "answer": "提供推理和语言能力。"},
            {"question": "Skill 为什么有价值？", "answer": "它把流程固化成可复用能力。"},
        ],
    }


def _document(document_type="overview", pages=None, **overrides):
    payload = {
        "version": 1,
        "document_type": document_type,
        "title": "从 LLM 到 Agent Skill",
        "subtitle": "理解模型、工具与 Skill 的关系",
        "recommended_style": "study-notes",
        "selected_diagram_type": "concept_chain",
        "diagram_recommendations": [
            {
                "diagram_type": "concept_chain",
                "label": "概念链",
                "rationale": "内容呈现清晰的能力演进关系。",
                "score": 0.9,
            }
        ],
        "pages": pages
        or [
            {
                "id": "page-1",
                "title": "核心主线",
                "learning_goal": "理解三个核心概念的关系",
                "blocks": [_hero()],
            }
        ],
        "source_refs": [_source_ref()],
    }
    payload.update(overrides)
    return payload


def _full_note_document(*, title="从 LLM 到 Agent Skill"):
    pages = []
    for index, page_title in enumerate(["模型层", "工具层", "Skill 层"], start=1):
        refs = [_section_ref(index)]
        page = {
            "id": f"section-{index:02d}",
            "title": page_title,
            "learning_goal": f"理解{page_title}",
            "blocks": [_hero(f"hero-{index}", refs=refs)],
        }
        if index == 3:
            page["blocks"].append(_review(refs=refs))
        pages.append(page)
    return _document(document_type="full_note", pages=pages, title=title)


def _service(tmp_path, llm, session=None, llm_config=None):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository
    from video_transcript_api.visual_learning.service import VisualLearningService
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    study = FakeStudyService(session or _session())
    resolver = StudySourceResolver(study)
    repository = VisualLearningRepository(str(tmp_path / "visual.db"))
    service = VisualLearningService(
        repository=repository,
        source_resolver=resolver,
        llm_callable=llm,
        llm_config={
            "visual_learning_model": "visual-test-model",
            "visual_learning_reasoning_effort": "high",
            **(llm_config or {}),
        },
    )
    return service, repository, study


def test_visual_prompt_requires_continuous_transitions(tmp_path):
    from video_transcript_api.visual_learning.prompts import build_visual_prompt

    service, _, _ = _service(tmp_path, FakeLLM())
    source = service.source_resolver.resolve("view-1")

    prompt = build_visual_prompt(source, "diagram")

    assert "前 N-1 页必须填写 transition" in prompt
    assert "能力缺口" in prompt
    assert "最后一页" in prompt


def test_full_note_prompt_contains_complete_sections_and_allowed_refs(tmp_path):
    from video_transcript_api.visual_learning.prompts import build_visual_prompt

    service, _, _ = _service(tmp_path, FakeLLM())
    source = service.source_resolver.resolve("view-1")
    sections = [
        {
            "id": section.id,
            "title": section.title,
            "original_markdown": section.markdown,
            "allowed_source_ref_ids": list(section.source_ref_ids),
        }
        for section in source.interpretation_sections
    ]

    prompt = build_visual_prompt(
        source,
        "full_note",
        interpretation_sections=sections,
    )

    for section in sections:
        assert section["original_markdown"] in prompt
        assert section["id"] in prompt
        for ref_id in section["allowed_source_ref_ids"]:
            assert ref_id in prompt
    assert "每个 section 恰好生成一页" in prompt
    assert "不要重写一份平行解读" in prompt


@pytest.mark.parametrize("document_type", ["overview", "full_note"])
def test_prepare_requires_interpretation_but_diagram_remains_available(
    tmp_path, document_type
):
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    session = _session()
    session["ai"]["overview"] = "一句无法拆成三节的总结。"
    service, repository, _ = _service(tmp_path, FakeLLM(), session=session)

    with pytest.raises(VisualLearningSourceNotReady):
        service.prepare_study_generation("view-1", document_type)

    diagram = service.prepare_study_generation("view-1", "diagram")
    assert diagram["status"] == "pending"
    assert repository.list_documents("study", "view-1", document_type) == []


def test_study_state_reports_missing_interpretation_as_source_not_ready(tmp_path):
    session = _session()
    session["ai"]["overview"] = "一句无法拆成三节的总结。"
    service, _, _ = _service(tmp_path, FakeLLM(), session=session)

    state = service.get_study_state("view-1", "overview")

    assert state["phase"] == "failed"
    assert state["interpretation_sections"] == []
    assert state["interpretation_available"] is False
    assert state["document"] is None


def test_request_key_only_invalidates_diagram_pipeline(tmp_path):
    service, _, _ = _service(tmp_path, FakeLLM())
    source = service.source_resolver.resolve("view-1")

    overview_key = service._request_key(
        source,
        "overview",
        "study-notes",
        "auto",
        "outline-test-model",
        "high",
        "render-test-model",
        "disabled",
    )
    diagram_key = service._request_key(
        source,
        "diagram",
        "study-notes",
        "auto",
        "outline-test-model",
        "high",
        "render-test-model",
        "disabled",
    )
    expected_overview = hashlib.sha256(
        json.dumps(
            {
                "pipeline_version": 4,
                "owner_type": source.owner_type,
                "owner_id": source.owner_id,
                "document_type": "overview",
                "source_hash": source.source_hash,
                "style": "study-notes",
                "diagram_type": "auto",
                "analysis_mode": "legacy",
                "outline_model": "outline-test-model",
                "outline_reasoning_effort": "high",
                "render_model": "render-test-model",
                "render_reasoning_effort": "disabled",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    expected_diagram = hashlib.sha256(
        json.dumps(
            {
                "pipeline_version": 4,
                "owner_type": source.owner_type,
                "owner_id": source.owner_id,
                "document_type": "diagram",
                "source_hash": source.source_hash,
                "style": "study-notes",
                "diagram_type": "auto",
                "analysis_mode": "legacy",
                "outline_model": "outline-test-model",
                "outline_reasoning_effort": "high",
                "render_model": "render-test-model",
                "render_reasoning_effort": "disabled",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    assert overview_key == expected_overview
    assert diagram_key == expected_diagram


def test_resolver_preserves_transcript_line_refs():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    source = StudySourceResolver(FakeStudyService(_session())).resolve("view-1")

    assert [ref.id for ref in source.source_refs if ":line:" in ref.id] == [
        _ref_id("line-1"),
        _ref_id("line-2"),
        _ref_id("line-3"),
    ]
    assert source.source_refs[0].start_seconds == 2.0
    assert source.source_refs[0].end_seconds == 15.5
    assert source.source_refs[1].paragraph_index == 1
    assert source.source_refs[1].start_seconds is None
    assert source.source_refs[2].end_seconds is None
    assert f"[{_ref_id()}] LLM 提供推理和语言能力。" in source.content


def test_study_source_exposes_existing_interpretation_sections():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    session = _session()
    session["ai"]["overview"] = (
        "## 模型层\n模型负责理解与推理。\n\n"
        "## 工具层\n工具负责连接外部世界。\n\n"
        "## Skill 层\nSkill 负责固化可复用流程。"
    )

    source = StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert [section.id for section in source.interpretation_sections] == [
        "section-01",
        "section-02",
        "section-03",
    ]
    section = source.interpretation_sections[0]
    section_ref_id = section.source_ref_ids[0]
    assert section_ref_id == "study:view-1:summary:section:section-01"
    assert section_ref_id in [ref.id for ref in source.source_refs]
    assert source.ref_texts[section_ref_id] == section.markdown


def test_study_source_sections_and_hash_use_full_untruncated_overview():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    prefix = "引言" + ("甲" * 12000)
    session = _session()
    session["ai"]["overview"] = (
        f"{prefix}\n\n## 第二节\n乙段。\n\n## 第三节\n全文末尾标记-A"
    )
    resolver = StudySourceResolver(FakeStudyService(session))

    first = resolver.resolve("view-1")
    session["ai"]["overview"] = session["ai"]["overview"].replace(
        "全文末尾标记-A", "全文末尾标记-B"
    )
    second = resolver.resolve("view-1")

    assert first.summary == prefix[:12000]
    assert "全文末尾标记-A" in first.interpretation_sections[-1].markdown
    assert first.source_hash != second.source_hash


def test_study_source_normalizes_wrapped_overview_before_sections_and_hashing():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    plain = (
        "## 模型层\n模型负责理解与推理。\n\n"
        "## 工具层\n工具负责连接外部世界。\n\n"
        "## Skill 层\nSkill 负责固化流程。"
    )
    plain_session = _session()
    plain_session["ai"]["overview"] = plain
    wrapped_session = _session()
    wrapped_session["ai"]["overview"] = (
        "---\ntitle: 从 LLM 到 Agent Skill\nsource_type: video_course\n---\n"
        f"{plain}"
    )

    plain_source = StudySourceResolver(FakeStudyService(plain_session)).resolve("view-1")
    wrapped_source = StudySourceResolver(FakeStudyService(wrapped_session)).resolve("view-1")

    assert wrapped_source.summary == plain_source.summary == plain
    assert wrapped_source.interpretation_sections == plain_source.interpretation_sections
    assert wrapped_source.source_hash == plain_source.source_hash


@pytest.mark.parametrize("overview", ["一句很短的总结。", ""])
def test_study_source_keeps_transcript_when_interpretation_is_not_ready(overview):
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    session = _session()
    session["ai"] = {"overview": overview}
    if not overview:
        session["source"] = {"kind": "document", "filename": "guide.pdf"}
        session["analysis"] = {"mode": "document_fast", "visual_ready": True}

    source = StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert source.interpretation_sections == ()
    assert [ref.id for ref in source.source_refs] == [
        _ref_id("line-1"),
        _ref_id("line-2"),
        _ref_id("line-3"),
    ]
    assert "LLM 提供推理和语言能力" in source.content


def test_resolver_chunks_long_single_paragraph_without_losing_content(tmp_path):
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver
    from video_transcript_api.study.document_quality import assess_document_text

    clean_content = "超长正文内容" * 6000
    content = clean_content[:12000] + "\x00" + clean_content[12000:24000] + "\x08" + clean_content[24000:]
    assert assess_document_text(content).mode == "fast"
    session = _session()
    session["source"] = {
        "kind": "document",
        "filename": "long.txt",
        "media_type": "text/plain",
    }
    session["transcript"]["lines"] = [
        {
            "id": "long-line",
            "text": content,
            "seekable": False,
            "start_seconds": None,
        }
    ]
    resolver = StudySourceResolver(FakeStudyService(session))

    source = resolver.resolve("view-1")

    assert source.total_content_chars == len(clean_content)
    assert len(source.source_refs) > 1
    assert all(len(text) <= 4000 for text in source.ref_texts.values())
    assert "".join(
        source.ref_texts[ref.id]
        for ref in source.source_refs
        if ":line:" in ref.id
    ) == clean_content
    service, _, _ = _service(tmp_path, FakeLLM())
    assert service._is_long_diagram(source, "diagram") is True


def test_resolver_creates_traceable_ref_for_summary_only_source():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    session = _session()
    session["transcript"]["lines"] = []
    source = StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert source.source_refs[0].id == "study:view-1:summary"
    assert "[study:view-1:summary]" in source.content
    assert source.source_refs[0].excerpt.startswith("## 模型层")
    assert source.source_refs[0].paragraph_index is None


def test_resolver_waits_for_full_summary_even_when_transcript_exists():
    from video_transcript_api.visual_learning.source_resolver import (
        StudySourceResolver,
        VisualLearningSourceNotReady,
    )

    session = _session()
    session["state"] = "generating_ai"
    session["ai"]["overview"] = ""
    session["progress"] = {
        "stage": "calibrating",
        "stage_label": "正在校对和总结",
        "percent": 80,
    }

    with pytest.raises(VisualLearningSourceNotReady) as caught:
        StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert caught.value.terminal is False
    assert caught.value.source_progress["stage"] == "waiting_analysis"
    assert caught.value.source_progress["percent"] == 80


def test_resolver_exposes_document_quality_as_assessment_stage():
    from video_transcript_api.visual_learning.source_resolver import (
        StudySourceResolver,
        VisualLearningSourceNotReady,
    )

    session = _session()
    session["state"] = "processing"
    session["ai"]["overview"] = ""
    session["progress"] = {
        "stage": "document_quality",
        "stage_label": "文档质量检查完成",
        "percent": 0,
    }

    with pytest.raises(VisualLearningSourceNotReady) as caught:
        StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert caught.value.source_progress["stage"] == "assessing_quality"
    assert caught.value.source_progress["raw_stage"] == "document_quality"


def test_resolver_accepts_fast_document_without_summary():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    session = _session()
    session["source"] = {"kind": "document", "filename": "guide.pdf"}
    session["analysis"] = {
        "mode": "document_fast",
        "visual_ready": True,
        "quality": {"mode": "fast", "reasons": [], "metrics": {}},
    }
    session["ai"] = {"overview": "", "summary_missing": True}

    source = StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert source.summary == ""
    assert source.source_kind == "document"
    assert source.source_progress["stage"] == "ready_for_generation"
    assert all(ref.id != "study:view-1:summary" for ref in source.source_refs)


@pytest.mark.parametrize("kind", ["text", "video", "unknown"])
def test_resolver_does_not_accept_fast_flag_for_non_document(kind):
    from video_transcript_api.visual_learning.source_resolver import (
        StudySourceResolver,
        VisualLearningSourceNotReady,
    )

    session = _session()
    session["source"] = {"kind": kind, "filename": "source"}
    session["analysis"] = {"mode": "document_fast", "visual_ready": True}
    session["ai"] = {"overview": "", "summary_missing": True}

    with pytest.raises(VisualLearningSourceNotReady):
        StudySourceResolver(FakeStudyService(session)).resolve("view-1")


def test_resolver_marks_terminal_missing_summary_as_not_reusable():
    from video_transcript_api.visual_learning.source_resolver import (
        StudySourceResolver,
        VisualLearningSourceNotReady,
    )

    session = _session()
    session["ai"] = {"overview": "", "summary_missing": True}

    with pytest.raises(VisualLearningSourceNotReady) as caught:
        StudySourceResolver(FakeStudyService(session)).resolve("view-1")

    assert caught.value.terminal is True
    assert caught.value.source_progress["stage"] == "failed"


def test_generate_overview_uses_summary_and_transcript(tmp_path):
    llm = FakeLLM(_document())
    service, repository, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="overview")

    assert result["status"] == "success"
    assert result["document_json"]["title"] == "从 LLM 到 Agent Skill"
    assert "LLM 提供推理和语言能力" in llm.calls[0]["prompt"]
    assert f"[{_ref_id()}] LLM 提供推理" in llm.calls[0]["prompt"]
    assert llm.calls[0]["task_type"] == "visual_overview"
    assert llm.calls[0]["response_schema"]["title"] == "VisualDocument"
    assert repository.get_latest("study", "view-1", "overview", True)


def test_overview_is_one_page_with_at_most_five_blocks(tmp_path):
    blocks = [_hero(f"hero-{index}") for index in range(6)]
    payload = _document()
    payload["pages"][0]["blocks"] = blocks
    llm = FakeLLM(payload)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="overview")

    assert result["status"] == "success"
    assert len(result["document_json"]["pages"]) == 1
    assert len(result["document_json"]["pages"][0]["blocks"]) == 5


def test_overview_keeps_explicit_macro_page_when_model_adds_section_pages(tmp_path):
    payload = _document()
    payload["pages"][0]["id"] = "overview"
    payload["pages"].append(
        {
            "id": "section-01",
            "title": "模型层",
            "learning_goal": "理解模型层",
            "blocks": [_hero("section-hero", refs=[_section_ref(1)])],
        }
    )
    llm = FakeLLM(payload)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="overview")

    assert result["status"] == "success"
    assert [page["id"] for page in result["document_json"]["pages"]] == [
        "overview"
    ]


def test_initial_overview_falls_back_when_model_returns_non_macro_pages(tmp_path):
    invalid = _document()
    invalid["pages"].append(copy.deepcopy(invalid["pages"][0]))
    llm = FakeLLM(invalid)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="overview")

    assert result["status"] == "success"
    assert result["document_json"]["pages"][0]["id"] == "overview"
    assert result["document_json"]["selected_diagram_type"] == "concept_chain"


def test_generate_full_note_limits_pages_to_three_through_eight(tmp_path):
    llm = FakeLLM(_full_note_document())
    service, _, _ = _service(tmp_path, llm)
    source = service.source_resolver.resolve("view-1")

    result = service.generate_study("view-1", document_type="full_note")

    assert result["status"] == "success"
    assert [call["task_type"] for call in llm.calls] == ["visual_full_note"]
    assert len(result["document_json"]["pages"]) == 3
    assert result["document_json"]["pages"][-1]["blocks"][-1]["type"] == "review_questions"
    allowed_refs = {
        ref_id
        for section in source.interpretation_sections
        for ref_id in section.source_ref_ids
    }
    assert {
        ref["id"] for ref in result["document_json"]["source_refs"]
    }.issubset(allowed_refs)


def test_initial_full_note_retries_once_when_a_page_has_only_review_questions(
    tmp_path,
):
    invalid = _full_note_document(title="首次结构错误")
    invalid["pages"][0]["blocks"] = [_review(refs=[_section_ref(1)])]
    valid = _full_note_document(title="纠错后有效")
    llm = FakeLLM(invalid, valid)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="full_note")

    assert result["status"] == "success"
    assert result["document_json"]["title"] == "纠错后有效"
    assert len(llm.calls) == 2
    assert "full_note page requires a visual block" in llm.calls[1]["prompt"]


def test_initial_full_note_retries_once_when_final_review_is_missing(tmp_path):
    invalid = _full_note_document(title="缺少复习题")
    invalid["pages"][-1]["blocks"] = invalid["pages"][-1]["blocks"][:-1]
    valid = _full_note_document(title="补全复习题")
    llm = FakeLLM(invalid, valid)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="full_note")

    assert result["status"] == "success"
    assert result["document_json"]["title"] == "补全复习题"
    assert len(llm.calls) == 2
    assert "review_questions" in llm.calls[1]["prompt"]


def test_initial_full_note_retries_once_when_page_ids_do_not_align(tmp_path):
    invalid = _full_note_document(title="页顺序错误")
    invalid["pages"] = list(reversed(invalid["pages"]))
    valid = _full_note_document(title="页顺序已纠正")
    llm = FakeLLM(invalid, valid)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="full_note")

    assert result["status"] == "success"
    assert result["document_json"]["title"] == "页顺序已纠正"
    assert len(llm.calls) == 2
    assert "pages do not match" in llm.calls[1]["prompt"]


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda payload: payload["pages"].__setitem__(
                slice(None), list(reversed(payload["pages"]))
            ),
            "full_note pages do not match interpretation sections",
        ),
        (
            lambda payload: payload["pages"][0].__setitem__(
                "blocks", [_review(refs=[_section_ref(1)])]
            ),
            "full_note page requires a visual block",
        ),
        (
            lambda payload: payload["pages"][-1]["blocks"][-1].__setitem__(
                "source_ref_ids", [_section_ref(1)]
            ),
            "full_note block references outside its section",
        ),
    ],
)
def test_invalid_full_note_alignment_preserves_previous_success(
    tmp_path, mutate, expected_error
):
    valid = _full_note_document(title="有效版本")
    invalid = _full_note_document(title="无效版本")
    mutate(invalid)
    llm = FakeLLM(valid, invalid)
    service, repository, _ = _service(tmp_path, llm)

    first = service.generate_study("view-1", "full_note")
    second = service.generate_study("view-1", "full_note", force=True)

    assert first["status"] == "success"
    assert second["status"] == "failed"
    assert second["error_message"] == expected_error
    assert repository.get_latest(
        "study", "view-1", "full_note", successful_only=True
    )["document_json"]["title"] == "有效版本"


def test_study_overview_requires_two_distinct_section_refs(tmp_path):
    invalid = _document(title="覆盖不足")
    invalid["pages"][0]["blocks"] = [_hero(refs=[_section_ref(1)])]
    llm = FakeLLM(invalid, invalid)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", "overview")

    assert result["status"] == "success"
    assert result["document_json"]["selected_diagram_type"] == "concept_chain"
    assert len(result["document_json"]["pages"][0]["blocks"][0]["items"]) == 3


def test_initial_overview_falls_back_when_source_refs_are_invalid(tmp_path):
    invalid = _document(title="引用无效")
    invalid["pages"][0]["blocks"] = [_hero(refs=["invalid-ref"])]
    valid = _document(title="引用已纠正")
    llm = FakeLLM(invalid, valid)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", "overview")

    assert result["status"] == "success"
    assert result["document_json"]["selected_diagram_type"] == "concept_chain"
    assert len(llm.calls) == 1


def test_study_overview_counts_original_evidence_toward_section_coverage(tmp_path):
    llm = FakeLLM(_document())
    service, _, _ = _service(tmp_path, llm)
    source = service.source_resolver.resolve("view-1")
    original_refs = [
        next(ref_id for ref_id in section.source_ref_ids if ":line:" in ref_id)
        for section in source.interpretation_sections[:2]
    ]
    llm.responses[0]["pages"][0]["blocks"] = [_hero(refs=original_refs)]

    result = service.generate_study("view-1", "overview")

    assert result["status"] == "success"


def test_generate_diagram_returns_ranked_recommendations(tmp_path):
    recommendations = [
        {"diagram_type": "timeline", "label": "时间线", "rationale": "有阶段", "score": 0.4},
        {"diagram_type": "comparison", "label": "对比图", "rationale": "有差异", "score": 0.7},
        {"diagram_type": "mind_map", "label": "思维导图", "rationale": "有分支", "score": 0.6},
        {"diagram_type": "process_flow", "label": "流程图", "rationale": "有步骤", "score": 0.95},
    ]
    llm = FakeLLM(
        _document(
            document_type="diagram",
            selected_diagram_type=None,
            diagram_recommendations=recommendations,
        )
    )
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", document_type="diagram")

    assert [item["diagram_type"] for item in result["document_json"]["diagram_recommendations"]] == [
        "process_flow",
        "comparison",
        "mind_map",
    ]
    assert result["document_json"]["selected_diagram_type"] == "process_flow"


def test_invalid_source_refs_fail_without_overwriting_previous_success(tmp_path):
    valid = _document(title="有效版本")
    invalid = _document(title="无效版本")
    invalid["pages"][0]["blocks"] = [_hero(refs=["invented-ref"])]
    llm = FakeLLM(valid, invalid)
    service, repository, _ = _service(tmp_path, llm)

    first = service.generate_study("view-1", "overview")
    second = service.generate_study("view-1", "overview", force=True)

    assert first["status"] == "success"
    assert second["status"] == "failed"
    assert repository.get_latest(
        "study", "view-1", "overview", successful_only=True
    )["document_json"]["title"] == "有效版本"


def test_mixed_source_refs_remove_invalid_ids_and_keep_valid_ids(tmp_path):
    payload = _document()
    payload["pages"][0]["blocks"] = [
        _hero(refs=[_section_ref(1), _section_ref(2), "invented-ref"])
    ]
    llm = FakeLLM(payload)
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", "overview")

    refs = result["document_json"]["pages"][0]["blocks"][0]["source_ref_ids"]
    assert refs == [_section_ref(1), _section_ref(2)]


def test_same_source_and_options_reuse_document(tmp_path):
    llm = FakeLLM(_document())
    service, _, _ = _service(tmp_path, llm)

    first = service.generate_study("view-1", "overview")
    second = service.generate_study("view-1", "overview")

    assert first["id"] == second["id"]
    assert len(llm.calls) == 1


def test_prepare_generation_creates_pending_without_calling_llm(tmp_path):
    llm = FakeLLM(_document())
    service, _, _ = _service(tmp_path, llm)

    pending = service.prepare_study_generation("view-1", "overview")

    assert pending["status"] == "pending"
    assert llm.calls == []
    generated = service.generate_study("view-1", "overview")
    assert generated["id"] == pending["id"]
    assert generated["status"] == "success"


def test_generate_prepared_force_version_claims_exact_document(tmp_path):
    llm = FakeLLM(_document(title="第一版"), _document(title="第二版"))
    service, repository, _ = _service(tmp_path, llm)
    service.generate_study("view-1", "overview")

    pending = service.prepare_study_generation(
        "view-1", "overview", force=True
    )
    generated = service.generate_prepared_study(
        pending["id"], "view-1", "overview", "study-notes", "auto"
    )

    assert generated["id"] == pending["id"]
    assert generated["status"] == "success"
    assert generated["document_json"]["title"] == "第二版"
    assert len(repository.list_documents("study", "view-1", "overview")) == 2


def test_generate_prepared_rejects_different_diagram_type(tmp_path):
    from video_transcript_api.visual_learning.service import (
        VisualLearningGenerationError,
    )

    service, _, _ = _service(tmp_path, FakeLLM())
    pending = service.prepare_study_generation(
        "view-1",
        "diagram",
        diagram_type="auto",
    )

    with pytest.raises(
        VisualLearningGenerationError,
        match="prepared document options mismatch",
    ):
        service.generate_prepared_study(
            pending["id"],
            "view-1",
            "diagram",
            "study-notes",
            "process_flow",
        )


@pytest.mark.parametrize(
    "nonce_suffix",
    ["garbage", "a" * 31, f"{'a' * 32}:extra"],
)
def test_generate_prepared_rejects_malformed_force_nonce(tmp_path, nonce_suffix):
    from video_transcript_api.visual_learning.service import (
        VisualLearningGenerationError,
    )

    service, repository, _ = _service(tmp_path, FakeLLM())
    pending = service.prepare_study_generation("view-1", "overview")
    connection = repository._get_connection()
    connection.execute(
        "UPDATE visual_documents SET request_key = ? WHERE id = ?",
        (f"{pending['request_key']}:{nonce_suffix}", pending["id"]),
    )
    connection.commit()

    with pytest.raises(
        VisualLearningGenerationError,
        match="prepared document options mismatch",
    ):
        service.generate_prepared_study(
            pending["id"], "view-1", "overview"
        )


@pytest.mark.parametrize(
    "config_update",
    [
        {"visual_learning_model": "changed-model"},
        {"visual_learning_reasoning_effort": "disabled"},
    ],
)
def test_generate_prepared_rejects_model_or_reasoning_change(
    tmp_path,
    config_update,
):
    from video_transcript_api.visual_learning.service import (
        VisualLearningGenerationError,
    )

    service, _, _ = _service(tmp_path, FakeLLM())
    pending = service.prepare_study_generation("view-1", "overview")
    service.llm_config.update(config_update)

    with pytest.raises(
        VisualLearningGenerationError,
        match="prepared document options mismatch",
    ):
        service.generate_prepared_study(
            pending["id"], "view-1", "overview"
        )


def test_document_state_returns_requested_version(tmp_path):
    llm = FakeLLM(_document())
    service, _, _ = _service(tmp_path, llm)
    source = service.source_resolver.resolve("view-1")
    generated = service.generate_study("view-1", "overview")

    state = service.get_document_state(generated["id"])

    assert state["document"]["id"] == generated["id"]
    assert state["latest_attempt"]["id"] == generated["id"]
    assert state["stale"] is False
    assert state["interpretation_available"] is True
    assert state["interpretation_sections"] == [
        {
            "id": section.id,
            "title": section.title,
            "markdown": section.markdown,
            "source_ref_ids": list(section.source_ref_ids),
        }
        for section in source.interpretation_sections
    ]


def test_document_state_survives_removed_study_source(tmp_path):
    llm = FakeLLM(_document())
    service, _, study = _service(tmp_path, llm)
    generated = service.generate_study("view-1", "overview")
    study.session = None

    state = service.get_document_state(generated["id"])

    assert state["document"]["id"] == generated["id"]
    assert state["document"]["document_json"]["title"] == "从 LLM 到 Agent Skill"
    assert state["stale"] is True
    assert state["interpretation_sections"] == []
    assert state["interpretation_available"] is False


def test_provider_error_is_not_persisted_verbatim(tmp_path):
    secret_error = "provider request failed with secret-key-value"
    llm = FakeLLM(StructuredResult(success=False, error=secret_error))
    service, _, _ = _service(tmp_path, llm)

    result = service.generate_study("view-1", "overview")

    assert result["status"] == "failed"
    assert result["error_message"] == "structured LLM generation failed"
    assert "secret-key-value" not in result["error_message"]


def test_normalizer_clamps_generated_text_and_arrays(caplog):
    from video_transcript_api.visual_learning.service import normalize_visual_document

    payload = _document()
    payload["pages"][0]["blocks"] = [
        _hero(
            headline="标" * 50,
            summary="摘要" * 130,
            points=[f"知识点 {index}" for index in range(6)],
        )
    ]

    with caplog.at_level(logging.INFO):
        normalized = normalize_visual_document(payload)

    block = normalized["pages"][0]["blocks"][0]
    assert len(block["headline"]) == 40
    assert len(block["summary"]) == 240
    assert len(block["points"]) == 5
    assert "pages[0].blocks[0].headline" in caplog.text
    assert "50 -> 40" in caplog.text
    assert "标" * 20 not in caplog.text


def test_changed_source_hash_marks_existing_document_stale(tmp_path):
    llm = FakeLLM(_document())
    service, _, study = _service(tmp_path, llm)
    service.generate_study("view-1", "overview")

    study.session["transcript"]["lines"][0]["text"] = "原文已经发生变化。"
    state = service.get_study_state("view-1", "overview")

    assert state["stale"] is True
    assert state["document"]["status"] == "success"
    assert state["latest_attempt"]["status"] == "success"


def test_study_state_returns_source_progress_before_visual_document(tmp_path):
    session = _session()
    session["state"] = "generating_ai"
    session["ai"]["overview"] = ""
    session["progress"] = {
        "stage": "calibrating",
        "stage_label": "正在生成全文总结",
        "percent": 80,
    }
    service, repository, _ = _service(tmp_path, FakeLLM(), session=session)

    state = service.get_study_state("view-1", "diagram")

    assert state["phase"] == "source_processing"
    assert state["source_progress"]["stage"] == "waiting_analysis"
    assert state["workflow_progress"]["stage"] == "waiting_analysis"
    assert state["workflow_progress"]["overall_percent"] >= 18
    assert state["generation_progress"] is None
    assert state["document"] is None
    assert state["latest_attempt"] is None
    assert repository.list_documents("study", "view-1") == []


def _outline():
    topics = [
        ("knowledge", "知识选择", "先判断知识价值", "价值"),
        ("search", "知识搜索", "建立全景搜索视角", "搜索"),
        ("understand", "深度理解", "从思维模式理解知识", "理解"),
        ("apply", "实践应用", "按需学习并立即使用", "应用"),
    ]
    return {
        "title": "高效学习完整框架",
        "thesis": "学习是从知识选择到实践应用的完整闭环。",
        "audience_goal": "建立能产生实际结果的学习系统",
        "sections": [
            {
                "id": section_id,
                "title": title,
                "core_message": message,
                "key_points": [message, f"{title}的落地动作"],
                "evidence_queries": [query, title],
                "recommended_block_type": "concept_grid",
            }
            for section_id, title, message, query in topics
        ],
    }


def _long_session():
    session = _session()
    topics = ["价值", "搜索", "理解", "应用"]
    lines = []
    for topic_index, topic in enumerate(topics):
        for item_index in range(8):
            lines.append(
                {
                    "id": f"{topic}-{item_index}",
                    "text": f"{topic}章节第{item_index + 1}条：这是关于{topic}方法、原则与案例的完整说明。",
                    "seekable": False,
                    "start_seconds": None,
                }
            )
    session["transcript"]["lines"] = lines
    session["ai"]["overview"] = "全文依次讨论知识价值、知识搜索、深度理解和实践应用。"
    session["source"] = {
        "kind": "document",
        "filename": "learning.pdf",
        "media_type": "application/pdf",
    }
    return session


def _long_diagram_document():
    refs = [
        _ref_id("价值-0"),
        _ref_id("搜索-0"),
        _ref_id("理解-0"),
        _ref_id("应用-0"),
    ]
    pages = [
        {
            "id": "overview",
            "title": "全景地图",
            "learning_goal": "理解学习闭环",
            "blocks": [_hero("overview-hero", refs=refs[:3])],
        }
    ]
    for section_id, title, _, topic in [
        ("knowledge", "知识选择", "", "价值"),
        ("search", "知识搜索", "", "搜索"),
        ("understand", "深度理解", "", "理解"),
        ("apply", "实践应用", "", "应用"),
    ]:
        pages.append(
            {
                "id": section_id,
                "title": title,
                "learning_goal": f"掌握{title}",
                "blocks": [_hero(f"{section_id}-hero", refs=[_ref_id(f"{topic}-0")])],
            }
        )
    return _document(document_type="diagram", pages=pages)


def test_long_document_uses_outline_then_evidence_backed_visual(tmp_path):
    llm = FakeLLM(_outline(), _long_diagram_document())
    service, repository, _ = _service(
        tmp_path,
        llm,
        session=_long_session(),
        llm_config={"visual_learning_long_content_chars": 200},
    )
    progress_updates = []
    original_update_progress = repository.update_progress

    def capture_progress(document_id, generation_token, progress):
        progress_updates.append(dict(progress))
        return original_update_progress(document_id, generation_token, progress)

    repository.update_progress = capture_progress

    result = service.generate_study("view-1", "diagram")

    assert result["status"] == "success"
    assert [call["task_type"] for call in llm.calls] == [
        "visual_outline",
        "visual_diagram",
    ]
    assert [page["id"] for page in result["document_json"]["pages"]] == [
        "overview",
        "knowledge",
        "search",
        "understand",
        "apply",
    ]
    used_refs = {
        ref_id
        for page in result["document_json"]["pages"]
        for block in page["blocks"]
        for ref_id in block["source_ref_ids"]
    }
    assert any("价值-" in ref_id for ref_id in used_refs)
    assert any("理解-" in ref_id for ref_id in used_refs)
    assert any("应用-" in ref_id for ref_id in used_refs)
    assert result["progress_json"]["stage"] == "completed"
    evidence_progress = [
        item for item in progress_updates if item["stage"] == "selecting_evidence"
    ][-1]
    assert evidence_progress["completed_units"] == 4
    assert evidence_progress["total_units"] == 4
    assert evidence_progress["basis"] == "completed_sections"


def test_long_document_uses_separate_outline_and_render_models(tmp_path):
    llm = FakeLLM(_outline(), _long_diagram_document())
    service, _, _ = _service(
        tmp_path,
        llm,
        session=_long_session(),
        llm_config={
            "visual_learning_long_content_chars": 200,
            "visual_learning_outline_model": "outline-pro",
            "visual_learning_outline_reasoning_effort": "high",
            "visual_learning_render_model": "render-pro",
            "visual_learning_render_reasoning_effort": "disabled",
        },
    )

    result = service.generate_study("view-1", "diagram")

    assert result["status"] == "success"
    assert [
        (call["model"], call["reasoning_effort"]) for call in llm.calls
    ] == [("outline-pro", "high"), ("render-pro", "disabled")]


def test_short_document_only_uses_render_model(tmp_path):
    llm = FakeLLM(_document(document_type="diagram"))
    service, _, _ = _service(
        tmp_path,
        llm,
        llm_config={
            "visual_learning_outline_model": "outline-pro",
            "visual_learning_render_model": "render-pro",
            "visual_learning_render_reasoning_effort": "disabled",
        },
    )

    result = service.generate_study("view-1", "diagram")

    assert result["status"] == "success"
    assert [(call["model"], call["reasoning_effort"]) for call in llm.calls] == [
        ("render-pro", "disabled")
    ]


def test_legacy_visual_model_config_remains_supported(tmp_path):
    llm = FakeLLM(_outline(), _long_diagram_document())
    service, _, _ = _service(
        tmp_path,
        llm,
        session=_long_session(),
        llm_config={"visual_learning_long_content_chars": 200},
    )

    result = service.generate_study("view-1", "diagram")

    assert result["status"] == "success"
    assert [(call["model"], call["reasoning_effort"]) for call in llm.calls] == [
        ("visual-test-model", "high"),
        ("visual-test-model", "high"),
    ]


def test_long_source_retains_full_refs_and_removes_control_watermark():
    from video_transcript_api.visual_learning.source_resolver import StudySourceResolver

    session = _long_session()
    session["transcript"]["lines"].insert(
        3,
        {"id": "watermark", "text": "\x00\x08ÿfôY\x1a[PNf\x00https://spam.test", "seekable": False},
    )
    source = StudySourceResolver(
        FakeStudyService(session), max_content_chars=500
    ).resolve("view-1")

    assert len(source.source_refs) == len(session["transcript"]["lines"]) - 1
    assert "watermark" not in source.content
    assert _ref_id("价值-0") in source.ref_texts
    assert _ref_id("理解-0") in source.ref_texts
    assert _ref_id("应用-7") in source.ref_texts
    assert _ref_id("价值-0") in source.content
    assert _ref_id("应用-7") in source.content
