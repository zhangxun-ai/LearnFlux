"""Deterministic sections derived from existing interpretation Markdown."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence

from .schemas import SourceReference


@dataclass(frozen=True)
class InterpretationSection:
    id: str
    title: str
    markdown: str
    source_ref_ids: tuple[str, ...]


class InterpretationNotReady(ValueError):
    """Raised when an interpretation cannot provide three non-empty sections."""


@dataclass(frozen=True)
class _SectionDraft:
    title: str
    markdown: str


_HEADING_PATTERN = re.compile(
    r"^ {0,3}##(?!#)[ \t]+(?P<title>[^\r\n]+?)[ \t]*(?:\r?\n|$)",
    re.MULTILINE,
)
_PARAGRAPH_BOUNDARY = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)+")
_FENCE_OPENING = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
_DOCUMENT_FENCE = re.compile(
    r"^\s*```(?:markdown|md)?[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n```[ \t]*\s*$",
    re.IGNORECASE,
)


def normalize_interpretation_markdown(markdown: str) -> str:
    """Remove document wrappers without changing Markdown inside the body."""
    text = str(markdown or "").lstrip("\ufeff")
    fenced = _DOCUMENT_FENCE.match(text)
    if fenced:
        text = fenced.group("body")

    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        closing = next(
            (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
            None,
        )
        if closing is not None:
            text = "".join(lines[closing + 1 :]).lstrip("\r\n")
    return text


def _fence_ranges(markdown: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    active: tuple[str, int, int] | None = None
    offset = 0
    for line in markdown.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if active is None:
            opening = _FENCE_OPENING.fullmatch(content)
            if opening:
                marker = opening.group("marker")
                if marker[0] == "~" or "`" not in opening.group("info"):
                    active = (marker[0], len(marker), offset)
        else:
            marker, minimum_length, start = active
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(marker)}{{{minimum_length},}}[ \t]*",
                content,
            )
            if closing:
                ranges.append((start, offset + len(content)))
                active = None
        offset += len(line)

    if active is not None:
        ranges.append((active[2], len(markdown)))
    return ranges


def _outside_fences(position: int, ranges: list[tuple[int, int]]) -> bool:
    return all(not start <= position < end for start, end in ranges)


def _paragraphs(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    pending = ""
    start = 0
    fence_ranges = _fence_ranges(markdown)
    boundaries = (
        match
        for match in _PARAGRAPH_BOUNDARY.finditer(markdown)
        if _outside_fences(match.start(), fence_ranges)
    )
    for boundary in boundaries:
        paragraph = markdown[start : boundary.end()]
        if paragraph.strip():
            paragraphs.append(f"{pending}{paragraph}")
            pending = ""
        else:
            pending += paragraph
        start = boundary.end()

    tail = markdown[start:]
    if tail.strip():
        paragraphs.append(f"{pending}{tail}")
    elif paragraphs:
        paragraphs[-1] += f"{pending}{tail}"
    return paragraphs


def _title_from_markdown(markdown: str) -> str:
    return next(line.strip() for line in markdown.splitlines() if line.strip())


def _initial_sections(markdown: str) -> list[_SectionDraft]:
    fence_ranges = _fence_ranges(markdown)
    headings = [
        match
        for match in _HEADING_PATTERN.finditer(markdown)
        if _outside_fences(match.start(), fence_ranges)
    ]
    if headings:
        sections: list[_SectionDraft] = []
        preamble = markdown[: headings[0].start()]
        pending = ""
        if preamble.strip():
            sections.append(
                _SectionDraft(
                    title=_title_from_markdown(preamble),
                    markdown=preamble,
                )
            )
        else:
            pending = preamble

        for index, heading in enumerate(headings):
            body_end = (
                headings[index + 1].start()
                if index + 1 < len(headings)
                else len(markdown)
            )
            body = f"{pending}{markdown[heading.end() : body_end]}"
            pending = ""
            if body.strip():
                sections.append(
                    _SectionDraft(
                        title=heading.group("title"),
                        markdown=body,
                    )
                )
            elif sections:
                previous = sections[-1]
                sections[-1] = _SectionDraft(
                    title=previous.title,
                    markdown=f"{previous.markdown}{body}",
                )
            else:
                pending = body
        return sections

    return [
        _SectionDraft(title=_title_from_markdown(paragraph), markdown=paragraph)
        for paragraph in _paragraphs(markdown)
    ]


def _merge_to_eight(sections: list[_SectionDraft]) -> list[_SectionDraft]:
    if len(sections) <= 8:
        return sections

    group_size, extra = divmod(len(sections), 8)
    merged: list[_SectionDraft] = []
    start = 0
    for group_index in range(8):
        size = group_size + (1 if group_index < extra else 0)
        group = sections[start : start + size]
        merged.append(
            _SectionDraft(
                title=" / ".join(section.title for section in group),
                markdown="".join(section.markdown for section in group),
            )
        )
        start += size
    return merged


def _split_to_three(sections: list[_SectionDraft]) -> list[_SectionDraft]:
    result = list(sections)
    while len(result) < 3:
        candidates = [
            (len(_paragraphs(section.markdown)), len(section.markdown), -index, index)
            for index, section in enumerate(result)
            if len(_paragraphs(section.markdown)) > 1
        ]
        if not candidates:
            raise InterpretationNotReady(
                "interpretation must contain at least three non-empty sections"
            )

        split_index = max(candidates)[-1]
        section = result[split_index]
        paragraphs = _paragraphs(section.markdown)
        midpoint = len(paragraphs) // 2
        replacements = [
            _SectionDraft(section.title, "".join(paragraphs[:midpoint])),
            _SectionDraft(section.title, "".join(paragraphs[midpoint:])),
        ]
        result[split_index : split_index + 1] = replacements
    return result


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for part in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            if len(part) == 1:
                tokens.add(part)
            else:
                tokens.update(part[index : index + 2] for index in range(len(part) - 1))
        else:
            tokens.add(part)
    return tokens


def _matching_ref_ids(
    section: _SectionDraft,
    source_refs: Sequence[SourceReference],
    ref_texts: Mapping[str, str],
) -> tuple[str, ...]:
    query_tokens = _tokens(f"{section.title} {section.markdown}")
    indexed = [
        (ref.id, _tokens(ref_texts[ref.id]), position)
        for position, ref in enumerate(source_refs)
        if ref.id in ref_texts and ":summary:section:" not in ref.id
    ]
    ranked = sorted(
        indexed,
        key=lambda item: (len(query_tokens & item[1]), -item[2]),
        reverse=True,
    )
    return tuple(
        ref_id
        for ref_id, tokens, _position in ranked
        if query_tokens & tokens
    )[:6]


def build_interpretation_sections(
    markdown: str,
    *,
    owner_type: str,
    owner_id: str,
    source_refs: Sequence[SourceReference],
    ref_texts: Mapping[str, str],
) -> tuple[InterpretationSection, ...]:
    """Return three to eight stable sections without rewriting source Markdown."""
    markdown = normalize_interpretation_markdown(markdown)
    sections = _split_to_three(_merge_to_eight(_initial_sections(markdown)))
    return tuple(
        InterpretationSection(
            id=section_id,
            title=section.title,
            markdown=section.markdown,
            source_ref_ids=(
                f"{owner_type}:{owner_id}:summary:section:{section_id}",
                *_matching_ref_ids(section, source_refs, ref_texts),
            ),
        )
        for index, section in enumerate(sections, start=1)
        for section_id in (f"section-{index:02d}",)
    )
