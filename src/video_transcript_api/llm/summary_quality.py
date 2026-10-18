"""Conservative structural checks shared by generation and cached result reuse."""

from __future__ import annotations

import re


def _normalized_source(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()


def summary_source_issues(transcript: str, summary: str) -> list[str]:
    """Find invented references or misquoted statements for one correction.

    This is not a semantic fact-check. Paraphrases without quotation marks are
    deliberately not treated as direct quotes.
    """
    source = _normalized_source(transcript)
    issues = []
    for reference in re.findall(r"\b[A-Za-z]{2,}[/\-]\d+[\w.\-]*", summary):
        reference = reference.rstrip(".-")
        if _normalized_source(reference) not in source:
            issues.append(f"reference absent from source: {reference}")
    for quote in re.findall(r'[“「]([^”」\n]+)[”」]|"([^"\n]+)"', summary):
        content = _normalized_source(quote[0] or quote[1])
        if len(content) >= 12 and content not in source:
            issues.append(f"direct quote cannot be matched to source: {quote[0] or quote[1]}")
    if "严格依据系统要求" in summary or "**解析说明**" in summary:
        issues.insert(0, "remove instruction commentary and self-certification")
    return list(dict.fromkeys(issues))[:8]


def summary_incompleteness_reason(transcript: str, summary: str | None) -> str | None:
    """Return an observable defect, without imposing topic or output word counts."""
    if not isinstance(summary, str) or not summary.strip():
        return "empty_summary"
    content = summary.strip()
    if content.endswith((":", "：")):
        return "dangling_explanation"
    lines = content.splitlines()
    if re.match(r"^#{1,6}\s+", lines[-1]):
        return "empty_final_section"
    fences = re.findall(r"^\s*(`{3,}|~{3,})[^\n]*$", content, re.MULTILINE)
    open_fence = None
    for fence in fences:
        if open_fence is None:
            open_fence = fence
        elif fence[0] == open_fence[0] and len(fence) >= len(open_fence):
            open_fence = None
    if open_fence is not None:
        return "unclosed_code_block"

    # A long source with explicitly only an overview is a partial document.
    # Short content and complete prose without headings remain valid.
    if len(transcript or "") >= 5000:
        sections = re.findall(r"^#{2,6}\s+(.+?)\s*$", content, re.MULTILINE)
        if sections and all(
            re.fullmatch(
                r"(?:\d+[.、．]?\s*)?(?:概述|内容概述|Overview)(?:\s*[（(]Overview[）)])?",
                section.strip(),
                re.IGNORECASE,
            )
            for section in sections
        ):
            return "overview_without_analysis"
    return None
