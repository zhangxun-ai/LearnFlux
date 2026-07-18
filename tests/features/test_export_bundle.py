from src.video_transcript_api.api.routes.views import (
    build_export_bundle_markdown,
    generate_download_filename,
    get_export_scope_sections,
)


def test_generate_download_filename_accepts_custom_extension():
    assert (
        generate_download_filename("深度学习入门", "bilibili", "analysis", "md")
        == "深度学习入门-AI解析-哔哩哔哩.md"
    )


def test_export_scope_sections_map_to_reading_order():
    assert get_export_scope_sections("analysis") == ("summary", "comment_insight")
    assert get_export_scope_sections("calibrated") == ("calibrated",)
    assert get_export_scope_sections("full") == (
        "summary",
        "comment_insight",
        "calibrated",
        "transcript",
    )
    assert get_export_scope_sections("unknown") == (
        "summary",
        "comment_insight",
        "calibrated",
        "transcript",
    )


def test_analysis_bundle_excludes_content_after_proofread_section(tmp_path):
    (tmp_path / "llm_summary.txt").write_text("# 内容总结\n\nAI 解析内容", encoding="utf-8")
    (tmp_path / "llm_calibrated.txt").write_text("校对文本内容", encoding="utf-8")
    (tmp_path / "transcript_capswriter.txt").write_text("原始转录内容", encoding="utf-8")

    markdown = build_export_bundle_markdown(
        {"title": "测试标题", "cache_dir": str(tmp_path)},
        "analysis",
    )

    assert "## 内容总结" in markdown
    assert "AI 解析内容" in markdown
    assert "校对文本内容" not in markdown
    assert "原始转录内容" not in markdown


def test_full_bundle_includes_sections_in_reading_order(tmp_path):
    (tmp_path / "llm_summary.txt").write_text("总结内容", encoding="utf-8")
    (tmp_path / "llm_calibrated.txt").write_text("校对文本内容", encoding="utf-8")
    (tmp_path / "transcript_capswriter.txt").write_text("原始转录内容", encoding="utf-8")

    markdown = build_export_bundle_markdown(
        {"title": "测试标题", "cache_dir": str(tmp_path)},
        "full",
    )

    section_positions = [
        markdown.find("## 内容总结"),
        markdown.find("## 校对文本"),
        markdown.find("## 原始转录"),
    ]
    assert all(position >= 0 for position in section_positions)
    assert section_positions == sorted(section_positions)
