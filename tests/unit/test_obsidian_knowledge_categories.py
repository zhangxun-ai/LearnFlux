from video_transcript_api.obsidian.knowledge_models import KnowledgeItem


def test_recommender_uses_bounded_server_prompt_and_candidate_schema():
    from video_transcript_api.obsidian.knowledge_categories import (
        ObsidianCategoryRecommender,
    )

    captured = {}

    def fake_llm(**kwargs):
        captured.update(kwargs)
        return {
            "category": "AI",
            "confidence": 0.82,
            "reason": "内容匹配",
        }

    result = ObsidianCategoryRecommender(fake_llm).recommend(
        candidates=["其他", "AI"],
        title="标题",
        analysis_excerpt="a" * 5000,
        raw_excerpt="r" * 5000,
    )

    assert result.category == "AI"
    assert result.recommended_by == "llm"
    assert len(captured["prompt"]) < 3500
    assert captured["response_schema"]["properties"]["category"]["enum"] == [
        "其他",
        "AI",
    ]


def test_recommender_falls_back_without_calling_llm_for_empty_candidates():
    from video_transcript_api.obsidian.knowledge_categories import (
        ObsidianCategoryRecommender,
    )

    calls = []
    recommender = ObsidianCategoryRecommender(
        lambda **kwargs: calls.append(kwargs)
    )
    empty = recommender.recommend(
        candidates=[], title="t", analysis_excerpt="a", raw_excerpt="r"
    )
    assert empty.category == ""
    assert empty.reason == "category_not_configured"
    assert calls == []


def test_recommender_falls_back_for_invalid_json_exception_and_non_candidate():
    from video_transcript_api.obsidian.knowledge_categories import (
        ObsidianCategoryRecommender,
    )

    failures = [
        lambda **_: "not json",
        lambda **_: {"category": "不存在"},
        lambda **_: (_ for _ in ()).throw(TimeoutError()),
    ]
    for fake in failures:
        result = ObsidianCategoryRecommender(fake).recommend(
            candidates=["AI", "其他"],
            title="t",
            analysis_excerpt="a",
            raw_excerpt="r",
        )
        assert result.category == "其他"
        assert result.recommended_by == "fallback"

    first = ObsidianCategoryRecommender(lambda **_: "").recommend(
        candidates=["Z", "A"],
        title="t",
        analysis_excerpt="a",
        raw_excerpt="r",
    )
    assert first.category == "A"


def test_collection_recommendation_aggregates_collection_and_positioned_items():
    from video_transcript_api.obsidian.knowledge_categories import (
        ObsidianCategoryRecommender,
    )

    captured = {}

    def fake_llm(**kwargs):
        captured.update(kwargs)
        return {"category": "商业", "confidence": 0.6, "reason": "合集主题"}

    items = [
        KnowledgeItem(
            "u", "v2", "第二课", "r2", "a2", "view_only", "/view/v2",
            "c", "s2", "作者-专题", "作者", 2,
        ),
        KnowledgeItem(
            "u", "v1", "第一课", "r1", "a1", "view_only", "/view/v1",
            "c", "s1", "作者-专题", "作者", 1,
        ),
    ]
    result = ObsidianCategoryRecommender(fake_llm).recommend_collection(
        candidates=["商业", "其他"],
        collection={
            "title": "专题",
            "creator_name": "作者",
            "description": "简介",
            "summary_markdown": "主线解读",
        },
        items=items,
    )

    prompt = captured["prompt"]
    assert result.category == "商业"
    assert all(value in prompt for value in ("专题", "作者", "简介", "主线解读"))
    assert prompt.index("第一课") < prompt.index("第二课")
