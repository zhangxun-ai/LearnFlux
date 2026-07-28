from io import BytesIO
import json
from pathlib import Path

from video_transcript_api.reading.service import ReadingService
from video_transcript_api.reading.schemas import ReadingLocator, ReadingRangeLocator
from video_transcript_api.reading.assets import ParsedAsset, write_document_assets
from video_transcript_api.reading.parsers import (
    OcrBlock,
    ParsedChapter,
    ParsedDocument,
    StructuredPage,
)
from video_transcript_api.reading import service as reading_service
from video_transcript_api.reading.source_files import reading_source_path


def test_markdown_import_opens_chapters_and_saves_progress(tmp_path):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    try:
        document = service.import_document(
            "reader-1",
            filename="notes.md",
            stream=BytesIO("# 第一章\n\n正文 A\n\n## 第二章\n\n正文 B".encode()),
        )
        assert document.status == "ready"

        detail = service.get_document_detail("reader-1", document.id)
        assert detail is not None
        assert [chapter.title for chapter in detail["chapters"]] == ["第一章", "第二章"]

        progress = service.save_progress(
            "reader-1",
            document.id,
            chapter_id=detail["chapters"][1].id,
            percent=100,
        )
        assert progress.locator.chapter_id == detail["chapters"][1].id
        assert service.get_document_detail("reader-2", document.id) is None
    finally:
        service.close()


def test_existing_pdf_chapters_are_reflowed_when_opened(tmp_path):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    try:
        document = service.repository.create_document(
            owner_user_id="reader-1",
            title="report",
            author=None,
            format="pdf",
            source_path="/managed/report.pdf",
            file_sha256="a" * 64,
            file_size=100,
            status="ready",
        )
        service.repository.create_chapter(
            "reader-1",
            document.id,
            position=0,
            title="第 1 页",
            source_locator=ReadingLocator(
                chapter_id="",
                block_id="chapter-0",
                block_offset=0,
                source_page=0,
            ),
            plain_text="第一行还没有结束，\n第二行才真正结束。",
            sanitized_html="<p>第一行还没有结束，</p><p>第二行才真正结束。</p>",
        )

        detail = service.get_document_detail("reader-1", document.id)

        assert detail is not None
        assert detail["chapters"][0].sanitized_html == (
            "<p>第一行还没有结束，第二行才真正结束。</p>"
        )
    finally:
        service.close()


def test_remove_then_reimport_same_file_parses_as_new_document(tmp_path):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    payload = b"# Title\n\nBody"
    try:
        first = service.import_document(
            "reader-1", filename="notes.md", stream=BytesIO(payload)
        )
        asset = ParsedAsset.from_bytes(
            b"\x89PNG\r\n\x1a\nimage", "image/png"
        )
        write_document_assets(
            service.source_root, "reader-1", first.id, [asset]
        )
        source_path = Path(first.source_path)

        assert service.delete_document("reader-1", first.id) is True
        assert service.repository.get_document("reader-1", first.id) is None
        assert not source_path.exists()
        assert not list((service.source_root / "reading-assets").rglob(asset.safe_name))

        second = service.import_document(
            "reader-1", filename="notes.md", stream=BytesIO(payload)
        )
        assert second.id != first.id
        assert second.status == "ready"
    finally:
        service.close()


def test_scanned_pdf_can_be_completed_by_local_ocr(tmp_path, monkeypatch):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    empty = ParsedDocument(chapters=[], outline=[], assets=[])
    ocr_result = ParsedDocument(
        chapters=[
            ParsedChapter(
                title="第 1 页",
                plain_text="这是 OCR 识别出的正文。",
                sanitized_html="<p>这是 OCR 识别出的正文。</p>",
                source_page=0,
            )
        ],
        outline=[],
        assets=[],
        pages=[
            StructuredPage(
                source_page=0,
                width=1000,
                height=1400,
                extraction_mode="local_ocr",
                blocks=[OcrBlock("这是 OCR 识别出的正文。", (10, 20, 400, 60), 0.99)],
            )
        ],
    )
    monkeypatch.setattr(reading_service, "parse_reading_source", lambda *_: empty)
    monkeypatch.setattr(
        reading_service,
        "parse_pdf_native_structure",
        lambda *_: empty,
    )
    ocr_calls = 0

    def parse_ocr_once(*_):
        nonlocal ocr_calls
        ocr_calls += 1
        return ocr_result

    monkeypatch.setattr(
        reading_service,
        "parse_pdf_with_local_ocr",
        parse_ocr_once,
        raising=False,
    )
    try:
        document = service.import_document(
            "reader-1",
            filename="scanned.pdf",
            stream=BytesIO(b"%PDF-1.7\nscanned"),
        )
        assert document.status == "needs_ocr"

        processing = service.start_local_ocr("reader-1", document.id)
        assert processing is not None and processing.status == "processing"

        ready = service.ocr_document("reader-1", document.id)
        assert ready is not None and ready.status == "ready"
        assert ocr_calls == 1
        detail = service.get_document_detail("reader-1", document.id)
        assert detail is not None
        assert [chapter.plain_text for chapter in detail["chapters"]] == [
            "这是 OCR 识别出的正文。"
        ]
        assert ready.active_parse_run_id is not None
        assert service.repository.list_run_pages(
            "reader-1", ready.active_parse_run_id
        )
    finally:
        service.close()


def test_native_pdf_import_creates_structured_generation_without_ocr(
    tmp_path, monkeypatch
):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    native_result = ParsedDocument(
        chapters=[
            ParsedChapter(
                title="第 1 页",
                plain_text="这是原生 PDF 正文。",
                sanitized_html="<p>这是原生 PDF 正文。</p>",
                source_page=0,
            )
        ],
        outline=[],
        assets=[],
        pages=[
            StructuredPage(
                source_page=0,
                width=600,
                height=800,
                extraction_mode="native_text",
                blocks=[OcrBlock("这是原生 PDF 正文。", (10, 20, 300, 50), None)],
            )
        ],
    )
    monkeypatch.setattr(
        reading_service,
        "parse_pdf_native_structure",
        lambda *_: native_result,
    )
    monkeypatch.setattr(
        reading_service,
        "parse_pdf_with_local_ocr",
        lambda *_: (_ for _ in ()).throw(AssertionError("OCR must not run")),
    )
    try:
        document = service.import_document(
            "reader-1",
            filename="native.pdf",
            stream=BytesIO(b"%PDF-1.7\nnative"),
        )

        assert document.status == "ready"
        assert document.active_parse_run_id is not None
        assert document.parse_quality == "good"
    finally:
        service.close()


def test_reprocess_pdf_switches_generation_and_relocates_user_state(
    tmp_path, monkeypatch
):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    structured_result = ParsedDocument(
        chapters=[
            ParsedChapter(
                title="新目录标题",
                plain_text="这是可定位的新版正文。",
                sanitized_html="<p>这是可定位的新版正文。</p>",
                source_page=1,
            )
        ],
        outline=[],
        assets=[],
        pages=[
            StructuredPage(
                source_page=1,
                width=1000,
                height=1400,
                extraction_mode="local_ocr",
                blocks=[
                    OcrBlock(
                        "这是可定位的新版正文。", (10, 20, 500, 80), 0.99
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        reading_service,
        "parse_pdf_with_local_ocr",
        lambda *_: structured_result,
    )
    try:
        document = service.repository.create_document(
            owner_user_id="reader-1",
            title="scanned",
            author=None,
            format="pdf",
            source_path="",
            file_sha256="d" * 64,
            file_size=100,
            status="ready",
        )
        source_path = reading_source_path(
            service.source_root, "reader-1", document.id, ".pdf"
        )
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(b"%PDF-1.7\nscanned")
        service.repository.update_document(
            "reader-1", document.id, source_path=str(source_path)
        )
        legacy = service.repository.create_chapter(
            "reader-1",
            document.id,
            position=0,
            title="第 2 页",
            source_locator=ReadingLocator(
                chapter_id="", block_id="chapter-0", block_offset=0, source_page=1
            ),
            plain_text="这是可定位的旧版正文。",
            sanitized_html="<p>这是可定位的旧版正文。</p>",
        )
        service.save_progress("reader-1", document.id, chapter_id=legacy.id, percent=40)
        annotation = service.repository.create_annotation(
            "reader-1",
            document.id,
            kind="highlight",
            locator=ReadingRangeLocator(
                chapter_id=legacy.id,
                block_id="chapter-0",
                block_offset=0,
                start_offset=2,
                end_offset=5,
                quote="可定位",
                source_page=1,
            ),
            quote="可定位",
            note_body=None,
            color="yellow",
        )

        updated = service.reprocess_document("reader-1", document.id)

        assert updated is not None and updated.active_parse_run_id is not None
        detail = service.get_document_detail("reader-1", document.id)
        assert detail is not None
        assert [chapter.title for chapter in detail["chapters"]] == ["新目录标题"]
        assert service.repository.get_chapter("reader-1", legacy.id) is not None
        progress = service.repository.get_progress("reader-1", document.id)
        assert progress is not None
        assert progress.locator.chapter_id == detail["chapters"][0].id
        assert progress.locator.source_page == 1
        assert service.repository.get_annotation("reader-1", annotation.id) == annotation
        resolutions = service.repository.list_locator_resolutions(
            "reader-1", document.id, updated.active_parse_run_id
        )
        assert {(item["target_type"], item["status"]) for item in resolutions} == {
            ("progress", "resolved"),
            ("annotation", "resolved"),
        }
    finally:
        service.close()


def test_interrupted_local_ocr_is_made_retryable_on_recovery(tmp_path):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    try:
        document = service.repository.create_document(
            owner_user_id="reader-1",
            title="scanned",
            author=None,
            format="pdf",
            source_path="/managed/scanned.pdf",
            file_sha256="b" * 64,
            file_size=100,
            status="processing",
        )

        assert service.recover_interrupted_ocr() == 1
        recovered = service.repository.get_document("reader-1", document.id)
        assert recovered is not None
        assert recovered.status == "needs_ocr"
        assert recovered.parse_error == "ocr_interrupted"
    finally:
        service.close()


def test_rebuild_scanned_pdf_outline_updates_existing_document(tmp_path):
    service = ReadingService(
        db_path=tmp_path / "reading.db",
        source_root=tmp_path / "sources",
    )
    try:
        document = service.repository.create_document(
            owner_user_id="reader-1",
            title="scanned",
            author=None,
            format="pdf",
            source_path="/managed/scanned.pdf",
            file_sha256="c" * 64,
            file_size=100,
            status="ready",
        )
        catalog = service.repository.create_chapter(
            "reader-1",
            document.id,
            position=0,
            title="第 6 页",
            source_locator=ReadingLocator(
                chapter_id="", block_id="chapter-0", block_offset=0, source_page=5
            ),
            plain_text=(
                "目\n录\n第一次国内革命战争时期\n"
                "中国社会各阶级的分析（一九二六年三月）……3—11"
            ),
            sanitized_html="",
        )
        period = service.repository.create_chapter(
            "reader-1",
            document.id,
            position=1,
            title="第 10 页",
            source_locator=ReadingLocator(
                chapter_id="", block_id="chapter-1", block_offset=0, source_page=9
            ),
            plain_text="第一次国内革命战争时期",
            sanitized_html="",
        )
        article = service.repository.create_chapter(
            "reader-1",
            document.id,
            position=2,
            title="第 12 页",
            source_locator=ReadingLocator(
                chapter_id="", block_id="chapter-2", block_offset=0, source_page=11
            ),
            plain_text="中国社会各阶级的分析\n（一九二六年三月）\n正文",
            sanitized_html="",
        )

        updated = service.rebuild_scanned_pdf_outline("reader-1", document.id)

        assert updated is not None
        outline = json.loads(updated.outline_json or "[]")
        assert [(item["title"], item["id"], item["parent_id"]) for item in outline] == [
            ("第一次国内革命战争时期", period.id, None),
            ("中国社会各阶级的分析（一九二六年三月）", article.id, period.id),
        ]
        assert catalog.id not in {item["id"] for item in outline}
    finally:
        service.close()
