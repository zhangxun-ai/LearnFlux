import pytest


def _metadata(**overrides):
    values = {
        "view_token": "view-1",
        "collection_id": "course-1",
        "source_id": "lesson-1",
        "course": "高效学习",
        "lesson": "第01课：核心概念",
        "synced_at": "2026-07-17T12:00:00+08:00",
    }
    values.update(overrides)
    return values


def test_managed_identity_uses_collection_source_or_single_view_token():
    from video_transcript_api.obsidian.markdown import managed_identity

    assert managed_identity("transcript", view_token="view-1") == {
        "type": "transcript",
        "source": "LearnFlux",
        "vta_view_token": "view-1",
    }
    assert managed_identity(
        "study-note",
        view_token="retry-view",
        collection_id="course-1",
        source_id="lesson-1",
    ) == {
        "type": "study-note",
        "source": "LearnFlux",
        "vta_collection_id": "course-1",
        "vta_source_id": "lesson-1",
    }


def _transcript_body(lines):
    from video_transcript_api.obsidian.markdown import (
        parse_markdown_document,
        render_transcript_markdown,
    )

    return parse_markdown_document(
        render_transcript_markdown(_metadata(), lines)
    ).body


def _transcript_paragraphs(lines):
    body = _transcript_body(lines)
    return body.split("## 文字稿\n\n", 1)[1].split("\n\n")


def test_render_transcript_groups_fragments_with_one_paragraph_timestamp():
    from video_transcript_api.obsidian.markdown import render_transcript_markdown

    content = render_transcript_markdown(
        _metadata(),
        [
            {"start_seconds": 2, "seekable": True, "text": "第一段"},
            {"start_seconds": 65.8, "seekable": True, "text": "第二段"},
            {"seekable": False, "text": "无时间戳内容"},
        ],
    )

    assert "type: transcript" in content
    assert "vta_collection_id: course-1" in content
    assert "# 第01课：核心概念" in content
    assert "## 文字稿" in content
    assert "**00:02** 第一段，第二段，无时间戳内容。" in content
    assert "**01:05**" not in content
    assert "\n[00:02]" not in content


def test_render_transcript_breaks_at_natural_sentence_after_180_chars():
    paragraphs = _transcript_paragraphs(
        [
            {"start_seconds": 0, "seekable": True, "text": f"{'甲' * 179}。"},
            {"start_seconds": 30, "seekable": True, "text": "下一段"},
        ]
    )

    assert len(paragraphs) == 2
    assert paragraphs[0] == f"**00:00** {'甲' * 179}。"
    assert paragraphs[1] == "**00:30** 下一段。"


def test_render_transcript_uses_target_and_hard_length_boundaries():
    target_paragraphs = _transcript_paragraphs(
        [
            {"start_seconds": 0, "seekable": True, "text": "甲" * 259},
            {"start_seconds": 10, "seekable": True, "text": "乙"},
            {"start_seconds": 20, "seekable": True, "text": "下一段"},
        ]
    )
    hard_limit_paragraphs = _transcript_paragraphs(
        [
            {"start_seconds": 0, "seekable": True, "text": "甲" * 100},
            {"start_seconds": 10, "seekable": True, "text": "乙" * 221},
        ]
    )

    assert len(target_paragraphs) == 2
    assert target_paragraphs[0].startswith("**00:00** ")
    assert target_paragraphs[1] == "**00:20** 下一段。"
    assert len(hard_limit_paragraphs) == 2
    assert hard_limit_paragraphs[0] == f"**00:00** {'甲' * 100}。"
    assert hard_limit_paragraphs[1] == f"**00:10** {'乙' * 221}。"


def test_render_transcript_breaks_on_reliable_silence_gap():
    paragraphs = _transcript_paragraphs(
        [
            {
                "start_seconds": 0,
                "end_seconds": 10,
                "seekable": True,
                "text": "甲" * 80,
            },
            {
                "start_seconds": 18,
                "end_seconds": 24,
                "seekable": True,
                "text": "乙",
            },
        ]
    )

    assert paragraphs == [
        f"**00:00** {'甲' * 80}。",
        "**00:18** 乙。",
    ]


def test_render_transcript_isolates_single_overlong_fragment_after_short_text():
    paragraphs = _transcript_paragraphs(
        [
            {"start_seconds": 0, "seekable": True, "text": "短" * 79},
            {"start_seconds": 5, "seekable": True, "text": "长" * 321},
            {"start_seconds": 50, "seekable": True, "text": "结尾"},
        ]
    )

    assert len(paragraphs) == 3
    assert paragraphs[0] == f"**00:00** {'短' * 79}。"
    assert paragraphs[1] == f"**00:05** {'长' * 321}。"
    assert paragraphs[2] == "**00:50** 结尾。"


def test_render_transcript_handles_ascii_period_hour_timestamp_and_no_timestamp():
    timed = _transcript_paragraphs(
        [
            {"start_seconds": 3661, "seekable": True, "text": "Hello."},
            {"start_seconds": 3662, "seekable": True, "text": "下一句"},
        ]
    )
    untimed = _transcript_paragraphs(
        [
            {"seekable": False, "text": "没有时间"},
            {"text": "仍然可读"},
        ]
    )

    assert timed == ["**01:01:01** Hello.下一句。"]
    assert untimed == ["没有时间，仍然可读。"]


def test_render_single_transcript_omits_collection_fields():
    from video_transcript_api.obsidian.markdown import render_transcript_markdown

    content = render_transcript_markdown(
        _metadata(collection_id="", source_id=""),
        [{"text": "正文", "seekable": False}],
    )

    assert "vta_view_token: view-1" in content
    assert "vta_collection_id" not in content
    assert "vta_source_id" not in content


def test_note_rendering_preserves_user_frontmatter_and_replaces_managed_fields():
    from video_transcript_api.obsidian.markdown import (
        parse_markdown_document,
        render_note_markdown,
    )

    existing = """---
type: study-note
source: LearnFlux
vta_collection_id: course-1
vta_source_id: lesson-1
lesson: 旧标题
synced_at: old
tags:
  - learning
aliases:
  - 课程重点
custom_field: keep-me
---

旧正文
"""
    rendered = render_note_markdown(_metadata(), "新正文\n\n- 条目", existing_content=existing)
    document = parse_markdown_document(rendered)

    assert document.frontmatter["lesson"] == "第01课：核心概念"
    assert document.frontmatter["synced_at"] == "2026-07-17T12:00:00+08:00"
    assert document.frontmatter["tags"] == ["learning"]
    assert document.frontmatter["aliases"] == ["课程重点"]
    assert document.frontmatter["custom_field"] == "keep-me"
    assert document.body == "新正文\n\n- 条目"


def test_empty_note_body_keeps_frontmatter_without_old_body():
    from video_transcript_api.obsidian.markdown import (
        extract_note_body,
        render_note_markdown,
    )

    rendered = render_note_markdown(_metadata(), "", existing_content=None)

    assert rendered.startswith("---\n")
    assert rendered.endswith("---\n")
    assert extract_note_body(rendered) == ""


def test_malformed_frontmatter_is_rejected_instead_of_rewritten():
    from video_transcript_api.obsidian.markdown import (
        MarkdownFormatError,
        parse_markdown_document,
        render_note_markdown,
    )

    malformed = "---\ntags: [broken\n---\nbody"
    with pytest.raises(MarkdownFormatError):
        parse_markdown_document(malformed)
    with pytest.raises(MarkdownFormatError):
        render_note_markdown(_metadata(), "new", existing_content=malformed)


def test_managed_hash_excludes_synced_at_and_custom_frontmatter():
    from video_transcript_api.obsidian.markdown import managed_markdown_hash

    first = """---
type: study-note
source: LearnFlux
vta_collection_id: course-1
vta_source_id: lesson-1
lesson: Lesson
synced_at: first
tags: [one]
---

body
"""
    second = first.replace("synced_at: first", "synced_at: second").replace(
        "tags: [one]", "tags: [two]"
    )
    changed = second.replace("lesson: Lesson", "lesson: Changed")

    assert managed_markdown_hash(first) == managed_markdown_hash(second)
    assert managed_markdown_hash(first) != managed_markdown_hash(changed)


def test_body_hash_normalizes_line_endings_but_not_content():
    from video_transcript_api.obsidian.markdown import note_body_hash

    assert note_body_hash("one\r\ntwo") == note_body_hash("one\ntwo")
    assert note_body_hash("") != note_body_hash(" ")
