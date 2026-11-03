"""Source coverage and real-position regressions for image-diagram inputs."""

from copy import deepcopy

import pytest

from video_transcript_api.image_diagrams.source import (
    select_source, snapshot_session, source_sections,
)


def session(lines):
    return {
        "metadata": {"title": "Full source"},
        "transcript": {"lines": lines},
        "ai": {"overview": "Existing interpretation, secondary to source"},
    }


def test_long_unsegmented_source_is_complete_and_exactly_addressable():
    text = "0123456789" * 6500 + "FINAL_END_MARKER"
    source = snapshot_session(session([
        {"id": "original-line-7", "text": text, "start_seconds": 12.5},
    ]))
    paragraphs = source["paragraphs"]
    assert len(paragraphs) > 30
    assert source["coverage"] == "full"
    assert source["source_chars"] == len(text)
    assert "".join(row["text"] for row in paragraphs) == text
    assert paragraphs[-1]["text"].endswith("FINAL_END_MARKER")
    assert [row["id"] for row in paragraphs] == [f"P{i}" for i in range(1, len(paragraphs) + 1)]
    for row in paragraphs:
        assert row["text"] == text[row["char_start"]:row["char_end"]]
        assert row["char_end"] - row["char_start"] == len(row["text"])
        assert row["line_id"] == "original-line-7"
        assert row["paragraph_index"] == 0
        assert row["start_seconds"] == 12.5
    refs = [ref for group in source["sections"] for ref in group["source_ref_ids"]]
    assert refs == [row["id"] for row in paragraphs]
    assert len(refs) == len(set(refs))


def test_empty_rows_do_not_shift_original_paragraph_or_line_identity():
    source = snapshot_session(session([
        {"id": "blank-1", "text": ""},
        {"id": "first", "text": "First real paragraph", "start_seconds": 2},
        {"id": "blank-2", "text": "   "},
        {"text": "Second real paragraph", "start_seconds": 5},
    ]))
    first, second = source["paragraphs"]
    assert (first["id"], first["paragraph_index"], first["line_id"]) == ("P1", 1, "first")
    assert (second["id"], second["paragraph_index"], second["line_id"]) == ("P2", 3, "line-4")


def test_trimmed_whitespace_keeps_offsets_in_original_line():
    raw = "   " + "x" * 4100 + "  "
    source = snapshot_session(session([{"id": "padded", "text": raw}]))
    for row in source["paragraphs"]:
        assert raw[row["char_start"]:row["char_end"]] == row["text"]
    assert source["paragraphs"][0]["char_start"] == 3
    assert source["paragraphs"][-1]["char_end"] == len(raw) - 2


def test_sections_cover_all_positions_and_heading_starts_new_section():
    paragraphs = [
        {"id": "P1", "text": "A" * 1600, "start_seconds": 0},
        {"id": "P2", "text": "## Next chapter", "start_seconds": 10},
        {"id": "P3", "text": "B" * 1600, "start_seconds": 11},
        {"id": "P4", "text": "### Last chapter", "start_seconds": 20},
    ]
    sections = source_sections(paragraphs)
    assert [row["source_ref_ids"] for row in sections] == [["P1"], ["P2", "P3"], ["P4"]]
    assert [row["start_seconds"] for row in sections] == [0, 10, 20]
    assert "Next chapter" in sections[1]["title"]


def test_select_section_uses_only_that_section_and_keeps_original_positions():
    source = snapshot_session(session([
        {"id": f"line-{i}", "text": str(i) * 2100, "start_seconds": i * 30}
        for i in range(12)
    ]))
    original = deepcopy(source)
    section = source["sections"][1]
    selected = select_source(source, {"scope": "section", "section_id": section["id"]})
    expected = [row for row in source["paragraphs"] if row["id"] in section["source_ref_ids"]]
    assert selected["paragraphs"] == expected
    assert selected["sections"] == [section]
    assert selected["coverage"] == "selected_section"
    assert selected["source_chars"] == sum(len(row["text"]) for row in expected)
    assert selected["source_hash"] == source["source_hash"]
    assert selected["whole_source_context"] == [
        {"id": row["id"], "title": row["title"]} for row in source["sections"]
    ]
    assert source == original
    assert select_source(source, {"scope": "overview"}) == source
    with pytest.raises(ValueError, match="invalid_section"):
        select_source(source, {"scope": "section", "section_id": "nonexistent"})


def test_source_hash_changes_when_tail_of_full_text_changes():
    original = session([{"id": "long-line", "text": "a" * 70000 + "original tail"}])
    altered = deepcopy(original)
    altered["transcript"]["lines"][0]["text"] = "a" * 70000 + "modified tail"
    assert snapshot_session(original)["source_hash"] != snapshot_session(altered)["source_hash"]
    assert snapshot_session(original)["source_hash"] == snapshot_session(original)["source_hash"]


def test_summary_cannot_substitute_for_missing_original_text():
    with pytest.raises(ValueError, match="source_not_ready"):
        snapshot_session(session([]))


def test_document_visual_limitations_are_disclosed():
    document = session([{"text": "Readable document body"}])
    document["source"] = {"kind": "document"}
    assert snapshot_session(document)["visual_limitations"]
