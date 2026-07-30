from video_transcript_api.obsidian.knowledge_models import KnowledgeItem


def _item(collection_id="", source_id=""):
    return KnowledgeItem("u", "view", "标题", "原文\n---\n保留", "解读", "online_url", "https://example.com", collection_id, source_id, "合集")


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
