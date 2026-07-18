"""Cleanup helpers for persisted local source files."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class SourceCleanupResult:
    scanned_count: int = 0
    deleted_count: int = 0
    deleted_bytes: int = 0
    skipped_referenced_count: int = 0
    error_count: int = 0


def cleanup_old_source_files(
    *,
    cache_manager,
    source_root: str | Path,
    collection_source_dir: str | Path | None = None,
    max_age_days: int = 30,
    now: float | None = None,
) -> SourceCleanupResult:
    """Delete expired source files that are not referenced by task_status."""
    try:
        retention_days = int(max_age_days)
    except (TypeError, ValueError):
        retention_days = 0
    if retention_days <= 0:
        return SourceCleanupResult()

    root = Path(source_root)
    collection_dir = (
        Path(collection_source_dir)
        if collection_source_dir
        else root / "collection_uploads"
    )
    protected = _referenced_paths(cache_manager, root, collection_dir)
    cutoff = (
        (time.time() if now is None else float(now))
        - retention_days * 24 * 60 * 60
    )

    scanned = deleted = deleted_bytes = skipped = errors = 0
    for file_path in _iter_cleanup_candidates(root, collection_dir):
        scanned += 1
        try:
            resolved = file_path.resolve()
            if resolved in protected:
                skipped += 1
                continue
            if file_path.is_symlink() or not file_path.is_file():
                continue
            stat = file_path.stat()
            if stat.st_mtime >= cutoff:
                continue
            deleted_bytes += stat.st_size
            file_path.unlink()
            deleted += 1
        except OSError:
            errors += 1

    return SourceCleanupResult(
        scanned_count=scanned,
        deleted_count=deleted,
        deleted_bytes=deleted_bytes,
        skipped_referenced_count=skipped,
        error_count=errors,
    )


def _iter_cleanup_candidates(source_root: Path, collection_dir: Path):
    if collection_dir.exists():
        for item in collection_dir.iterdir():
            if item.is_file() or item.is_symlink():
                yield item

    for root in _compact_roots(
        [
            source_root / "study_uploads",
            source_root / "study_texts",
            source_root / "online_downloads",
        ]
    ):
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if item.is_file() or item.is_symlink():
                yield item


def _compact_roots(paths: list[Path]) -> list[Path]:
    compact: list[Path] = []
    for path in sorted({p.resolve() for p in paths}, key=lambda p: len(p.parts)):
        if any(_is_relative_to(path, existing) for existing in compact):
            continue
        compact.append(path)
    return compact


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _referenced_paths(cache_manager, source_root: Path, collection_dir: Path) -> set[Path]:
    paths: set[Path] = set()
    for row in cache_manager.list_source_file_references():
        explicit = str(row.get("source_file_path") or "").strip()
        if explicit:
            paths.add(Path(explicit).resolve())

        local_path = _path_from_local_url(
            str(row.get("url") or ""),
            str(row.get("media_id") or ""),
            str(row.get("title") or ""),
            source_root,
            collection_dir,
        )
        if local_path:
            paths.add(local_path.resolve())
    return paths


def _path_from_local_url(
    url: str,
    media_id: str,
    title: str,
    source_root: Path,
    collection_dir: Path,
) -> Path | None:
    parsed = urlparse(url or "")
    if parsed.scheme != "local":
        return None
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]

    if parsed.netloc == "collection-source" and parts:
        local_media_id = parts[0]
        filename = parts[1] if len(parts) > 1 else title
        return collection_dir / f"{local_media_id}{_safe_extension(filename)}"

    if parsed.netloc == "study-source" and parts:
        local_media_id = parts[0]
        filename = parts[1] if len(parts) > 1 else title
        return (
            source_root
            / "study_uploads"
            / f"{_safe_media_id(local_media_id)}{_safe_extension(filename)}"
        )

    if parsed.netloc == "study-text" and parts:
        local_media_id = parts[0]
        return source_root / "study_texts" / f"{_safe_media_id(local_media_id)}.md"

    if parsed.netloc == "collection" and len(parts) >= 2:
        local_media_id = media_id or parts[1]
        return collection_dir / f"{local_media_id}{_safe_extension(title or url)}"

    return None


def _safe_media_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)
    return cleaned.strip("_") or "local_source"


def _safe_extension(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext.startswith(".") and 2 <= len(ext) <= 10 and ext[1:].isalnum():
        return ext
    return ".bin"
