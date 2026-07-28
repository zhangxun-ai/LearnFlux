"""Validated data contracts for reading persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ReadingStatus = Literal["processing", "ready", "needs_ocr", "failed"]
ParseQuality = Literal["good", "warning", "attention"]
ParseRunStatus = Literal["running", "completed", "failed", "cancelled"]
VALID_READING_STATUSES = frozenset({"processing", "ready", "needs_ocr", "failed"})
VALID_ANNOTATION_KINDS = frozenset({"bookmark", "highlight", "note"})


class ReadingLocator(BaseModel):
    """A stable position in a parsed reading document."""

    chapter_id: str
    block_id: str
    block_offset: int = Field(ge=0)
    source_page: int | None = Field(default=None, ge=0)
    epub_cfi: str = ""


class ReadingRangeLocator(ReadingLocator):
    """A stable text range, with small context for safe relocation."""

    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    quote_prefix: str = Field(default="", max_length=32)
    quote: str = Field(min_length=1, max_length=10_000)
    quote_suffix: str = Field(default="", max_length=32)

    @model_validator(mode="after")
    def validate_range(self) -> "ReadingRangeLocator":
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must not precede start_offset")
        return self


class ReadingDocument(BaseModel):
    id: str
    owner_user_id: str
    title: str
    author: str | None = None
    format: str
    source_path: str
    file_sha256: str
    file_size: int
    status: ReadingStatus
    parse_error: str | None = None
    cover_path: str | None = None
    outline_json: str | None = None
    parse_generation: int = 0
    active_parse_run_id: str | None = None
    parse_quality: ParseQuality = "good"
    parse_warning_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None = None


class ReadingParseRun(BaseModel):
    """One versioned local parse attempt for a reading document."""

    id: str
    document_id: str
    generation: int = Field(ge=1)
    parent_run_id: str | None = None
    parser_version: str
    status: ParseRunStatus
    created_at: datetime
    updated_at: datetime


class ReadingPageAnalysis(BaseModel):
    """One local extraction attempt for a source PDF page."""

    id: str
    creating_run_id: str
    source_page: int = Field(ge=0)
    retry_profile: str
    extraction_mode: str
    quality_status: ParseQuality
    quality_score: float = Field(ge=0, le=1)
    issue_codes_json: str
    created_at: datetime


class ReadingChapter(BaseModel):
    id: str
    document_id: str
    position: int
    parent_id: str | None = None
    title: str
    source_locator: ReadingLocator
    plain_text: str
    sanitized_html: str
    created_at: datetime


class ReadingProgress(BaseModel):
    owner_user_id: str
    document_id: str
    mode: str
    locator: ReadingLocator
    percent: float
    updated_at: datetime


class ReadingPreferences(BaseModel):
    owner_user_id: str
    theme: str
    font_family: str
    font_size: int
    layout: str
    sound_track: str
    sound_volume: float
    updated_at: datetime


class ReadingAnnotation(BaseModel):
    id: str
    owner_user_id: str
    document_id: str
    kind: Literal["bookmark", "highlight", "note"]
    locator: ReadingRangeLocator
    quote: str
    note_body: str | None = None
    color: str | None = None
    created_at: datetime
    updated_at: datetime


class FocusMaterial(BaseModel):
    id: str
    owner_user_id: str
    source_type: str
    source_id: str | None = None
    source_title: str
    quote: str
    note: str | None = None
    locator: ReadingRangeLocator | None = None
    consumed_at: datetime | None = None
    created_at: datetime
