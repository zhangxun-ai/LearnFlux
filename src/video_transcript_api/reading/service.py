"""Application service for the first usable reading flow."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from .assets import (
    ReadingAssetError,
    document_asset_dir,
    resolve_document_asset,
    validate_document_asset_dir,
    write_document_assets,
)
from .parsers import (
    LocalOcrUnavailable,
    ParsedChapter,
    ParsedDocument,
    build_scanned_pdf_outline,
    classify_page_blocks,
    parse_pdf_native_structure,
    parse_pdf_with_local_ocr,
    parse_reading_source,
    pdf_text_to_html,
    score_page_quality,
)
from .repository import ReadingDataError, ReadingRepository
from .schemas import ReadingLocator, ReadingRangeLocator
from .source_files import (
    ReadingSourceError,
    delete_reading_source,
    inspect_upload,
    save_staged_upload,
    stage_upload,
    validate_reading_source_path,
)


class ReadingService:
    def __init__(self, *, db_path: str | Path, source_root: str | Path) -> None:
        self.repository = ReadingRepository(db_path)
        self.source_root = Path(source_root)

    def close(self) -> None:
        self.repository.close()

    def list_documents(self, owner_user_id: str):
        return self.repository.list_documents(owner_user_id)

    def get_document_detail(self, owner_user_id: str, document_id: str) -> dict | None:
        document = self.repository.get_document(owner_user_id, document_id)
        if document is None:
            return None
        chapters = self.repository.list_chapters(owner_user_id, document_id)
        if document.format == "pdf":
            chapters = [self._reflow_scanned_pdf_chapter(item) for item in chapters]
        progress = self.repository.get_progress(owner_user_id, document_id)
        return {
            "document": document,
            "chapters": chapters,
            "progress": progress,
        }

    @staticmethod
    def _reflow_scanned_pdf_chapter(chapter):
        if (
            not re.fullmatch(r"第\s*\d+\s*页", chapter.title)
            or "data-reading-asset" in chapter.sanitized_html
        ):
            return chapter
        return chapter.model_copy(
            update={"sanitized_html": pdf_text_to_html(chapter.plain_text)}
        )

    def import_document(
        self,
        owner_user_id: str,
        *,
        filename: str,
        stream: BinaryIO,
    ):
        staging_dir = self.source_root / ".reading-staging"
        staged = stage_upload(stream, staging_dir=staging_dir)
        inspected = inspect_upload(staged, filename)

        for existing in self.repository.list_documents(owner_user_id):
            if existing.file_sha256 == inspected.sha256 and Path(existing.source_path).is_file():
                inspected.temp_path.unlink(missing_ok=True)
                return existing

        title = Path(filename).stem.strip()[:200] or "未命名文档"
        document = self.repository.create_document(
            owner_user_id=owner_user_id,
            title=title,
            author=None,
            format=inspected.format,
            source_path="",
            file_sha256=inspected.sha256,
            file_size=inspected.size_bytes,
            status="processing",
        )
        try:
            source_path = save_staged_upload(
                inspected,
                data_root=self.source_root,
                owner_user_id=owner_user_id,
                document_id=document.id,
            )
            self.repository.update_document(
                owner_user_id, document.id, source_path=str(source_path)
            )
            if inspected.format == "pdf":
                parsed = parse_pdf_native_structure(source_path)
                if parsed.pages:
                    return self._save_structured_pdf_document(
                        owner_user_id, document.id, source_path, parsed
                    )
                return self.repository.update_document(
                    owner_user_id,
                    document.id,
                    status="needs_ocr",
                    parse_error="no_readable_native_text",
                )
            parsed = parse_reading_source(source_path, inspected.format)
            if not parsed.chapters:
                return self.repository.update_document(
                    owner_user_id,
                    document.id,
                    source_path=str(source_path),
                    status="needs_ocr" if inspected.format == "pdf" else "failed",
                    parse_error="no_readable_text",
                )
            return self._save_parsed_document(
                owner_user_id, document.id, source_path, parsed
            )
        except (OSError, ValueError, ReadingDataError, ReadingSourceError):
            current = self.repository.get_document(owner_user_id, document.id)
            if current is not None:
                self.repository.update_document(
                    owner_user_id,
                    document.id,
                    status="failed",
                    parse_error="parse_failed",
                )
            raise

    def start_local_ocr(self, owner_user_id: str, document_id: str):
        document = self.repository.get_document(owner_user_id, document_id)
        if (
            document is None
            or document.format != "pdf"
            or document.status != "needs_ocr"
        ):
            return document
        return self.repository.update_document(
            owner_user_id,
            document_id,
            status="processing",
            parse_error=None,
        )

    def ocr_document(self, owner_user_id: str, document_id: str):
        document = self.repository.get_document(owner_user_id, document_id)
        if document is None or document.format != "pdf":
            return document
        if document.status != "processing":
            return document
        try:
            source_path = validate_reading_source_path(
                document.source_path, data_root=self.source_root
            )
            parsed = parse_pdf_with_local_ocr(source_path)
            if not parsed.chapters:
                return self.repository.update_document(
                    owner_user_id,
                    document_id,
                    status="needs_ocr",
                    parse_error="ocr_no_readable_text",
                )
            if parsed.pages:
                return self._save_structured_pdf_document(
                    owner_user_id, document_id, source_path, parsed
                )
            return self._save_parsed_document(
                owner_user_id, document_id, source_path, parsed
            )
        except LocalOcrUnavailable:
            return self.repository.update_document(
                owner_user_id,
                document_id,
                status="needs_ocr",
                parse_error="local_ocr_unavailable",
            )
        except (OSError, ValueError, ReadingSourceError):
            return self.repository.update_document(
                owner_user_id,
                document_id,
                status="failed",
                parse_error="ocr_failed",
            )

    def reprocess_document(self, owner_user_id: str, document_id: str):
        """Create a structured PDF generation without replacing active content on error."""
        run = self.start_reprocess_document(owner_user_id, document_id)
        if run is None:
            return self.repository.get_document(owner_user_id, document_id)
        return self.complete_reprocess_document(owner_user_id, document_id, run.id)

    def start_reprocess_document(self, owner_user_id: str, document_id: str):
        """Reserve a versioned PDF reprocess run before scheduling long OCR work."""
        document = self.repository.get_document(owner_user_id, document_id)
        if document is None or document.format != "pdf" or document.status != "ready":
            return None
        try:
            validate_reading_source_path(
                document.source_path, data_root=self.source_root
            )
        except ReadingSourceError:
            return None
        return self.repository.create_parse_run(
            owner_user_id,
            document_id,
            parser_version="structured-v1",
            parent_run_id=document.active_parse_run_id,
        )

    def complete_reprocess_document(
        self, owner_user_id: str, document_id: str, run_id: str
    ):
        """Run a reserved reprocess, leaving active content unchanged on failure."""
        document = self.repository.get_document(owner_user_id, document_id)
        run = self.repository.get_parse_run(owner_user_id, run_id)
        if (
            document is None
            or run is None
            or run.document_id != document_id
            or run.status != "running"
        ):
            return document
        try:
            source_path = validate_reading_source_path(
                document.source_path, data_root=self.source_root
            )
        except ReadingSourceError:
            self.repository.update_parse_run_status(owner_user_id, run.id, "failed")
            return document
        try:
            parsed = parse_pdf_with_local_ocr(source_path)
            if not parsed.chapters or not parsed.pages:
                raise ReadingDataError("structured parse produced no readable pages")
            return self._save_structured_pdf_document(
                owner_user_id,
                document_id,
                source_path,
                parsed,
                run=run,
            )
        except (LocalOcrUnavailable, OSError, ValueError, ReadingSourceError):
            self.repository.update_parse_run_status(owner_user_id, run.id, "failed")
            return document

    def recover_interrupted_ocr(self, *, older_than: datetime | None = None) -> int:
        return self.repository.recover_interrupted_pdf_ocr(older_than=older_than)

    def rebuild_scanned_pdf_outline(self, owner_user_id: str, document_id: str):
        document = self.repository.get_document(owner_user_id, document_id)
        if document is None or document.format != "pdf":
            return document
        stored_chapters = self.repository.list_chapters(owner_user_id, document_id)
        parsed_chapters = [
            ParsedChapter(
                chapter.title,
                chapter.plain_text,
                chapter.sanitized_html,
                source_page=chapter.source_locator.source_page,
                chapter_key=f"page-{chapter.source_locator.source_page}",
            )
            for chapter in stored_chapters
            if chapter.source_locator.source_page is not None
        ]
        outline = build_scanned_pdf_outline(parsed_chapters)
        chapter_ids = {
            f"page-{chapter.source_locator.source_page}": chapter.id
            for chapter in stored_chapters
            if chapter.source_locator.source_page is not None
        }
        return self.repository.update_document(
            owner_user_id,
            document_id,
            outline_json=json.dumps(
                self._outline_values(outline, chapter_ids), ensure_ascii=False
            ),
        )

    @staticmethod
    def _outline_values(outline_items, chapter_ids: dict[str, str]):
        outline: list[dict[str, str | int | None]] = []
        for item in outline_items:
            chapter_id = chapter_ids.get(item.chapter_key)
            if chapter_id:
                outline.append(
                    {
                        "id": chapter_id,
                        "title": item.title,
                        "position": len(outline),
                        "level": item.level,
                        "parent_id": chapter_ids.get(item.parent_key or ""),
                        "source_page": item.source_page,
                        "epub_cfi": item.epub_cfi,
                    }
                )
        return outline

    def _save_parsed_document(
        self,
        owner_user_id: str,
        document_id: str,
        source_path: Path,
        parsed: ParsedDocument,
    ):
        write_document_assets(
            self.source_root,
            owner_user_id,
            document_id,
            parsed.assets,
        )
        outline_json, _ = self._create_parsed_chapters(
            owner_user_id, document_id, parsed
        )
        return self.repository.update_document(
            owner_user_id,
            document_id,
            source_path=str(source_path),
            status="ready",
            parse_error=None,
            outline_json=outline_json,
        )

    def _create_parsed_chapters(
        self,
        owner_user_id: str,
        document_id: str,
        parsed: ParsedDocument,
        *,
        parse_run_id: str | None = None,
    ) -> tuple[str, list]:
        chapter_ids: dict[str, str] = {}
        created_chapters = []
        for position, chapter in enumerate(parsed.chapters):
            parent_id = chapter_ids.get(chapter.parent_key or "")
            block_id = f"chapter-{position}"
            if parse_run_id is not None:
                source_page = chapter.source_page if chapter.source_page is not None else -1
                block_id = (
                    f"run:{parse_run_id}:page:{source_page}:block:{position}"
                )
            created = self.repository.create_chapter(
                owner_user_id,
                document_id,
                position=position,
                title=chapter.title,
                source_locator=ReadingLocator(
                    chapter_id="",
                    block_id=block_id,
                    block_offset=0,
                    source_page=chapter.source_page,
                    epub_cfi=chapter.epub_cfi,
                ),
                plain_text=chapter.plain_text,
                sanitized_html=chapter.sanitized_html,
                parent_id=parent_id,
                parse_run_id=parse_run_id,
            )
            chapter_ids[chapter.chapter_key] = created.id
            created_chapters.append(created)
        outline = self._outline_values(parsed.outline, chapter_ids)
        return json.dumps(outline, ensure_ascii=False), created_chapters

    def _save_structured_pdf_document(
        self,
        owner_user_id: str,
        document_id: str,
        source_path: Path,
        parsed: ParsedDocument,
        *,
        run=None,
    ):
        run = run or self.repository.create_parse_run(
            owner_user_id, document_id, parser_version="structured-v1"
        )
        try:
            warning_count = 0
            has_attention = False
            for page in parsed.pages:
                structured = classify_page_blocks(page)
                quality = score_page_quality(structured)
                if quality.status != "good":
                    warning_count += 1
                has_attention = has_attention or quality.status == "attention"
                analysis = self.repository.record_page_analysis(
                    owner_user_id,
                    run.id,
                    source_page=structured.source_page,
                    retry_profile="standard",
                    extraction_mode=structured.extraction_mode,
                    quality_status=quality.status,
                    quality_score=quality.score,
                    issue_codes=list(quality.reasons),
                )
                blocks = [
                    {
                        "text": block.text,
                        "bbox": list(block.bbox) if block.bbox is not None else None,
                        "confidence": block.confidence,
                        "kind": "body",
                        "reading_order": index,
                    }
                    for index, block in enumerate(structured.body_blocks)
                ]
                body_block_count = len(blocks)
                blocks.extend(
                    {
                        "text": block.text,
                        "bbox": list(block.bbox) if block.bbox is not None else None,
                        "confidence": block.confidence,
                        "kind": "footnote",
                        "reading_order": body_block_count + index,
                    }
                    for index, block in enumerate(structured.footnote_blocks)
                )
                self.repository.record_page_blocks(owner_user_id, analysis.id, blocks)
                self.repository.snapshot_run_page(
                    owner_user_id, run.id, structured.source_page, analysis.id
                )
            write_document_assets(
                self.source_root, owner_user_id, document_id, parsed.assets
            )
            outline_json, created_chapters = self._create_parsed_chapters(
                owner_user_id, document_id, parsed, parse_run_id=run.id
            )
            self.repository.update_parse_run_status(
                owner_user_id, run.id, "completed"
            )
            progress_locator, resolutions = self._resolve_active_locators(
                owner_user_id,
                document_id,
                run.id,
                parsed,
                created_chapters,
            )
            return self.repository.activate_parse_run(
                owner_user_id,
                document_id,
                run.id,
                outline_json=outline_json,
                parse_quality="attention" if has_attention else (
                    "warning" if warning_count else "good"
                ),
                parse_warning_count=warning_count,
                progress_locator=progress_locator,
                locator_resolutions=resolutions,
            )
        except (ReadingDataError, ValueError):
            self.repository.update_parse_run_status(owner_user_id, run.id, "failed")
            raise

    def _resolve_active_locators(
        self,
        owner_user_id: str,
        document_id: str,
        run_id: str,
        parsed: ParsedDocument,
        created_chapters: list,
    ) -> tuple[ReadingLocator | None, list[dict]]:
        chapters_by_page = {
            chapter.source_locator.source_page: chapter
            for chapter in created_chapters
            if chapter.source_locator.source_page is not None
        }
        page_text = {
            page.source_page: "\n".join(
                block.text for block in classify_page_blocks(page).body_blocks
            )
            for page in parsed.pages
        }
        resolutions: list[dict] = []

        def chapter_locator(locator: ReadingLocator) -> ReadingLocator | None:
            if locator.source_page is None:
                return None
            chapter = chapters_by_page.get(locator.source_page)
            if chapter is None:
                return None
            return ReadingLocator(
                chapter_id=chapter.id,
                block_id=chapter.source_locator.block_id,
                block_offset=0,
                source_page=locator.source_page,
                epub_cfi="",
            )

        progress_locator = None
        progress = self.repository.get_progress(owner_user_id, document_id)
        if progress is not None:
            progress_locator = chapter_locator(progress.locator)
            resolutions.append(
                {
                    "target_type": "progress",
                    "old_locator": progress.locator,
                    "resolved_locator": progress_locator,
                    "status": "resolved" if progress_locator else "unresolved",
                    "reason": "same_source_page"
                    if progress_locator
                    else "source_page_not_available",
                }
            )

        for annotation in self.repository.list_annotations(owner_user_id, document_id):
            locator = annotation.locator
            target = chapter_locator(locator)
            text = page_text.get(locator.source_page)
            if target is not None and text is not None:
                matches = self._unique_quote_matches(text, locator)
                if len(matches) == 1:
                    target = ReadingRangeLocator(
                        **target.model_dump(),
                        start_offset=matches[0],
                        end_offset=matches[0] + len(locator.quote),
                        quote_prefix=locator.quote_prefix,
                        quote=locator.quote,
                        quote_suffix=locator.quote_suffix,
                    )
                else:
                    target = None
            else:
                target = None
            resolutions.append(
                {
                    "target_type": "annotation",
                    "old_locator": locator,
                    "resolved_locator": target,
                    "status": "resolved" if target else "unresolved",
                    "reason": "unique_quote_match"
                    if target
                    else "quote_not_unique_or_source_page_not_available",
                }
            )
        return progress_locator, resolutions

    @staticmethod
    def _unique_quote_matches(text: str, locator: ReadingRangeLocator) -> list[int]:
        matches: list[int] = []
        start = 0
        while True:
            index = text.find(locator.quote, start)
            if index < 0:
                return matches
            before = text[:index]
            after = text[index + len(locator.quote) :]
            if (
                (not locator.quote_prefix or before.endswith(locator.quote_prefix))
                and (not locator.quote_suffix or after.startswith(locator.quote_suffix))
            ):
                matches.append(index)
            start = index + len(locator.quote)

    def save_progress(
        self,
        owner_user_id: str,
        document_id: str,
        *,
        chapter_id: str,
        percent: float,
    ):
        chapter = self.repository.get_chapter(owner_user_id, chapter_id)
        if chapter is None or chapter.document_id != document_id:
            raise ReadingDataError("chapter not found")
        return self.repository.upsert_progress(
            owner_user_id,
            document_id,
            mode="immersive",
            locator=ReadingLocator(
                chapter_id=chapter.id,
                block_id=chapter.source_locator.block_id,
                block_offset=0,
                source_page=chapter.source_locator.source_page,
            ),
            percent=max(0.0, min(100.0, percent)),
        )

    def get_preferences(self, owner_user_id: str):
        return self.repository.get_preferences(owner_user_id)

    def save_preferences(self, owner_user_id: str, **values):
        return self.repository.upsert_preferences(owner_user_id, **values)

    def get_document_asset(
        self, owner_user_id: str, document_id: str, asset_name: str
    ) -> tuple[Path, str] | None:
        if self.repository.get_document(owner_user_id, document_id) is None:
            return None
        return resolve_document_asset(
            self.source_root, owner_user_id, document_id, asset_name
        )

    def get_document_source(
        self, owner_user_id: str, document_id: str
    ) -> tuple[Path, str] | None:
        document = self.repository.get_document(owner_user_id, document_id)
        if document is None or document.format != "pdf" or not document.source_path:
            return None
        try:
            source = validate_reading_source_path(
                document.source_path, data_root=self.source_root
            )
        except ReadingSourceError:
            return None
        if not source.is_file():
            return None
        return source, "application/pdf"

    def delete_document(self, owner_user_id: str, document_id: str) -> bool:
        document = self.repository.get_document(owner_user_id, document_id)
        if document is None:
            return False
        if not document.source_path:
            raise ReadingSourceError("unmanaged_source_path")
        source_path = validate_reading_source_path(
            document.source_path, data_root=self.source_root
        )
        asset_dir = document_asset_dir(
            self.source_root, owner_user_id, document_id
        )
        validate_document_asset_dir(asset_dir, data_root=self.source_root)
        job = self.repository.delete_document_with_job(
            owner_user_id,
            document_id,
            source_path=str(source_path),
            asset_dir=str(asset_dir),
        )
        if job is None:
            return False
        self._run_deletion_job(job)
        return True

    def _run_deletion_job(self, job: dict[str, str]) -> bool:
        try:
            delete_reading_source(job["source_path"], data_root=self.source_root)
            asset_dir = validate_document_asset_dir(
                job["asset_dir"], data_root=self.source_root
            )
            if asset_dir.exists():
                # Resolve the opaque owner directory directly for recovery jobs.
                if asset_dir.is_symlink() or not asset_dir.is_dir():
                    raise ReadingAssetError("unmanaged_asset_path")
                import shutil

                shutil.rmtree(asset_dir)
            self.repository.complete_deletion_job(job["id"])
            return True
        except (OSError, ReadingSourceError, ReadingAssetError):
            return False

    def recover_deletion_jobs(self) -> int:
        completed = 0
        for job in self.repository.list_deletion_jobs():
            completed += int(self._run_deletion_job(job))
        return completed
