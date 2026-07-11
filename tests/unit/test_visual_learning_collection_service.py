from dataclasses import replace

import pytest

from video_transcript_api.visual_learning.interpretation import InterpretationSection
from video_transcript_api.visual_learning.schemas import SourceReference
from video_transcript_api.visual_learning.source_resolver import (
    VisualLearningSource,
    VisualLearningSourceNotFound,
)


class FakeResolver:
    def __init__(self, source):
        self.source = source

    def resolve(self, owner_id):
        if self.source is None:
            raise VisualLearningSourceNotFound("source not found")
        return self.source


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        from video_transcript_api.llm import StructuredResult

        self.calls.append(kwargs)
        return StructuredResult(success=True, data=self.responses.pop(0))


def _section_ref(owner_type, owner_id, index):
    return f"{owner_type}:{owner_id}:summary:section:section-{index:02d}"


def _source(owner_type="collection", owner_id="collection-1", source_hash="hash-1"):
    sections = tuple(
        InterpretationSection(
            id=f"section-{index:02d}",
            title=title,
            markdown=f"{title}的完整既有解读。",
            source_ref_ids=(_section_ref(owner_type, owner_id, index),),
        )
        for index, title in enumerate(["选择", "理解", "应用"], start=1)
    )
    refs = [
        SourceReference(
            id=section.source_ref_ids[0],
            owner_type=owner_type,
            owner_id=owner_id,
            excerpt=section.markdown,
        )
        for section in sections
    ]
    return VisualLearningSource(
        owner_type=owner_type,
        owner_id=owner_id,
        title="学习集合",
        summary="集合总结",
        content="集合原文",
        source_refs=refs,
        source_hash=source_hash,
        source_progress={
            "stage": "ready_for_generation",
            "stage_label": "集合总结已完成",
            "percent": 100,
            "analysis_mode": owner_type,
        },
        source_kind=owner_type,
        source_filename="学习集合",
        total_content_chars=100,
        ref_texts={ref.id: ref.excerpt for ref in refs},
        interpretation_sections=sections,
    )


def _hero(refs, block_id="hero"):
    return {
        "id": block_id,
        "type": "hero_summary",
        "title": "核心结论",
        "source_ref_ids": refs,
        "headline": "建立学习闭环",
        "summary": "从选择到理解，再到应用。",
        "points": ["选择", "理解", "应用"],
    }


def _review(refs):
    return {
        "id": "review",
        "type": "review_questions",
        "title": "主动回忆",
        "source_ref_ids": refs,
        "questions": [
            {"question": "如何选择知识？", "answer": "先判断价值。"},
            {"question": "如何完成闭环？", "answer": "理解后立即应用。"},
        ],
    }


def _document(owner_type, owner_id, document_type="overview", *, title="学习集合"):
    refs = [_section_ref(owner_type, owner_id, index) for index in range(1, 4)]
    if document_type == "overview":
        pages = [
            {
                "id": "overview",
                "title": "全景关系",
                "learning_goal": "理解三节的宏观关系",
                "blocks": [_hero(refs)],
            }
        ]
    else:
        pages = [
            {
                "id": f"section-{index:02d}",
                "title": f"第 {index} 节",
                "learning_goal": "理解本节",
                "blocks": [_hero([ref], f"hero-{index}")],
            }
            for index, ref in enumerate(refs, start=1)
        ]
        pages[-1]["blocks"].append(_review([refs[-1]]))
    return {
        "version": 1,
        "document_type": document_type,
        "title": title,
        "recommended_style": "study-notes",
        "selected_diagram_type": None,
        "diagram_recommendations": [],
        "pages": pages,
        "source_refs": [],
    }


def _service(tmp_path, llm):
    from video_transcript_api.visual_learning.repository import VisualLearningRepository
    from video_transcript_api.visual_learning.service import VisualLearningService

    study = FakeResolver(_source("study", "view-1"))
    collection = FakeResolver(_source())
    repository = VisualLearningRepository(str(tmp_path / "visual.db"))
    service = VisualLearningService(
        repository,
        study,
        llm_callable=llm,
        llm_config={"visual_learning_model": "visual-test-model"},
        collection_source_resolver=collection,
    )
    return service, repository, study, collection


def test_collection_wrappers_reuse_and_keep_document_types_independent(tmp_path):
    llm = FakeLLM(
        _document("collection", "collection-1", "overview"),
        _document("collection", "collection-1", "full_note"),
    )
    service, repository, _, _ = _service(tmp_path, llm)

    overview = service.prepare_collection_generation("collection-1", "overview")
    reused = service.prepare_collection_generation("collection-1", "overview")
    full_note = service.prepare_collection_generation("collection-1", "full_note")
    generated_overview = service.generate_prepared_collection(
        overview["id"], "collection-1", "overview"
    )
    generated_full_note = service.generate_prepared_collection(
        full_note["id"], "collection-1", "full_note"
    )

    assert overview["owner_type"] == "collection"
    assert reused["id"] == overview["id"]
    assert full_note["id"] != overview["id"]
    assert generated_overview["status"] == "success"
    assert generated_full_note["status"] == "success"
    assert len(repository.list_documents("collection", "collection-1")) == 2


def test_collection_overview_requires_three_distinct_section_refs(tmp_path):
    valid = _document("collection", "collection-1")
    payload = _document("collection", "collection-1")
    payload["pages"][0]["blocks"][0]["source_ref_ids"] = [
        _section_ref("collection", "collection-1", 1),
        _section_ref("collection", "collection-1", 2),
    ]
    service, _, _, _ = _service(tmp_path, FakeLLM(valid, payload))

    first = service.generate_collection("collection-1", "overview")
    result = service.generate_collection("collection-1", "overview", force=True)

    assert first["status"] == "success"
    assert result["status"] == "failed"
    assert result["error_message"] == (
        "overview must cite at least three interpretation sections"
    )


def test_collection_state_detects_stale_source_and_serializes_sections(tmp_path):
    llm = FakeLLM(_document("collection", "collection-1"))
    service, _, _, collection = _service(tmp_path, llm)
    generated = service.generate_collection("collection-1", "overview")

    ready = service.get_collection_state("collection-1", "overview")
    collection.source = _source(source_hash="hash-2")
    stale = service.get_collection_state("collection-1", "overview")

    assert ready["document"]["id"] == generated["id"]
    assert ready["interpretation_available"] is True
    assert [item["id"] for item in ready["interpretation_sections"]] == [
        "section-01",
        "section-02",
        "section-03",
    ]
    assert stale["stale"] is True
    assert stale["document"]["status"] == "success"


def test_document_state_uses_owner_resolver_and_preserves_missing_source(tmp_path):
    llm = FakeLLM(_document("collection", "collection-1"))
    service, _, _, collection = _service(tmp_path, llm)
    generated = service.generate_collection("collection-1", "overview")
    collection.source = None

    state = service.get_document_state(generated["id"])

    assert state["document"]["id"] == generated["id"]
    assert state["stale"] is True
    assert state["interpretation_sections"] == []
    assert state["interpretation_available"] is False


def test_prepared_collection_validates_owner_and_study_api_is_preserved(tmp_path):
    from video_transcript_api.visual_learning.service import (
        VisualLearningGenerationError,
    )

    llm = FakeLLM(
        _document("study", "view-1"),
        _document("collection", "collection-1"),
    )
    service, _, _, _ = _service(tmp_path, llm)

    study = service.generate_study("view-1", "overview")
    collection = service.prepare_collection_generation("collection-1", "overview")

    with pytest.raises(
        VisualLearningGenerationError,
        match="prepared document options mismatch",
    ):
        service.generate_prepared_collection(study["id"], "collection-1", "overview")
    generated = service.generate_prepared_collection(
        collection["id"], "collection-1", "overview"
    )
    assert study["owner_type"] == "study"
    assert generated["owner_type"] == "collection"


@pytest.mark.parametrize("owner_type", ["study", "collection"])
@pytest.mark.parametrize("mismatch", ["owner_type", "owner_id"])
def test_prepared_generation_rejects_resolver_owner_mismatch(
    tmp_path,
    owner_type,
    mismatch,
):
    from video_transcript_api.visual_learning.service import (
        VisualLearningGenerationError,
    )

    service, _, study, collection = _service(tmp_path, FakeLLM())
    if owner_type == "study":
        pending = service.prepare_study_generation("view-1", "overview")
        resolver = study
        generate = lambda: service.generate_prepared_study(
            pending["id"], "view-1", "overview"
        )
    else:
        pending = service.prepare_collection_generation(
            "collection-1", "overview"
        )
        resolver = collection
        generate = lambda: service.generate_prepared_collection(
            pending["id"], "collection-1", "overview"
        )

    if mismatch == "owner_type":
        wrong_value = "collection" if owner_type == "study" else "study"
        resolver.source = replace(resolver.source, owner_type=wrong_value)
    else:
        resolver.source = replace(resolver.source, owner_id="wrong-owner")

    with pytest.raises(
        VisualLearningGenerationError,
        match="resolved source owner mismatch",
    ):
        generate()


def _mismatched_source(source, mismatch):
    if mismatch == "owner_type":
        wrong_value = "collection" if source.owner_type == "study" else "study"
        return replace(source, owner_type=wrong_value)
    return replace(source, owner_id="wrong-owner")


@pytest.mark.parametrize("owner_type", ["study", "collection"])
@pytest.mark.parametrize("mismatch", ["owner_type", "owner_id"])
def test_owner_state_rejects_resolver_owner_mismatch(
    tmp_path,
    owner_type,
    mismatch,
):
    from video_transcript_api.visual_learning.service import (
        VisualLearningGenerationError,
    )

    service, _, study, collection = _service(tmp_path, FakeLLM())
    resolver = study if owner_type == "study" else collection
    resolver.source = _mismatched_source(resolver.source, mismatch)

    with pytest.raises(
        VisualLearningGenerationError,
        match="resolved source owner mismatch",
    ):
        if owner_type == "study":
            service.get_study_state("view-1", "overview")
        else:
            service.get_collection_state("collection-1", "overview")


@pytest.mark.parametrize("owner_type", ["study", "collection"])
@pytest.mark.parametrize("mismatch", ["owner_type", "owner_id"])
def test_document_state_hides_sections_from_mismatched_owner_source(
    tmp_path,
    owner_type,
    mismatch,
):
    owner_id = "view-1" if owner_type == "study" else "collection-1"
    llm = FakeLLM(_document(owner_type, owner_id))
    service, _, study, collection = _service(tmp_path, llm)
    if owner_type == "study":
        generated = service.generate_study(owner_id, "overview")
        resolver = study
    else:
        generated = service.generate_collection(owner_id, "overview")
        resolver = collection
    resolver.source = _mismatched_source(resolver.source, mismatch)

    state = service.get_document_state(generated["id"])

    assert state["document"]["id"] == generated["id"]
    assert state["stale"] is True
    assert state["interpretation_sections"] == []
    assert state["interpretation_available"] is False
