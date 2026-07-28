import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from video_transcript_api.reading import parsers
from video_transcript_api.reading.parsers import ParsedChapter


def _render(source: str) -> str:
    assert hasattr(parsers, "pdf_text_to_html"), "PDF semantic reflow is not implemented"
    return parsers.pdf_text_to_html(source)


def test_pdf_text_to_html_merges_visual_wraps_into_semantic_paragraphs():
    source = (
        "第一段开头并没有结束，\n"
        "这一行只是 PDF 的视觉换行，\n"
        "直到这里才真正结束。\n"
        "第二段也会继续到\n"
        "自己的结束位置。"
    )

    rendered = _render(source)

    assert rendered.count("<p>") == 2
    assert "第一段开头并没有结束，这一行只是 PDF 的视觉换行，直到这里才真正结束。" in rendered
    assert "第二段也会继续到自己的结束位置。" in rendered


def test_pdf_text_to_html_keeps_numbered_items_together_as_a_list():
    source = (
        "关键结论如下：\n"
        "1. 第一项说明会在下一行\n"
        "继续完成。\n"
        "2. 第二项说明。\n"
        "3. 第三项说明。"
    )

    rendered = _render(source)

    assert rendered.count("<ol>") == 1
    assert rendered.count("<li>") == 3
    assert "第一项说明会在下一行继续完成。" in rendered


def test_pdf_text_to_html_ignores_isolated_reference_markers():
    rendered = _render("上一段结束。\n8\n9\n•\n下一段结束。")

    assert rendered == "<p>上一段结束。</p><p>下一段结束。</p>"


def test_pdf_text_to_html_promotes_first_page_title_lines():
    rendered = parsers.pdf_text_to_html(
        "Hermes Agent 深度研究报告\n执行摘要\n正文到这里结束。",
        promote_leading_headings=True,
    )

    assert rendered == (
        "<h1>Hermes Agent 深度研究报告</h1>"
        "<h2>执行摘要</h2>"
        "<p>正文到这里结束。</p>"
    )


def test_native_pdf_page_preserves_blocks_without_ocr_confidence():
    page = parsers.normalize_native_pdf_page(
        [
            (10, 20, 220, 50, "第一段原生文本\n", 0, 0),
            (10, 80, 220, 110, "第二段原生文本\n", 1, 0),
        ],
        source_page=0,
        page_size=(600, 800),
    )

    classified = parsers.classify_page_blocks(page)

    assert classified.extraction_mode == "native_text"
    assert [block.text for block in classified.body_blocks] == [
        "第一段原生文本",
        "第二段原生文本",
    ]
    assert parsers.score_page_quality(classified).status == "good"


def test_native_pdf_outline_uses_embedded_toc_page_targets():
    outline = parsers.build_native_pdf_outline(
        [(1, "第一章", 2), (2, "第一节", 3)], page_count=4
    )

    assert [(item.title, item.chapter_key, item.parent_key) for item in outline] == [
        ("第一章", "page-1", None),
        ("第一节", "page-2", "page-1"),
    ]


def test_local_ocr_render_scale_never_exceeds_detector_limit():
    scale = parsers.local_ocr_render_scale(2214, 3147.75)

    assert 1 < scale < 2
    assert max(2214 * scale, 3147.75 * scale) <= 3200


def test_local_ocr_runner_reads_one_page_result_from_an_external_process(tmp_path):
    image_path = tmp_path / "page.png"
    result_path = tmp_path / "page.json"
    image_path.write_bytes(b"png")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        result_path.write_text(json.dumps({"res": {"rec_texts": ["目录"]}}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    result = parsers.run_local_ocr_runner(image_path, result_path, runner=fake_run)

    assert result == {"rec_texts": ["目录"]}
    assert calls[0][0][:2] == [
        sys.executable,
        str(Path(parsers.__file__).with_name("ocr_runner.py")),
    ]
    assert calls[0][1]["check"] is False


def test_local_ocr_runner_failure_keeps_the_page_available_for_attention(tmp_path):
    image_path = tmp_path / "page.png"
    result_path = tmp_path / "page.json"
    image_path.write_bytes(b"png")

    result = parsers.run_local_ocr_runner(
        image_path,
        result_path,
        runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="runner failed"),
    )

    assert result == {}


def test_local_ocr_worker_count_scales_to_a_small_safe_process_pool():
    assert parsers.local_ocr_worker_count(1) == 1
    assert parsers.local_ocr_worker_count(2) == 2
    assert parsers.local_ocr_worker_count(441) == 2


def test_markdown_returns_hierarchical_outline_and_safe_embedded_image(tmp_path):
    png = b"\x89PNG\r\n\x1a\nimage"
    encoded = base64.b64encode(png).decode("ascii")
    source = tmp_path / "book.md"
    source.write_text(
        "# 第一章\n\n"
        "![结构图](data:image/png;base64," + encoded + ")\n\n"
        "## 第一节\n\n正文\n\n"
        "```text\n# 不是目录\n```",
        encoding="utf-8",
    )

    parsed = parsers.parse_reading_source(source, "markdown")

    assert [item.title for item in parsed.outline] == ["第一章", "第一节"]
    assert [item.level for item in parsed.outline] == [1, 2]
    assert parsed.outline[1].parent_key == parsed.outline[0].chapter_key
    assert len(parsed.assets) == 1
    assert parsed.assets[0].mime_type == "image/png"
    html = "".join(chapter.sanitized_html for chapter in parsed.chapters)
    assert f'data-reading-asset="{parsed.assets[0].safe_name}"' in html
    assert "data:image" not in html
    assert "不是目录" not in [item.title for item in parsed.outline]


def test_markdown_missing_or_invalid_image_degrades_to_placeholder(tmp_path):
    source = tmp_path / "book.md"
    source.write_text(
        "# Title\n\n![missing](./missing.png)\n\n"
        "![bad](data:image/png;base64,bm90LXBuZw==)",
        encoding="utf-8",
    )

    parsed = parsers.parse_reading_source(source, "markdown")

    assert parsed.assets == []
    html = "".join(chapter.sanitized_html for chapter in parsed.chapters)
    assert html.count("reading-image-placeholder") == 2


def test_pdf_markdown_formatting_never_leaks_into_plain_text():
    parsed = parsers._parse_markdown_text(
        "# 写在最后\n\n"
        "如果延迟为 **-1**：\n\n"
        "<mark>检查端口连通性</mark>\n\n"
        "<u><mark>先理解原理</mark></u>"
    )

    chapter = parsed.chapters[0]
    assert chapter.plain_text == (
        "如果延迟为 -1：\n检查端口连通性\n先理解原理"
    )
    assert "<mark>" not in chapter.plain_text
    assert "<u>" not in chapter.plain_text
    assert "**" not in chapter.plain_text


def test_scanned_pdf_catalog_builds_period_and_article_navigation():
    chapters = [
        ParsedChapter(
            "第 6 页",
            "目\n录\n第一次国内革命战争时期\n"
            "中国社会各阶级的分析（一九二六年三月）……3—11\n"
            "湖南农民运动考察报告（一九二七年三月）……12—44\n"
            "第二次国内革命战争时期\n"
            "中国的红色政权为什么能够存在？（一九二八年十月五日）……47—55",
            "",
            source_page=5,
            chapter_key="page-5",
        ),
        ParsedChapter(
            "第 10 页",
            "第一次国内革命战争时期",
            "",
            source_page=9,
            chapter_key="page-9",
        ),
        ParsedChapter(
            "第 12 页",
            "中国社会各阶级的分析\n（一九二六年三月）\n正文",
            "",
            source_page=11,
            chapter_key="page-11",
        ),
        ParsedChapter(
            "第 21 页",
            "湖南农民运动考察报告\n（一九二七年三月）\n正文",
            "",
            source_page=20,
            chapter_key="page-20",
        ),
        ParsedChapter(
            "第 56 页",
            "第二次国内革命战争时期",
            "",
            source_page=55,
            chapter_key="page-55",
        ),
        ParsedChapter(
            "第 57 页",
            "中国的红色政权为什么能够存在？\n正文",
            "",
            source_page=56,
            chapter_key="page-56",
        ),
    ]

    outline = parsers.build_scanned_pdf_outline(chapters)

    assert [(item.title, item.level, item.chapter_key, item.parent_key) for item in outline] == [
        ("第一次国内革命战争时期", 1, "page-9", None),
        ("中国社会各阶级的分析（一九二六年三月）", 2, "page-11", "page-9"),
        ("湖南农民运动考察报告（一九二七年三月）", 2, "page-20", "page-9"),
        ("第二次国内革命战争时期", 1, "page-55", None),
        ("中国的红色政权为什么能够存在？（一九二八年十月五日）", 2, "page-56", "page-55"),
    ]


def test_scanned_pdf_catalog_ignores_title_mentions_below_page_heading():
    chapters = [
        ParsedChapter(
            "第 8 页",
            "目\n录\n第二次国内革命战争时期\n"
            "论反对日本帝国主义的策略（一九三五年十二月）……128—153",
            "",
            source_page=7,
            chapter_key="page-7",
        ),
        ParsedChapter(
            "第 54 页",
            "54\n毛泽东选集 第二次国内革命战争时期\n正文第一行\n正文第二行\n"
            "正文第三行\n注释中提到《论反对日本帝国主义的策略》。",
            "",
            source_page=53,
            chapter_key="page-53",
        ),
        ParsedChapter(
            "第 137 页",
            "128\n论反对日本帝国主义的策略\n（一九三五年十二月二十七日）\n正文",
            "",
            source_page=136,
            chapter_key="page-136",
        ),
    ]

    outline = parsers.build_scanned_pdf_outline(chapters)

    assert [(item.title, item.chapter_key) for item in outline] == [
        ("论反对日本帝国主义的策略（一九三五年十二月）", "page-136")
    ]


def test_scanned_pdf_catalog_drops_truncated_publication_date():
    chapters = [
        ParsedChapter(
            "第 7 页",
            "目\n录\n第二次国内革命战争时期\n井冈山的斗争(一九二八年十一月",
            "",
            source_page=6,
            chapter_key="page-6",
        ),
        ParsedChapter(
            "第 65 页",
            "56\n井冈山的斗争\n（一九二八年十一月二十五日）\n正文",
            "",
            source_page=64,
            chapter_key="page-64",
        ),
    ]

    outline = parsers.build_scanned_pdf_outline(chapters)

    assert [(item.title, item.chapter_key) for item in outline] == [
        ("井冈山的斗争", "page-64")
    ]


def test_scanned_pdf_catalog_keeps_three_character_article_titles():
    chapters = [
        ParsedChapter(
            "第 9 页",
            "目\n录\n实践论(一九三七年七月)……259—273\n矛盾论(一九三七年八月)……274—312",
            "",
            source_page=8,
            chapter_key="page-8",
        ),
        ParsedChapter(
            "第 268 页",
            "259\n实践论\n（一九三七年七月）\n正文",
            "",
            source_page=267,
            chapter_key="page-267",
        ),
        ParsedChapter(
            "第 283 页",
            "274\n矛盾论\n（一九三七年八月）\n正文",
            "",
            source_page=282,
            chapter_key="page-282",
        ),
    ]

    outline = parsers.build_scanned_pdf_outline(chapters)

    assert [(item.title, item.chapter_key) for item in outline] == [
        ("实践论(一九三七年七月)", "page-267"),
        ("矛盾论(一九三七年八月)", "page-282"),
    ]


def test_scanned_pdf_catalog_joins_wrapped_article_title():
    chapters = [
        ParsedChapter(
            "第 9 页",
            "目\n录\n为争取千百万群众进入抗日民族统一战线\n"
            "而斗争(一九三七年五月七日）……249—258",
            "",
            source_page=8,
            chapter_key="page-8",
        ),
        ParsedChapter(
            "第 260 页",
            "249\n为争取千百万群众进入抗日民族统一战线而斗争\n"
            "（一九三七年五月七日）\n正文",
            "",
            source_page=259,
            chapter_key="page-259",
        ),
    ]

    outline = parsers.build_scanned_pdf_outline(chapters)

    assert [(item.title, item.chapter_key) for item in outline] == [
        ("为争取千百万群众进入抗日民族统一战线而斗争(一九三七年五月七日）", "page-259")
    ]


def test_scanned_pdf_catalog_can_start_after_front_matter_without_fixed_window():
    chapters = [
        ParsedChapter(
            "第 26 页",
            "目录\n第一章 导言…………30",
            "",
            source_page=25,
            chapter_key="page-25",
        ),
        ParsedChapter(
            "第 30 页",
            "第一章 导言\n正文",
            "",
            source_page=29,
            chapter_key="page-29",
        ),
    ]

    outline = parsers.build_scanned_pdf_outline(chapters)

    assert [(item.title, item.chapter_key) for item in outline] == [
        ("第一章 导言", "page-29")
    ]


def test_structured_page_orders_columns_before_moving_to_next_row():
    page = parsers.StructuredPage(
        source_page=0,
        width=1000,
        height=1000,
        extraction_mode="local_ocr",
        blocks=[
            parsers.OcrBlock("right first", (600, 100, 800, 130), 0.99),
            parsers.OcrBlock("left second", (100, 180, 300, 210), 0.99),
            parsers.OcrBlock("left first", (100, 100, 300, 130), 0.99),
            parsers.OcrBlock("right second", (600, 180, 800, 210), 0.99),
        ],
    )

    structured = parsers.classify_page_blocks(page)

    assert [block.text for block in structured.body_blocks] == [
        "left first",
        "left second",
        "right first",
        "right second",
    ]


def test_structured_page_keeps_bottom_small_text_out_of_body():
    page = parsers.StructuredPage(
        source_page=0,
        width=1000,
        height=1000,
        extraction_mode="local_ocr",
        blocks=[
            parsers.OcrBlock("正文内容。", (100, 200, 900, 250), 0.99),
            parsers.OcrBlock("1. 这是脚注", (100, 940, 360, 960), 0.99),
        ],
    )

    structured = parsers.classify_page_blocks(page)

    assert [block.text for block in structured.body_blocks] == ["正文内容。"]
    assert [block.text for block in structured.footnote_blocks] == ["1. 这是脚注"]


def test_document_layout_removes_repeated_running_header_from_body():
    pages = [
        parsers.StructuredPage(
            source_page=0,
            width=600,
            height=900,
            extraction_mode="local_ocr",
            blocks=[
                parsers.OcrBlock("书名", (50, 20, 120, 45), 0.99),
                parsers.OcrBlock("第一页正文", (50, 150, 500, 190), 0.99),
            ],
        ),
        parsers.StructuredPage(
            source_page=1,
            width=600,
            height=900,
            extraction_mode="local_ocr",
            blocks=[
                parsers.OcrBlock("书名", (50, 20, 120, 45), 0.99),
                parsers.OcrBlock("第二页正文", (50, 150, 500, 190), 0.99),
            ],
        ),
    ]

    classified = parsers.classify_document_pages(pages)

    assert [block.text for block in classified[0].body_blocks] == ["第一页正文"]
    assert [block.text for block in classified[1].body_blocks] == ["第二页正文"]


def test_structured_page_requires_coordinates_for_ocr_quality():
    page = parsers.StructuredPage(
        source_page=0,
        width=1000,
        height=1000,
        extraction_mode="local_ocr",
        blocks=[parsers.OcrBlock("缺少坐标", None, 0.99)],
    )

    assert parsers.score_page_quality(page).status == "attention"


def test_normalize_local_ocr_page_preserves_text_boxes_and_scores():
    raw_result = {
        "rec_texts": ["第一行", "第二行"],
        "rec_scores": [0.98, 0.91],
        "rec_polys": [
            [[10, 20], [110, 20], [110, 40], [10, 40]],
            [[10, 60], [110, 60], [110, 80], [10, 80]],
        ],
    }

    page = parsers.normalize_local_ocr_page(
        raw_result, source_page=3, page_size=(120, 100)
    )

    assert page.source_page == 3
    assert [(item.text, item.bbox, item.confidence) for item in page.blocks] == [
        ("第一行", (10.0, 20.0, 110.0, 40.0), 0.98),
        ("第二行", (10.0, 60.0, 110.0, 80.0), 0.91),
    ]
