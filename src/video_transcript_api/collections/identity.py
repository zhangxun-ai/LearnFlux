"""Canonical identity helpers for learning collections.

Same owner + creator + title must map to one collection. Normalization keeps
whitespace variants from creating accidental duplicates.
"""

from __future__ import annotations

import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_collection_identity_field(value: str | None) -> str:
    """Normalize a creator/title field for storage and uniqueness checks."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u00a0", " ").strip()
    text = _WHITESPACE_RE.sub(" ", text)
    return text
