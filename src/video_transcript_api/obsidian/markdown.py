"""Render and parse application-managed Obsidian Markdown documents."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import yaml


MANAGED_FRONTMATTER_FIELDS = (
    "type",
    "source",
    "vta_view_token",
    "vta_collection_id",
    "vta_source_id",
    "course",
    "lesson",
    "synced_at",
)


class MarkdownFormatError(ValueError):
    """Raised when existing frontmatter cannot be parsed safely."""


@dataclass(frozen=True)
class MarkdownDocument:
    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class TranscriptParagraph:
    timestamp_seconds: float | None
    text: str


_CONNECTING_PUNCTUATION = frozenset("，,、；;：:。.！？!?…")
_TERMINAL_PUNCTUATION = frozenset("。.！？!?…")
_CLOSING_PUNCTUATION = frozenset("”’）》】」』")


def _normalize_newlines(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")


def parse_markdown_document(content: str) -> MarkdownDocument:
    """Parse optional YAML frontmatter and a normalized Markdown body."""
    normalized = _normalize_newlines(content)
    if not normalized.startswith("---\n"):
        return MarkdownDocument(frontmatter={}, body=normalized.rstrip("\n"))
    lines = normalized.split("\n")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise MarkdownFormatError("frontmatter closing delimiter is missing") from exc
    raw_frontmatter = "\n".join(lines[1:closing])
    try:
        parsed = yaml.safe_load(raw_frontmatter) if raw_frontmatter.strip() else {}
    except yaml.YAMLError as exc:
        raise MarkdownFormatError("frontmatter is not valid YAML") from exc
    if not isinstance(parsed, dict):
        raise MarkdownFormatError("frontmatter must be a mapping")
    body_lines = lines[closing + 1 :]
    if body_lines and body_lines[0] == "":
        body_lines = body_lines[1:]
    if body_lines and body_lines[-1] == "":
        body_lines = body_lines[:-1]
    return MarkdownDocument(frontmatter=dict(parsed), body="\n".join(body_lines))


def managed_identity(
    document_type: str,
    *,
    view_token: str,
    collection_id: str = "",
    source_id: str = "",
) -> dict[str, str]:
    """Return the immutable identity tuple used to recover renamed files."""
    if bool(collection_id) != bool(source_id):
        raise ValueError("collection_id and source_id must be provided together")
    identity = {"type": document_type, "source": "LearnFlux"}
    if collection_id and source_id:
        identity["vta_collection_id"] = collection_id
        identity["vta_source_id"] = source_id
    else:
        identity["vta_view_token"] = view_token
    return identity


def _managed_frontmatter(document_type: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    view_token = str(metadata.get("view_token") or "")
    collection_id = str(metadata.get("collection_id") or "")
    source_id = str(metadata.get("source_id") or "")
    if bool(collection_id) != bool(source_id):
        raise ValueError("collection_id and source_id must be provided together")
    fields: dict[str, Any] = {
        "type": document_type,
        "source": "LearnFlux",
        "vta_view_token": view_token,
    }
    if collection_id and source_id:
        fields["vta_collection_id"] = collection_id
        fields["vta_source_id"] = source_id
    if metadata.get("course"):
        fields["course"] = str(metadata["course"])
    fields["lesson"] = str(metadata.get("lesson") or "未命名课程")
    fields["synced_at"] = str(metadata.get("synced_at") or "")
    return fields


def _serialize_markdown(frontmatter: Mapping[str, Any], body: str) -> str:
    dumped = yaml.safe_dump(
        dict(frontmatter),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip("\n")
    normalized_body = _normalize_newlines(body)
    if normalized_body:
        return f"---\n{dumped}\n---\n\n{normalized_body.rstrip(chr(10))}\n"
    return f"---\n{dumped}\n---\n"


def _format_timestamp(seconds: Any) -> str:
    total = max(0, int(float(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    remaining = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:02d}:{remaining:02d}"


def _content_length(value: str) -> int:
    return len("".join(str(value or "").split()))


def _punctuation_index(value: str) -> int:
    index = len(value) - 1
    while index >= 0 and value[index] in _CLOSING_PUNCTUATION:
        index -= 1
    return index


def _ends_with_punctuation(value: str, punctuation: frozenset[str]) -> bool:
    index = _punctuation_index(value)
    return index >= 0 and value[index] in punctuation


def _join_transcript_text(current: str, fragment: str) -> str:
    if not current:
        return fragment
    if (
        _ends_with_punctuation(current, _CONNECTING_PUNCTUATION)
        or fragment[0] in _CONNECTING_PUNCTUATION
    ):
        return f"{current}{fragment}"
    return f"{current}，{fragment}"


def _finish_paragraph_text(value: str) -> str:
    text = value.rstrip()
    index = _punctuation_index(text)
    if index < 0 or text[index] in _TERMINAL_PUNCTUATION:
        return text
    if text[index] in _CONNECTING_PUNCTUATION:
        return f"{text[:index]}。{text[index + 1:]}"
    return f"{text[:index + 1]}。{text[index + 1:]}"


def _valid_time(value: Any) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def _line_timestamp(item: Mapping[str, Any]) -> float | None:
    if not item.get("seekable"):
        return None
    return _valid_time(item.get("start_seconds"))


def _build_transcript_paragraphs(
    transcript_lines: list[Mapping[str, Any]],
) -> list[TranscriptParagraph]:
    paragraphs: list[TranscriptParagraph] = []
    current_text = ""
    current_timestamp: float | None = None
    previous_end: float | None = None

    def finish_current() -> None:
        nonlocal current_text, current_timestamp
        if not current_text:
            return
        paragraphs.append(
            TranscriptParagraph(
                timestamp_seconds=current_timestamp,
                text=_finish_paragraph_text(current_text),
            )
        )
        current_text = ""
        current_timestamp = None

    for item in transcript_lines:
        fragment = str(item.get("text") or "").strip()
        if not fragment:
            continue
        fragment_length = _content_length(fragment)
        timestamp = _line_timestamp(item)
        current_start = _valid_time(item.get("start_seconds"))
        current_end = _valid_time(item.get("end_seconds"))

        if fragment_length > 320:
            finish_current()
            current_text = fragment
            current_timestamp = timestamp
            finish_current()
            previous_end = current_end
            continue

        current_length = _content_length(current_text)
        reliable_silence = (
            current_text
            and current_length >= 80
            and previous_end is not None
            and current_start is not None
            and current_start - previous_end >= 8
        )
        if reliable_silence:
            finish_current()

        joined = _join_transcript_text(current_text, fragment)
        if (
            current_text
            and _content_length(current_text) >= 80
            and _content_length(joined) > 320
        ):
            finish_current()
            joined = fragment

        current_text = joined
        if current_timestamp is None:
            current_timestamp = timestamp

        current_length = _content_length(current_text)
        if current_length >= 260:
            finish_current()
        elif current_length >= 180 and _ends_with_punctuation(
            fragment, _TERMINAL_PUNCTUATION
        ):
            finish_current()

        previous_end = current_end

    finish_current()
    return paragraphs


def render_transcript_markdown(
    metadata: Mapping[str, Any],
    transcript_lines: list[Mapping[str, Any]],
) -> str:
    """Render a fully application-managed transcript Markdown file."""
    title = str(metadata.get("lesson") or "未命名课程")
    rows = [f"# {title}", "", "## 文字稿"]
    for paragraph in _build_transcript_paragraphs(transcript_lines):
        rows.append("")
        if paragraph.timestamp_seconds is None:
            rows.append(paragraph.text)
        else:
            rows.append(
                f"**{_format_timestamp(paragraph.timestamp_seconds)}** {paragraph.text}"
            )
    body = "\n".join(rows).rstrip()
    return _serialize_markdown(_managed_frontmatter("transcript", metadata), body)


def render_note_markdown(
    metadata: Mapping[str, Any],
    body: str,
    *,
    existing_content: str | None,
) -> str:
    """Render a note while preserving all non-managed user frontmatter fields."""
    existing = (
        parse_markdown_document(existing_content)
        if existing_content is not None
        else MarkdownDocument({}, "")
    )
    custom = {
        key: value
        for key, value in existing.frontmatter.items()
        if key not in MANAGED_FRONTMATTER_FIELDS
    }
    frontmatter = _managed_frontmatter("study-note", metadata)
    frontmatter.update(custom)
    return _serialize_markdown(frontmatter, body)


def extract_note_body(content: str) -> str:
    return parse_markdown_document(content).body


def note_body_hash(body: str) -> str:
    return hashlib.sha256(_normalize_newlines(body).encode("utf-8")).hexdigest()


def managed_markdown_hash(content: str) -> str:
    """Hash managed fields and body while ignoring synced_at and user metadata."""
    document = parse_markdown_document(content)
    managed = {
        key: document.frontmatter.get(key)
        for key in MANAGED_FRONTMATTER_FIELDS
        if key != "synced_at" and key in document.frontmatter
    }
    canonical = json.dumps(
        {"frontmatter": managed, "body": document.body},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
