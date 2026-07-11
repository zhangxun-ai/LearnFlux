import copy

import pytest


def _summary(suffix=""):
    return (
        "## 集合主线\n先建立核心框架。\n\n"
        "## 关键方法\n再比较不同方法。\n\n"
        f"## 实践步骤\n最后进入实践。{suffix}"
    )


class FakeCollectionService:
    def __init__(self, detail=None, source_details=None, knowledge_map=None):
        self.detail = detail
        self.source_details = source_details or {}
        self.knowledge_map = knowledge_map
        self.detail_calls = 0
        self.source_calls = []
        self.map_calls = []

    def get_collection_detail(self, collection_id):
        self.detail_calls += 1
        if collection_id != "collection-1" or self.detail is None:
            raise ValueError("collection not found")
        return copy.deepcopy(self.detail)

    def get_source_detail(self, collection_id, source_id):
        self.source_calls.append((collection_id, source_id))
        value = self.source_details.get(source_id)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise ValueError("source not found")
        return copy.deepcopy(value)

    def get_knowledge_map(self, collection_id, scope, source_id=None):
        self.map_calls.append((collection_id, scope, source_id))
        if isinstance(self.knowledge_map, Exception):
            raise self.knowledge_map
        return copy.deepcopy(self.knowledge_map)


def _detail(summary=None, sources=None):
    return {
        "id": "collection-1",
        "title": "Agent 学习合集",
        "collection_type": "video_course",
        "summary_markdown": _summary() if summary is None else summary,
        "sources": sources
        if sources is not None
        else [
            {
                "id": "source-1",
                "title": "第一课.mp4",
                "source_type": "video",
                "task_status": "success",
                "position": 1,
            }
        ],
    }


def _source_detail(summary="第一课总结", transcript="第一段原文。\n\n第二段原文。"):
    return {
        "id": "source-1",
        "title": "第一课.mp4",
        "source_type": "video",
        "task_status": "success",
        "summary": summary,
        "transcript": transcript,
        "raw_transcript": transcript,
        "content_ready": bool(transcript),
    }


def _resolver(service, max_content_chars=60000):
    from video_transcript_api.visual_learning.collection_source_resolver import (
        CollectionSourceResolver,
    )

    return CollectionSourceResolver(service, max_content_chars=max_content_chars)


def test_collection_source_not_found_is_normalized():
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotFound,
    )

    with pytest.raises(VisualLearningSourceNotFound):
        _resolver(FakeCollectionService()).resolve("missing")


@pytest.mark.parametrize("summary", ["", "一句不足以分节的总结。"])
def test_collection_source_requires_complete_interpretation(summary):
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    service = FakeCollectionService(
        detail=_detail(summary=summary),
        source_details={"source-1": _source_detail()},
    )

    with pytest.raises(VisualLearningSourceNotReady) as caught:
        _resolver(service).resolve("collection-1")

    assert caught.value.terminal is True
    assert service.source_calls == []


def test_collection_source_requires_at_least_one_readable_successful_source():
    from video_transcript_api.visual_learning.source_resolver import (
        VisualLearningSourceNotReady,
    )

    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail(summary="", transcript="")},
    )

    with pytest.raises(VisualLearningSourceNotReady) as caught:
        _resolver(service).resolve("collection-1")

    assert caught.value.terminal is True


def test_collection_source_skips_missing_source_when_another_is_usable():
    sources = [
        {"id": "missing", "title": "缺失.mp4", "task_status": "success"},
        {"id": "source-1", "title": "第一课.mp4", "task_status": "success"},
        {"id": "failed", "title": "失败.mp4", "task_status": "failed"},
    ]
    service = FakeCollectionService(
        detail=_detail(sources=sources),
        source_details={
            "missing": ValueError("source not found"),
            "source-1": _source_detail(),
        },
    )

    source = _resolver(service).resolve("collection-1")

    assert service.detail_calls == 1
    assert service.source_calls == [
        ("collection-1", "missing"),
        ("collection-1", "source-1"),
    ]
    assert source.owner_type == "collection"
    assert source.source_progress["stage"] == "ready_for_generation"


def test_collection_source_exposes_stable_refs_and_optional_map():
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail()},
        knowledge_map={
            "status": "success",
            "map_json": {"nodes": [{"id": "core", "label": "核心"}]},
        },
    )

    source = _resolver(service).resolve("collection-1")

    ref_ids = [ref.id for ref in source.source_refs]
    assert ref_ids == [
        "collection:collection-1:summary",
        "collection:collection-1:summary:section:section-01",
        "collection:collection-1:summary:section:section-02",
        "collection:collection-1:summary:section:section-03",
        "collection:collection-1:knowledge-map",
        "collection:collection-1:source:source-1:summary",
        "collection:collection-1:source:source-1:paragraph:0",
        "collection:collection-1:source:source-1:paragraph:1",
    ]
    assert source.ref_texts[ref_ids[1]] == source.interpretation_sections[0].markdown
    assert source.ref_texts[ref_ids[4]].startswith('{"nodes"')
    assert source.ref_texts[ref_ids[5]] == "第一课总结"
    assert "第一段原文。" in source.ref_texts[ref_ids[6]]
    assert service.map_calls == [("collection-1", "collection", None)]


def test_collection_source_normalizes_summary_before_sections_and_hashing():
    plain = _summary()
    wrapped = (
        "```markdown\n---\ntitle: Agent 学习合集\nsource_type: video_course\n---\n"
        f"{plain}\n```"
    )
    plain_service = FakeCollectionService(
        detail=_detail(summary=plain),
        source_details={"source-1": _source_detail()},
    )
    wrapped_service = FakeCollectionService(
        detail=_detail(summary=wrapped),
        source_details={"source-1": _source_detail()},
    )

    plain_source = _resolver(plain_service).resolve("collection-1")
    wrapped_source = _resolver(wrapped_service).resolve("collection-1")

    assert wrapped_source.summary == plain
    assert wrapped_source.interpretation_sections == plain_source.interpretation_sections
    assert wrapped_source.source_hash == plain_source.source_hash


def test_collection_source_does_not_require_knowledge_map():
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail()},
        knowledge_map=ValueError("map unavailable"),
    )

    source = _resolver(service).resolve("collection-1")

    assert "collection:collection-1:knowledge-map" not in source.ref_texts


def test_collection_source_propagates_unexpected_knowledge_map_failure():
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail()},
        knowledge_map=RuntimeError("database unavailable"),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        _resolver(service).resolve("collection-1")


def test_collection_source_propagates_unexpected_source_detail_failure():
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": RuntimeError("cache database unavailable")},
    )

    with pytest.raises(RuntimeError, match="cache database unavailable"):
        _resolver(service).resolve("collection-1")


def test_collection_source_prioritizes_all_summaries_before_transcripts():
    sources = [
        {"id": "source-1", "title": "第一课.mp4", "task_status": "success"},
        {"id": "source-2", "title": "第二课.mp4", "task_status": "success"},
    ]
    service = FakeCollectionService(
        detail=_detail(sources=sources),
        source_details={
            "source-1": _source_detail(
                summary="第一课高优先级总结",
                transcript="第一课低优先级原文" * 40,
            ),
            "source-2": {
                **_source_detail(
                    summary="第二课高优先级总结",
                    transcript="第二课低优先级原文",
                ),
                "id": "source-2",
                "title": "第二课.mp4",
            },
        },
        knowledge_map={"map_json": {"topic": "集合知识地图"}},
    )

    source = _resolver(service, max_content_chars=520).resolve("collection-1")

    summary_ids = [
        "collection:collection-1:source:source-1:summary",
        "collection:collection-1:source:source-2:summary",
    ]
    paragraph_ids = [
        ref.id for ref in source.source_refs if ":paragraph:" in ref.id
    ]
    ref_ids = [ref.id for ref in source.source_refs]
    assert max(ref_ids.index(ref_id) for ref_id in summary_ids) < min(
        ref_ids.index(ref_id) for ref_id in paragraph_ids
    )
    assert all(f"[{ref_id}]" in source.content for ref_id in summary_ids)
    assert source.content.index(f"[{summary_ids[1]}]") < source.content.index(
        f"[{paragraph_ids[0]}]"
    )


def test_collection_source_bounds_retained_transcript_evidence_but_hashes_all_text():
    max_chars = 240
    sources = [
        {"id": f"source-{index}", "title": f"第{index}课.mp4", "task_status": "success"}
        for index in range(1, 4)
    ]
    source_details = {
        source["id"]: {
            **_source_detail(
                summary=f"第{index}课总结",
                transcript=(f"第{index}课开头" * 2000) + (f"第{index}课结尾" * 2000),
            ),
            "id": source["id"],
            "title": source["title"],
        }
        for index, source in enumerate(sources, start=1)
    }
    service = FakeCollectionService(
        detail=_detail(sources=sources),
        source_details=source_details,
    )
    resolver = _resolver(service, max_content_chars=max_chars)

    first = resolver.resolve("collection-1")
    first_evidence = {
        ref_id: text
        for ref_id, text in first.ref_texts.items()
        if ":paragraph:" in ref_id
    }
    transcript = service.source_details["source-2"]["transcript"]
    midpoint = len(transcript) // 2
    replacement = "保留证据之外的变化"
    service.source_details["source-2"]["transcript"] = (
        transcript[:midpoint]
        + replacement
        + transcript[midpoint + len(replacement) :]
    )
    second = resolver.resolve("collection-1")
    second_evidence = {
        ref_id: text
        for ref_id, text in second.ref_texts.items()
        if ":paragraph:" in ref_id
    }

    assert len(first.content) <= max_chars
    assert sum(len(text) for text in first_evidence.values()) <= max_chars * 2
    assert first_evidence == second_evidence
    assert first.source_hash != second.source_hash


def test_collection_source_splits_long_single_paragraph_into_bounded_evidence():
    transcript = ("开头内容" * 1200) + ("中间内容" * 1200) + ("末尾标记" * 1200)
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail(transcript=transcript)},
    )

    source = _resolver(service, max_content_chars=600).resolve("collection-1")

    transcript_refs = [
        ref for ref in source.source_refs if ":paragraph:" in ref.id
    ]
    retained = [source.ref_texts[ref.id] for ref in transcript_refs]
    assert len(transcript_refs) >= 2
    assert transcript_refs[0].id.endswith("paragraph:0:chunk:1")
    assert ":chunk:" in transcript_refs[-1].id
    assert "末尾标记" in retained[-1]
    assert sum(len(text) for text in retained) <= 600


def test_collection_source_bounds_original_evidence_globally_across_many_sources():
    max_chars = 180
    sources = [
        {"id": f"source-{index}", "title": f"第{index}课", "task_status": "success"}
        for index in range(20)
    ]
    service = FakeCollectionService(
        detail=_detail(sources=sources),
        source_details={
            source["id"]: {
                **_source_detail(
                    summary=f"第{index}课总结" * 200,
                    transcript=f"第{index}课原文" * 2000,
                ),
                "id": source["id"],
            }
            for index, source in enumerate(sources)
        },
        knowledge_map={"map_json": {"topic": "知识地图" * 10}},
    )

    source = _resolver(service, max_content_chars=max_chars).resolve("collection-1")

    original_refs = [
        ref
        for ref in source.source_refs
        if ref.id == "collection:collection-1:knowledge-map" or ":source:" in ref.id
    ]
    retained_ref_text = sum(len(source.ref_texts[ref.id]) for ref in original_refs)
    retained_excerpts = sum(len(ref.excerpt) for ref in original_refs)
    assert retained_ref_text <= max_chars
    assert retained_excerpts <= max_chars
    assert retained_ref_text + retained_excerpts <= max_chars * 2


def test_collection_source_keeps_true_final_chunk_with_odd_budget():
    service = FakeCollectionService(
        detail=_detail(),
        source_details={
            "source-1": _source_detail(
                summary="", transcript=("A" * 1200) + "Z"
            )
        },
    )

    source = _resolver(service, max_content_chars=601).resolve("collection-1")

    retained = [
        source.ref_texts[ref.id]
        for ref in source.source_refs
        if ":paragraph:" in ref.id
    ]
    assert retained[-1].endswith("Z")
    assert sum(len(text) for text in retained) <= 601


def test_collection_source_never_emits_partial_reference_prefix():
    summary_row = f"[collection:collection-1:summary] {_summary()}"
    max_chars = len(summary_row) + 8
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail()},
        knowledge_map={"map_json": {"topic": "知识地图"}},
    )

    source = _resolver(service, max_content_chars=max_chars).resolve("collection-1")

    assert source.content == summary_row
    assert not source.content.endswith("[collect")


def test_collection_source_skips_reference_prefix_without_evidence_text():
    summary_row = f"[collection:collection-1:summary] {_summary()}"
    map_prefix = "[collection:collection-1:knowledge-map] "
    max_chars = len(summary_row) + 1 + len(map_prefix)
    service = FakeCollectionService(
        detail=_detail(),
        source_details={"source-1": _source_detail()},
        knowledge_map={"map_json": {"topic": "知识地图"}},
    )

    source = _resolver(service, max_content_chars=max_chars).resolve("collection-1")

    assert source.content == summary_row


@pytest.mark.parametrize("changed_input", ["summary", "map", "source_summary", "transcript"])
def test_collection_source_hash_tracks_all_full_inputs(changed_input):
    detail = _detail(summary=_summary("甲" * 13000))
    source_detail = _source_detail(summary="来源总结-A", transcript="来源原文-A")
    knowledge_map = {"map_json": {"nodes": [{"label": "知识-A"}]}}
    service = FakeCollectionService(
        detail=detail,
        source_details={"source-1": source_detail},
        knowledge_map=knowledge_map,
    )
    resolver = _resolver(service, max_content_chars=120)
    first = resolver.resolve("collection-1")

    if changed_input == "summary":
        service.detail["summary_markdown"] += "末尾变化"
    elif changed_input == "map":
        service.knowledge_map["map_json"]["nodes"][0]["label"] = "知识-B"
    elif changed_input == "source_summary":
        service.source_details["source-1"]["summary"] = "来源总结-B"
    else:
        service.source_details["source-1"]["transcript"] = "来源原文-B"

    second = resolver.resolve("collection-1")

    assert len(first.content) <= 120
    assert first.source_hash != second.source_hash
