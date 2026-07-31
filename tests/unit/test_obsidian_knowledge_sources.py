from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_single_prefers_calibrated_and_uses_task_source_metadata(tmp_path):
    from video_transcript_api.obsidian.knowledge_sources import ObsidianKnowledgeSourceResolver

    local = tmp_path / "lesson.mp4"
    local.write_bytes(b"media")
    cache = MagicMock()
    cache.get_cache_by_view_token.return_value = {
        "llm_calibrated": "校对文本",
        "transcript_data": {"segments": [{"text": "结构化原文"}]},
        "llm_summary": "AI 解读",
        "task_info": {
            "title": "课程标题",
            "url": "local://lesson.mp4",
            "source_file_path": str(local),
        },
    }

    item = ObsidianKnowledgeSourceResolver(cache_manager=cache).resolve_single("u", "view-1")

    assert item.title == "课程标题"
    assert item.raw_content == "校对文本"
    assert item.analysis_content == "AI 解读"
    assert item.source_kind == "local_file"
    assert item.source_access == str(local)


def test_single_formats_structured_transcript_and_falls_back_to_view_url():
    from video_transcript_api.obsidian.knowledge_sources import ObsidianKnowledgeSourceResolver

    cache = MagicMock()
    cache.get_cache_by_view_token.return_value = {
        "transcript_data": {"segments": [{"text": "第一段"}, {"text": "第二段"}]},
        "llm_summary": "解读",
        "task_info": {"title": "标题", "url": "local://missing", "source_file_path": "/missing/file.mp4"},
    }

    item = ObsidianKnowledgeSourceResolver(cache_manager=cache).resolve_single("u", "view-2")

    assert "第一段" in item.raw_content and "第二段" in item.raw_content
    assert "{'segments'" not in item.raw_content
    assert item.source_kind == "view_only"
    assert item.source_access == "/view/view-2"


@pytest.mark.parametrize(
    ("cache_data", "code"),
    [
        ({"transcript_data": "", "llm_summary": "analysis"}, "transcript_not_ready"),
        ({"transcript_data": "raw", "llm_summary": ""}, "analysis_not_ready"),
    ],
)
def test_single_reports_stable_not_ready_reason(cache_data, code):
    from video_transcript_api.obsidian.knowledge_sources import (
        KnowledgeContentNotReady,
        ObsidianKnowledgeSourceResolver,
    )

    cache = MagicMock()
    cache.get_cache_by_view_token.return_value = cache_data
    with pytest.raises(KnowledgeContentNotReady, match=code):
        ObsidianKnowledgeSourceResolver(cache_manager=cache).resolve_single("u", "view")


def test_collection_resolves_selected_items_in_position_order_and_reports_unready(tmp_path):
    from video_transcript_api.obsidian.knowledge_sources import ObsidianKnowledgeSourceResolver

    local = tmp_path / "local.mp4"
    local.write_bytes(b"x")
    collection_service = MagicMock()
    collection_service.get_collection_detail.return_value = {
        "id": "c1",
        "title": "专题",
        "creator_name": "作者",
        "description": "简介",
        "summary_markdown": "主线",
        "sources": [
            {"id": "s2", "view_token": "v2", "title": "02", "position": 2},
            {"id": "s1", "view_token": "v1", "title": "01", "position": 1},
            {"id": "s3", "view_token": "v3", "title": "03", "position": 3},
        ],
    }
    details = {
        "s1": {"id": "s1", "view_token": "v1", "title": "01", "position": 1, "transcript": "raw1", "summary": "ai1", "source_access": {"kind": "online_url", "url": "https://e/1"}},
        "s2": {"id": "s2", "view_token": "v2", "title": "02", "position": 2, "transcript": "raw2", "summary": "ai2", "source_access": {"kind": "local_file", "view_url": "/view/v2"}},
        "s3": {"id": "s3", "view_token": "v3", "title": "03", "position": 3, "transcript": "", "summary": "ai3", "source_access": {"kind": "view_only", "view_url": "/view/v3"}},
    }
    collection_service.get_source_detail.side_effect = lambda _c, source_id: details[source_id]
    collection_service.get_source_file_path.side_effect = lambda _c, source_id: str(local) if source_id == "s2" else None

    collection, items, unavailable = ObsidianKnowledgeSourceResolver(
        cache_manager=MagicMock(), collection_service=collection_service
    ).resolve_collection("u", "c1", ["s3", "s2", "s1"])

    from video_transcript_api.obsidian.knowledge_markdown import (
        COLLECTION_INDEX_SOURCE_ID,
        COLLECTION_INDEX_TITLE,
    )

    assert [item.source_id for item in items] == [
        COLLECTION_INDEX_SOURCE_ID,
        "s1",
        "s2",
    ]
    assert items[0].title == COLLECTION_INDEX_TITLE
    assert "全系列主线总结" in items[0].analysis_content
    assert "主线" in items[0].analysis_content
    assert "01" in items[0].analysis_content
    assert items[1].title == "01"
    assert items[1].source_access == "https://e/1"
    assert items[2].source_access == str(local)
    assert items[1].collection_title == "作者-专题"
    assert unavailable == [{"source_id": "s3", "code": "transcript_not_ready"}]
    assert collection["title"] == "专题"
