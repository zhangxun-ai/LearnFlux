import pytest


def test_canonicalize_document_text_without_exposing_text_in_evidence():
    from video_transcript_api.study.document_quality import (
        assess_document_text,
        canonicalize_document_text,
    )

    raw = "\ufeff标题\r\n正文\r下一行"

    canonical = canonicalize_document_text(raw)
    result = assess_document_text(raw)

    assert raw.startswith("\ufeff")
    assert canonical == "标题\n正文\n下一行"
    assert set(result.to_evidence()) == {"mode", "reasons", "metrics"}
    assert "canonical_text" not in result.to_evidence()


def test_quality_metrics_use_exact_unicode_character_rules():
    from video_transcript_api.study.document_quality import assess_document_text

    result = assess_document_text("中文 A1，。\n\t\x00�")
    metrics = result.metrics

    assert metrics.total_chars == 11
    assert metrics.valid_chars == 6
    assert metrics.printable_ratio == pytest.approx(10 / 11)
    assert metrics.replacement_char_ratio == pytest.approx(1 / 11)
    assert metrics.control_char_ratio == pytest.approx(1 / 11)
    assert metrics.wordish_ratio == pytest.approx(6 / 8)


def test_duplicate_line_ratio_uses_repeated_occurrences_after_first():
    from video_transcript_api.study.document_quality import assess_document_text

    result = assess_document_text(
        "Title\nPage 1\nBody text\nPage 1\nPage 1"
    )

    assert result.metrics.duplicate_line_ratio == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("有效内容" * 49, "too_short"),
        (("有效内容" * 70) + ("\x00" * 20), "low_printable_ratio"),
        (("有效内容" * 70) + "�", "replacement_char_ratio"),
        (("有效内容" * 70) + "\x00", "control_char_ratio"),
        (("A " * 210) + ("♜" * 150), "low_wordish_ratio"),
        (
            "\n".join(["Page header"] * 5 + [f"正文段落 {index}" for index in range(5)]),
            "duplicate_lines",
        ),
    ],
)
def test_fallback_reasons_are_stable_codes(text, reason):
    from video_transcript_api.study.document_quality import assess_document_text

    result = assess_document_text(text)

    assert result.mode == "fallback"
    assert reason in result.reasons


def test_clean_document_uses_fast_mode():
    from video_transcript_api.study.document_quality import assess_document_text

    result = assess_document_text(
        "\n".join(f"第 {index} 节：这是结构清晰的正文内容。" for index in range(40))
    )

    assert result.mode == "fast"
    assert result.reasons == ()


def test_evidence_payload_size_does_not_grow_with_document_length():
    from video_transcript_api.study.document_quality import assess_document_text

    short = assess_document_text("干净正文。" * 100).to_evidence()
    long = assess_document_text("干净正文。" * 10000).to_evidence()

    assert len(repr(long)) <= len(repr(short)) + 100
    assert "干净正文" not in repr(long)
