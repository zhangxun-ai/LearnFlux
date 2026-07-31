from video_transcript_api.obsidian.knowledge_models import KnowledgeItem


def _item(collection_id="", source_id=""):
    return KnowledgeItem("u", "view", "标题", "原文\n---\n保留", "解读", "online_url", "https://example.com", collection_id, source_id, "合集")


def test_collection_index_bodies_include_mainline_and_chapter_links():
    from video_transcript_api.obsidian.knowledge_markdown import (
        COLLECTION_INDEX_SOURCE_ID,
        COLLECTION_INDEX_TITLE,
        build_collection_index_bodies,
        managed_document_hash,
        parse_knowledge_markdown,
        render_analysis_knowledge_markdown,
        render_raw_knowledge_markdown,
    )
    from video_transcript_api.obsidian.knowledge_models import KnowledgeItem

    raw_body, analysis_body = build_collection_index_bodies(
        creator="AI小王子",
        collection_title="Codex从0到1实战课",
        description="实战课简介",
        summary_markdown="## 全系列主线\n\n先会安装，再会做技能。",
        chapters=[
            {
                "position": 1,
                "title": "001-CodeX是做什么的？",
                "ready": True,
                "summary": "介绍 Codex 的定位与学习理由",
            },
            {
                "position": 2,
                "title": "002-部署",
                "ready": False,
                "summary": "",
            },
        ],
    )
    assert "AI小王子" in raw_body and "章节目录" in raw_body
    assert "全系列主线总结" in analysis_body
    assert "先会安装" in analysis_body
    assert "[[001-CodeX是做什么的？]]" in analysis_body
    assert ".mp4" not in analysis_body
    assert "未就绪" in analysis_body

    item = KnowledgeItem(
        "u",
        "collection-index:c1",
        COLLECTION_INDEX_TITLE,
        raw_body,
        analysis_body,
        "collection_index",
        "learnflux://collections/c1",
        "c1",
        COLLECTION_INDEX_SOURCE_ID,
        "AI小王子-Codex从0到1实战课",
    )
    rendered = render_analysis_knowledge_markdown(
        item,
        category="知识",
        raw_relative_path="raw/知识/AI小王子-Codex从0到1实战课/00-合集总览.md",
        relative_path="processed/知识/AI小王子-Codex从0到1实战课/00-合集总览.md",
        synced_at="one",
    )
    rendered2 = render_analysis_knowledge_markdown(
        item,
        category="知识",
        raw_relative_path="raw/知识/AI小王子-Codex从0到1实战课/00-合集总览.md",
        relative_path="processed/知识/AI小王子-Codex从0到1实战课/00-合集总览.md",
        synced_at="two",
    )
    fields, body = parse_knowledge_markdown(rendered)
    assert fields["learnflux_role"] == "collection_index"
    assert fields["learnflux_collection_id"] == "c1"
    assert "原文 / 逐字稿" not in body
    assert "全系列主线总结" in body
    assert managed_document_hash(rendered) == managed_document_hash(rendered2)
    assert "原文 / 逐字稿" not in render_raw_knowledge_markdown(
        item,
        category="知识",
        relative_path="raw/知识/AI小王子-Codex从0到1实战课/00-合集总览.md",
        synced_at="one",
    )


def test_renderers_keep_layers_and_hashes_stable_across_sync_time():
    from video_transcript_api.obsidian.knowledge_markdown import (
        managed_document_hash,
        parse_knowledge_markdown,
        render_analysis_knowledge_markdown,
        render_raw_knowledge_markdown,
    )
    raw1 = render_raw_knowledge_markdown(_item(), category="分类", relative_path="raw/分类/标题.md", synced_at="one")
    raw2 = render_raw_knowledge_markdown(_item(), category="分类", relative_path="raw/分类/标题.md", synced_at="two")
    analysis = render_analysis_knowledge_markdown(_item("c", "s"), category="分类", raw_relative_path="raw/分类/合集/标题.md", relative_path="processed/分类/合集/标题.md", synced_at="now")
    assert "type: learnflux-raw" in raw1 and "learnflux_collection_id" not in raw1
    assert managed_document_hash(raw1) == managed_document_hash(raw2)
    assert "type: learnflux-analysis" in analysis
    assert 'raw_note: "[[raw/分类/合集/标题]]"' in analysis
    assert "learnflux_collection_id: c" in analysis
    fields, body = parse_knowledge_markdown(raw1)
    assert fields["content_hash"].startswith("sha256:")
    assert "原文\n---\n保留" in body


def test_content_hash_is_body_only_and_extra_frontmatter_counts_as_external_change():
    from video_transcript_api.obsidian.knowledge_markdown import (
        managed_document_hash,
        parse_knowledge_markdown,
        render_raw_knowledge_markdown,
    )

    first = render_raw_knowledge_markdown(
        _item(),
        category="A",
        relative_path="raw/A/a.md",
        synced_at="one",
    )
    second = render_raw_knowledge_markdown(
        _item(),
        category="B",
        relative_path="raw/B/a.md",
        synced_at="two",
    )
    first_fields, _ = parse_knowledge_markdown(first)
    second_fields, _ = parse_knowledge_markdown(second)
    assert first_fields["content_hash"] == second_fields["content_hash"]
    assert managed_document_hash(first) != managed_document_hash(second)

    externally_edited = first.replace(
        "source: LearnFlux\n", "source: LearnFlux\nuser_field: changed\n"
    )
    assert managed_document_hash(first) != managed_document_hash(externally_edited)


def test_collection_raw_and_analysis_have_stable_identity_and_source_access():
    from video_transcript_api.obsidian.knowledge_markdown import (
        parse_knowledge_markdown,
        render_analysis_knowledge_markdown,
        render_raw_knowledge_markdown,
    )

    item = KnowledgeItem(
        "u",
        "v",
        "标题",
        "原文",
        "AI",
        "local_file",
        "/tmp/source.mp4",
        "c",
        "s",
        "作者-合集",
    )
    raw = render_raw_knowledge_markdown(
        item,
        category="知识",
        relative_path="raw/知识/作者-合集/标题.md",
        synced_at="now",
    )
    analysis = render_analysis_knowledge_markdown(
        item,
        category="知识",
        raw_relative_path="raw/知识/作者-合集/标题.md",
        relative_path="processed/知识/作者-合集/标题.md",
        synced_at="now",
    )
    raw_fields, raw_body = parse_knowledge_markdown(raw)
    analysis_fields, analysis_body = parse_knowledge_markdown(analysis)
    assert raw_fields["learnflux_collection_id"] == "c"
    assert raw_fields["learnflux_source_id"] == "s"
    assert raw_fields["source_access"] == "/tmp/source.mp4"
    assert "## AI 解读" not in raw_body
    assert analysis_fields["raw_note"] == "[[raw/知识/作者-合集/标题]]"
    assert "## 原文 / 逐字稿" not in analysis_body
