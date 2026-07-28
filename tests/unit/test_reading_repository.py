"""Owner isolation and persistence tests for the flow reading repository."""

from __future__ import annotations

import json
import sqlite3

import pytest
from pydantic import ValidationError

from video_transcript_api.reading.repository import (
    ReadingDataError,
    ReadingRepository,
)
from video_transcript_api.reading.schemas import ReadingLocator, ReadingRangeLocator


def _document(repository: ReadingRepository, owner: str, suffix: str = ""):
    return repository.create_document(
        owner_user_id=owner,
        title=f"Book {suffix}",
        author="Author",
        format="pdf",
        source_path=f"private/{owner}/{suffix or 'book'}.pdf",
        file_sha256=f"hash-{suffix or 'shared'}",
        file_size=123,
        status="processing",
    )


def _locator(chapter_id: str = "chapter-1") -> ReadingLocator:
    return ReadingLocator(
        chapter_id=chapter_id,
        block_id="block-1",
        block_offset=3,
        source_page=0,
        epub_cfi="",
    )


def _range_locator(chapter_id: str = "chapter-1") -> ReadingRangeLocator:
    return ReadingRangeLocator(
        chapter_id=chapter_id,
        block_id="block-1",
        block_offset=3,
        start_offset=3,
        end_offset=8,
        quote_prefix="before",
        quote="quote",
        quote_suffix="after",
        source_page=0,
        epub_cfi="",
    )


@pytest.fixture
def repository(tmp_path):
    repo = ReadingRepository(tmp_path / "reading.db")
    yield repo
    repo.close()


def test_schema_creation_is_idempotent_and_has_required_indexes(tmp_path):
    db_path = tmp_path / "reading.db"
    first = ReadingRepository(db_path)
    first.close()
    second = ReadingRepository(db_path)
    second.close()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert {
        "reading_documents",
        "reading_chapters",
        "reading_progress",
        "reading_preferences",
        "reading_annotations",
        "focus_materials",
        "reading_deletion_jobs",
    } <= tables
    assert {
        "idx_reading_chapters_document_position",
        "idx_reading_annotations_owner_document_updated",
        "idx_focus_materials_owner_consumed_created",
    } <= indexes


def test_document_hash_is_unique_per_owner(repository):
    first = _document(repository, "owner-a")

    with pytest.raises(sqlite3.IntegrityError):
        _document(repository, "owner-a")

    other = _document(repository, "owner-b")
    assert first.file_sha256 == other.file_sha256
    assert first.id != other.id


def test_document_crud_is_owner_scoped(repository):
    document = _document(repository, "owner-a")

    assert repository.get_document("owner-b", document.id) is None
    assert repository.update_document(
        "owner-b", document.id, title="Stolen"
    ) is None
    assert repository.delete_document("owner-b", document.id) is False
    assert repository.list_documents("owner-b") == []

    updated = repository.update_document(
        "owner-a", document.id, title="Updated", status="ready"
    )
    assert updated is not None
    assert updated.title == "Updated"
    assert updated.status == "ready"
    assert repository.delete_document("owner-a", document.id) is True
    assert repository.get_document("owner-a", document.id) is None


def test_document_delete_job_is_atomic_and_removes_linked_material(repository):
    document = _document(repository, "owner-a", "delete-job")
    material = repository.create_material(
        "owner-a",
        source_type="reading",
        source_id=document.id,
        source_title=document.title,
        quote="quoted",
        note=None,
        locator=None,
    )

    job = repository.delete_document_with_job(
        "owner-a",
        document.id,
        source_path="/managed/source.pdf",
        asset_dir="/managed/assets",
    )

    assert job is not None
    assert repository.get_document("owner-a", document.id) is None
    assert repository.get_material("owner-a", material.id) is None
    assert repository.list_deletion_jobs() == [job]
    assert repository.complete_deletion_job(job["id"]) is True
    assert repository.list_deletion_jobs() == []


def test_chapter_crud_is_owner_scoped_through_document(repository):
    document = _document(repository, "owner-a")
    chapter = repository.create_chapter(
        "owner-a",
        document.id,
        position=0,
        title="One",
        source_locator=_locator(),
        plain_text="Chapter text",
        sanitized_html="<p>Chapter text</p>",
    )

    assert repository.get_chapter("owner-b", chapter.id) is None
    assert repository.list_chapters("owner-b", document.id) == []
    assert repository.update_chapter(
        "owner-b", chapter.id, title="Stolen"
    ) is None
    assert repository.delete_chapter("owner-b", chapter.id) is False

    updated = repository.update_chapter(
        "owner-a", chapter.id, title="Updated"
    )
    assert updated is not None and updated.title == "Updated"
    assert repository.delete_chapter("owner-a", chapter.id) is True
    assert repository.get_chapter("owner-a", chapter.id) is None


def test_progress_and_preferences_crud_are_owner_scoped(repository):
    document = _document(repository, "owner-a")
    progress = repository.upsert_progress(
        "owner-a", document.id, mode="immersive", locator=_locator(), percent=0.5
    )
    preferences = repository.upsert_preferences(
        "owner-a",
        theme="dark",
        font_family="serif",
        font_size=18,
        layout="wide",
        sound_track="rain",
        sound_volume=0.4,
    )

    assert progress.locator.source_page == 0
    assert preferences.theme == "dark"
    assert repository.get_progress("owner-b", document.id) is None
    assert repository.delete_progress("owner-b", document.id) is False
    assert repository.get_preferences("owner-b") is None
    assert repository.delete_preferences("owner-b") is False

    assert repository.delete_progress("owner-a", document.id) is True
    assert repository.delete_preferences("owner-a") is True


def test_annotation_crud_is_owner_scoped(repository):
    document = _document(repository, "owner-a")
    annotation = repository.create_annotation(
        "owner-a",
        document.id,
        kind="highlight",
        locator=_range_locator(),
        quote="quote",
        note_body="note",
        color="yellow",
    )

    assert repository.get_annotation("owner-b", annotation.id) is None
    assert repository.list_annotations("owner-b", document.id) == []
    assert repository.update_annotation(
        "owner-b", annotation.id, note_body="Stolen"
    ) is None
    assert repository.delete_annotation("owner-b", annotation.id) is False

    updated = repository.update_annotation(
        "owner-a", annotation.id, note_body="Updated"
    )
    assert updated is not None and updated.note_body == "Updated"
    assert repository.delete_annotation("owner-a", annotation.id) is True


def test_focus_material_crud_is_owner_scoped(repository):
    document = _document(repository, "owner-a")
    material = repository.create_material(
        "owner-a",
        source_type="reading_document",
        source_id=document.id,
        source_title=document.title,
        quote="quote",
        note="note",
        locator=_range_locator(),
    )

    assert repository.get_material("owner-b", material.id) is None
    assert repository.list_materials("owner-b") == []
    assert repository.update_material(
        "owner-b", material.id, note="Stolen"
    ) is None
    assert repository.delete_material("owner-b", material.id) is False

    updated = repository.update_material(
        "owner-a", material.id, note="Updated", consumed=True
    )
    assert updated is not None and updated.note == "Updated"
    assert updated.consumed_at is not None
    assert repository.delete_material("owner-a", material.id) is True


def test_deleting_document_cascades_reading_data_but_preserves_material(repository):
    document = _document(repository, "owner-a")
    chapter = repository.create_chapter(
        "owner-a",
        document.id,
        position=0,
        title="One",
        source_locator=_locator(),
        plain_text="text",
        sanitized_html="<p>text</p>",
    )
    repository.upsert_progress(
        "owner-a", document.id, mode="immersive", locator=_locator(), percent=0.2
    )
    annotation = repository.create_annotation(
        "owner-a",
        document.id,
        kind="note",
        locator=_range_locator(),
        quote="quote",
        note_body="note",
        color="blue",
    )
    material = repository.create_material(
        "owner-a",
        source_type="reading_document",
        source_id=document.id,
        source_title=document.title,
        quote="quote",
        note="note",
        locator=_range_locator(),
    )

    assert repository.delete_document("owner-a", document.id) is True
    assert repository.get_chapter("owner-a", chapter.id) is None
    assert repository.get_progress("owner-a", document.id) is None
    assert repository.get_annotation("owner-a", annotation.id) is None
    preserved = repository.get_material("owner-a", material.id)
    assert preserved is not None
    assert preserved.source_id is None


def test_locator_validation_uses_zero_based_pages_and_bounded_quotes():
    assert _locator().source_page == 0
    with pytest.raises(ValidationError):
        ReadingLocator(
            chapter_id="c", block_id="b", block_offset=-1, source_page=0
        )
    with pytest.raises(ValidationError):
        ReadingLocator(
            chapter_id="c", block_id="b", block_offset=0, source_page=-1
        )
    with pytest.raises(ValidationError):
        ReadingRangeLocator(
            chapter_id="c",
            block_id="b",
            block_offset=0,
            start_offset=5,
            end_offset=4,
            quote="quote",
        )
    with pytest.raises(ValidationError):
        ReadingRangeLocator(
            chapter_id="c",
            block_id="b",
            block_offset=0,
            start_offset=0,
            end_offset=1,
            quote="",
        )
    with pytest.raises(ValidationError):
        ReadingRangeLocator(
            chapter_id="c",
            block_id="b",
            block_offset=0,
            start_offset=0,
            end_offset=1,
            quote_prefix="x" * 33,
            quote="q",
        )


def test_corrupt_locator_json_raises_only_for_own_row(repository):
    own = _document(repository, "owner-a", "own")
    other = _document(repository, "owner-b", "other")
    repository.upsert_progress(
        "owner-a", own.id, mode="immersive", locator=_locator(), percent=0.1
    )
    repository.upsert_progress(
        "owner-b", other.id, mode="immersive", locator=_locator(), percent=0.2
    )

    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE reading_progress SET locator_json = ? WHERE owner_user_id = ?",
            ("{broken", "owner-b"),
        )

    assert repository.get_progress("owner-a", own.id) is not None
    assert repository.get_progress("owner-a", other.id) is None
    with pytest.raises(ReadingDataError, match="invalid locator JSON"):
        repository.get_progress("owner-b", other.id)


def test_oversized_locator_is_rejected(repository):
    document = _document(repository, "owner-a")
    oversized = ReadingLocator(
        chapter_id="c",
        block_id="b" * 70_000,
        block_offset=0,
    )

    with pytest.raises(ValueError, match="locator JSON is too large"):
        repository.upsert_progress(
            "owner-a",
            document.id,
            mode="immersive",
            locator=oversized,
            percent=0.1,
        )


def test_document_status_is_validated_before_any_write(repository):
    with pytest.raises(ReadingDataError, match="invalid reading status"):
        repository.create_document(
            owner_user_id="owner-a",
            title="Invalid",
            author="Author",
            format="pdf",
            source_path="private/owner-a/invalid.pdf",
            file_sha256="invalid-hash",
            file_size=123,
            status="invalid",
        )

    assert repository.list_documents("owner-a") == []

    document = _document(repository, "owner-a")
    with pytest.raises(ReadingDataError, match="invalid reading status"):
        repository.update_document("owner-a", document.id, status="invalid")

    unchanged = repository.get_document("owner-a", document.id)
    assert unchanged is not None and unchanged.status == "processing"


def test_locator_input_and_stored_data_bounds_are_safe(repository):
    with pytest.raises(ValidationError):
        ReadingRangeLocator(
            chapter_id="c",
            block_id="b",
            block_offset=0,
            start_offset=0,
            end_offset=1,
            quote="x" * 10_001,
        )

    document = _document(repository, "owner-a")
    repository.upsert_progress(
        "owner-a", document.id, mode="immersive", locator=_locator(), percent=0.1
    )
    oversized_json = json.dumps(
        {"chapter_id": "c", "block_id": "x" * 70_000, "block_offset": 0}
    )
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE reading_progress SET locator_json = ? WHERE owner_user_id = ?",
            (oversized_json, "owner-a"),
        )

    with pytest.raises(ReadingDataError, match="invalid locator JSON"):
        repository.get_progress("owner-a", document.id)

    sensitive_json = '{"secret":"TOP_SECRET_LOCATOR_DATA"'
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE reading_progress SET locator_json = ? WHERE owner_user_id = ?",
            (sensitive_json, "owner-a"),
        )

    with pytest.raises(ReadingDataError) as error:
        repository.get_progress("owner-a", document.id)
    assert "TOP_SECRET_LOCATOR_DATA" not in str(error.value)
    assert "TOP_SECRET_LOCATOR_DATA" not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_chapter_parent_must_belong_to_same_owner_and_document(repository):
    document = _document(repository, "owner-a", "one")
    other_document = _document(repository, "owner-a", "two")
    foreign_document = _document(repository, "owner-b", "foreign")
    other_parent = repository.create_chapter(
        "owner-a",
        other_document.id,
        position=0,
        title="Other parent",
        source_locator=_locator(),
        plain_text="other",
        sanitized_html="<p>other</p>",
    )
    foreign_parent = repository.create_chapter(
        "owner-b",
        foreign_document.id,
        position=0,
        title="Foreign parent",
        source_locator=_locator(),
        plain_text="foreign",
        sanitized_html="<p>foreign</p>",
    )

    for invalid_parent_id in (other_parent.id, foreign_parent.id):
        with pytest.raises(ReadingDataError, match="invalid parent chapter"):
            repository.create_chapter(
                "owner-a",
                document.id,
                position=1,
                title="Invalid child",
                source_locator=_locator(),
                plain_text="child",
                sanitized_html="<p>child</p>",
                parent_id=invalid_parent_id,
            )
    assert repository.list_chapters("owner-a", document.id) == []

    parent = repository.create_chapter(
        "owner-a",
        document.id,
        position=0,
        title="Parent",
        source_locator=_locator(),
        plain_text="parent",
        sanitized_html="<p>parent</p>",
    )
    child = repository.create_chapter(
        "owner-a",
        document.id,
        position=1,
        title="Child",
        source_locator=_locator(),
        plain_text="child",
        sanitized_html="<p>child</p>",
        parent_id=parent.id,
    )

    for invalid_parent_id in (other_parent.id, foreign_parent.id):
        with pytest.raises(ReadingDataError, match="invalid parent chapter"):
            repository.update_chapter(
                "owner-a", child.id, parent_id=invalid_parent_id
            )
        unchanged = repository.get_chapter("owner-a", child.id)
        assert unchanged is not None and unchanged.parent_id == parent.id

    assert repository.delete_chapter("owner-b", foreign_parent.id) is True
    unaffected = repository.get_chapter("owner-a", child.id)
    assert unaffected is not None and unaffected.parent_id == parent.id


def test_annotation_kind_is_validated_before_any_write(repository):
    document = _document(repository, "owner-a")
    with pytest.raises(ReadingDataError, match="invalid annotation kind"):
        repository.create_annotation(
            "owner-a",
            document.id,
            kind="invalid",
            locator=_range_locator(),
            quote="quote",
            note_body="note",
            color="yellow",
        )
    assert repository.list_annotations("owner-a", document.id) == []

    annotation = repository.create_annotation(
        "owner-a",
        document.id,
        kind="highlight",
        locator=_range_locator(),
        quote="quote",
        note_body="note",
        color="yellow",
    )
    with pytest.raises(ReadingDataError, match="invalid annotation kind"):
        repository.update_annotation("owner-a", annotation.id, kind="invalid")
    unchanged = repository.get_annotation("owner-a", annotation.id)
    assert unchanged is not None and unchanged.kind == "highlight"


def test_invalid_stored_model_does_not_leak_sensitive_fields(repository):
    document = _document(repository, "owner-a")
    chapter = repository.create_chapter(
        "owner-a",
        document.id,
        position=0,
        title="Chapter",
        source_locator=_locator(),
        plain_text="ordinary",
        sanitized_html="<p>ordinary</p>",
    )
    sensitive_text = "TOP_SECRET_STORED_CHAPTER_TEXT"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE reading_chapters SET position = ?, plain_text = ? WHERE id = ?",
            ("invalid-position", sensitive_text, chapter.id),
        )

    with pytest.raises(ReadingDataError) as error:
        repository.get_chapter("owner-a", chapter.id)
    assert sensitive_text not in str(error.value)
    assert sensitive_text not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_legacy_database_is_upgraded_and_keeps_legacy_chapters(tmp_path):
    db_path = tmp_path / "legacy-reading.db"
    document_id = "legacy-document"
    chapter_id = "legacy-chapter"
    locator = json.dumps(
        {
            "chapter_id": "",
            "block_id": "chapter-0",
            "block_offset": 0,
            "source_page": 0,
            "epub_cfi": "",
        }
    )
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE reading_documents (
                id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, title TEXT NOT NULL,
                author TEXT, format TEXT NOT NULL, source_path TEXT NOT NULL,
                file_sha256 TEXT NOT NULL, file_size INTEGER NOT NULL, status TEXT NOT NULL,
                parse_error TEXT, cover_path TEXT, outline_json TEXT,
                parse_generation INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_opened_at TEXT,
                UNIQUE(owner_user_id, file_sha256)
            );
            CREATE TABLE reading_chapters (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, position INTEGER NOT NULL,
                parent_id TEXT, title TEXT NOT NULL, source_locator_json TEXT NOT NULL,
                plain_text TEXT NOT NULL, sanitized_html TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """INSERT INTO reading_documents VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                "reader",
                "Legacy",
                None,
                "pdf",
                "/managed/legacy.pdf",
                "legacy-hash",
                1,
                "ready",
                None,
                None,
                "[]",
                0,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                None,
            ),
        )
        connection.execute(
            """INSERT INTO reading_chapters VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chapter_id,
                document_id,
                0,
                None,
                "Legacy chapter",
                locator,
                "legacy body",
                "<p>legacy body</p>",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    repository = ReadingRepository(db_path)
    try:
        document = repository.get_document("reader", document_id)
        assert document is not None
        assert document.active_parse_run_id is None
        assert document.parse_quality == "good"
        assert document.parse_warning_count == 0
        assert [item.id for item in repository.list_chapters("reader", document_id)] == [
            chapter_id
        ]
    finally:
        repository.close()


def test_active_parse_run_hides_legacy_chapters_without_deleting_them(repository):
    document = _document(repository, "owner-a", "generation")
    legacy = repository.create_chapter(
        "owner-a",
        document.id,
        position=0,
        title="Legacy",
        source_locator=_locator(),
        plain_text="legacy",
        sanitized_html="<p>legacy</p>",
    )
    run = repository.create_parse_run(
        "owner-a",
        document.id,
        parser_version="structured-v1",
        status="completed",
    )
    structured = repository.create_chapter(
        "owner-a",
        document.id,
        position=0,
        title="Structured",
        source_locator=_locator(),
        plain_text="structured",
        sanitized_html="<p>structured</p>",
        parse_run_id=run.id,
    )

    updated = repository.activate_parse_run(
        "owner-a",
        document.id,
        run.id,
        outline_json="[]",
        parse_quality="warning",
        parse_warning_count=1,
    )

    assert updated is not None
    assert updated.active_parse_run_id == run.id
    assert updated.parse_quality == "warning"
    assert [item.id for item in repository.list_chapters("owner-a", document.id)] == [
        structured.id
    ]
    assert repository.get_chapter("owner-a", legacy.id) is not None


def test_parse_run_prevents_parallel_work_and_keeps_one_page_snapshot(repository):
    document = _document(repository, "owner-a", "run-pages")
    run = repository.create_parse_run(
        "owner-a", document.id, parser_version="structured-v1"
    )
    with pytest.raises(ReadingDataError, match="parse run already active"):
        repository.create_parse_run(
            "owner-a", document.id, parser_version="structured-v1"
        )

    analysis = repository.record_page_analysis(
        "owner-a",
        run.id,
        source_page=0,
        retry_profile="standard",
        extraction_mode="local_ocr",
        quality_status="good",
        quality_score=0.99,
        issue_codes=[],
    )
    repository.snapshot_run_page("owner-a", run.id, 0, analysis.id)
    with pytest.raises(ReadingDataError, match="page snapshot already exists"):
        repository.snapshot_run_page("owner-a", run.id, 0, analysis.id)

    assert repository.list_run_pages("owner-a", run.id) == [(0, analysis.id)]


def test_page_analysis_persists_structured_blocks(repository):
    document = _document(repository, "owner-a", "blocks")
    run = repository.create_parse_run(
        "owner-a", document.id, parser_version="structured-v1"
    )
    analysis = repository.record_page_analysis(
        "owner-a",
        run.id,
        source_page=0,
        retry_profile="standard",
        extraction_mode="local_ocr",
        quality_status="good",
        quality_score=0.99,
        issue_codes=[],
    )

    repository.record_page_blocks(
        "owner-a",
        analysis.id,
        [
            {
                "text": "正文",
                "bbox": [10, 20, 100, 40],
                "confidence": 0.98,
                "kind": "body",
                "reading_order": 0,
            }
        ],
    )

    assert repository.list_page_blocks("owner-a", analysis.id) == [
        {
            "text": "正文",
            "bbox": [10, 20, 100, 40],
            "confidence": 0.98,
            "kind": "body",
            "reading_order": 0,
        }
    ]
