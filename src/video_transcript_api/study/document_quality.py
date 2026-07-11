"""Deterministic quality routing for extracted study documents."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class DocumentQualityMetrics:
    total_chars: int
    valid_chars: int
    printable_ratio: float
    replacement_char_ratio: float
    control_char_ratio: float
    wordish_ratio: float
    duplicate_line_ratio: float


@dataclass(frozen=True)
class DocumentQualityAssessment:
    mode: Literal["fast", "fallback"]
    reasons: tuple[str, ...]
    metrics: DocumentQualityMetrics

    def to_evidence(self) -> dict:
        """Return the bounded JSON payload safe to persist in task progress."""
        return {
            "mode": self.mode,
            "reasons": list(self.reasons),
            "metrics": asdict(self.metrics),
        }


def canonicalize_document_text(text: str) -> str:
    """Normalize characters only for quality calculations."""
    canonical = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return canonical[1:] if canonical.startswith("\ufeff") else canonical


def _is_wordish(char: str) -> bool:
    return (
        char.isalnum()
        or "\u4e00" <= char <= "\u9fff"
        or unicodedata.category(char).startswith("P")
    )


def assess_document_text(text: str) -> DocumentQualityAssessment:
    """Measure extracted text and choose the fast or fallback processing path."""
    canonical = canonicalize_document_text(text)
    total = len(canonical)
    denominator = max(1, total)
    non_whitespace = [char for char in canonical if not char.isspace()]
    valid_chars = sum(1 for char in non_whitespace if _is_wordish(char))
    printable = sum(
        1 for char in canonical if char.isprintable() or char in {"\n", "\t"}
    )
    controls = sum(
        1
        for char in canonical
        if unicodedata.category(char).startswith("C") and char not in {"\n", "\t"}
    )

    normalized_lines = []
    for line in canonical.split("\n"):
        normalized = re.sub(r"\s+", " ", line.strip())
        if len(normalized) >= 4:
            normalized_lines.append(normalized)
    line_counts = Counter(normalized_lines)
    duplicate_count = sum(
        count - 1 for count in line_counts.values() if count >= 3
    )

    metrics = DocumentQualityMetrics(
        total_chars=total,
        valid_chars=valid_chars,
        printable_ratio=printable / denominator,
        replacement_char_ratio=canonical.count("\ufffd") / denominator,
        control_char_ratio=controls / denominator,
        wordish_ratio=valid_chars / max(1, len(non_whitespace)),
        duplicate_line_ratio=duplicate_count / max(1, len(normalized_lines)),
    )
    reasons = []
    if metrics.valid_chars < 200:
        reasons.append("too_short")
    if metrics.printable_ratio < 0.97:
        reasons.append("low_printable_ratio")
    if metrics.replacement_char_ratio > 0.001:
        reasons.append("replacement_char_ratio")
    if metrics.control_char_ratio > 0.001:
        reasons.append("control_char_ratio")
    if metrics.wordish_ratio < 0.75:
        reasons.append("low_wordish_ratio")
    if metrics.duplicate_line_ratio > 0.35:
        reasons.append("duplicate_lines")

    return DocumentQualityAssessment(
        mode="fallback" if reasons else "fast",
        reasons=tuple(reasons),
        metrics=metrics,
    )
