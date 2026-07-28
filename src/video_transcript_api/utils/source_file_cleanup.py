"""Cleanup helpers for persisted local source files."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class SourceCleanupResult:
    scanned_count: int = 0
    deleted_count: int = 0
    deleted_bytes: int = 0
    skipped_referenced_count: int = 0
    error_count: int = 0
    cleared_reference_count: int = 0


def managed_ephemeral_media_roots(
    *,
    temp_dir: str | Path | None = None,
    collection_source_dir: str | Path | None = None,
    source_root: str | Path | None = None,
) -> list[Path]:
    """Directories that only hold processing staging copies (never user originals)."""
    temp_root = Path(temp_dir or "./data/temp").resolve()
    collection_dir = Path(
        collection_source_dir or "./data/source_files/collection_uploads"
    ).resolve()
    roots = {
        (temp_root / "collection_uploads").resolve(),
        (temp_root / "collection_staging").resolve(),
        (temp_root / "collection_audio").resolve(),
        collection_dir,
    }
    if source_root is not None:
        roots.add((Path(source_root) / "collection_uploads").resolve())
    return sorted(roots, key=lambda path: len(path.parts))


def is_ephemeral_managed_media_path(
    path: str | Path | None,
    *,
    temp_dir: str | Path | None = None,
    collection_source_dir: str | Path | None = None,
    source_root: str | Path | None = None,
) -> bool:
    """True when ``path`` lives under a managed staging tree (safe to delete)."""
    if not path:
        return False
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    for root in managed_ephemeral_media_roots(
        temp_dir=temp_dir,
        collection_source_dir=collection_source_dir,
        source_root=source_root,
    ):
        try:
            if not root.exists():
                # Still treat logical children as managed even if root is missing.
                root_prefix = str(root) + os.sep
                if str(resolved).startswith(root_prefix) or resolved == root:
                    return True
                continue
            resolved.relative_to(root)
            return True
        except (ValueError, OSError):
            continue
    return False


def should_preserve_local_media_path(
    path: str | Path | None,
    *,
    preserve_source_file: bool,
    temp_dir: str | Path | None = None,
    collection_source_dir: str | Path | None = None,
) -> bool:
    """Whether the *source media* path should survive after processing.

    Priority: product UX first (open source / re-parse / study player).
    When ``preserve_source_file`` is True, keep the source media regardless of
    whether it is a user original path or a managed durable copy.

    True intermediates (extracted audio under ``collection_audio``, throwaway
    temp staging) are never passed as the durable source path — callers clean
    those separately.
    """
    if not preserve_source_file or not path:
        return False
    # Extracted audio / throwaway temp only — never treat as durable source.
    if is_intermediate_processing_artifact(
        path,
        temp_dir=temp_dir,
    ):
        return False
    return True


def is_intermediate_processing_artifact(
    path: str | Path | None,
    *,
    temp_dir: str | Path | None = None,
) -> bool:
    """Paths that exist only to speed processing and must be deleted after use."""
    if not path:
        return False
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    temp_root = Path(temp_dir or "./data/temp").resolve()
    intermediate_roots = (
        (temp_root / "collection_audio").resolve(),
        (temp_root / "collection_staging").resolve(),
    )
    for root in intermediate_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            try:
                if str(resolved).startswith(str(root) + os.sep):
                    return True
            except Exception:
                pass
    return False


def purge_managed_collection_media(
    *,
    cache_manager,
    collection_source_dir: str | Path,
    temp_dir: str | Path | None = None,
    extra_roots: Iterable[str | Path] = (),
) -> SourceCleanupResult:
    """Delete managed collection media copies and clear task source_file_path refs.

    User originals outside managed trees are never touched. Transcript/summary
    caches stay intact — only redundant media bytes are removed.
    """
    roots = managed_ephemeral_media_roots(
        temp_dir=temp_dir,
        collection_source_dir=collection_source_dir,
    )
    for extra in extra_roots:
        roots.append(Path(extra).resolve())

    scanned = deleted = deleted_bytes = errors = 0
    for root in roots:
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if not item.is_file() and not item.is_symlink():
                continue
            scanned += 1
            try:
                size = item.stat().st_size if item.is_file() else 0
                item.unlink(missing_ok=True)
                deleted += 1
                deleted_bytes += size
            except OSError:
                errors += 1

    cleared = 0
    clear_fn = getattr(cache_manager, "clear_ephemeral_source_file_paths", None)
    if callable(clear_fn):
        try:
            cleared = int(
                clear_fn(
                    prefixes=[str(root) for root in roots],
                )
                or 0
            )
        except Exception:
            errors += 1

    return SourceCleanupResult(
        scanned_count=scanned,
        deleted_count=deleted,
        deleted_bytes=deleted_bytes,
        skipped_referenced_count=0,
        error_count=errors,
        cleared_reference_count=cleared,
    )


def cleanup_old_source_files(
    *,
    cache_manager,
    source_root: str | Path,
    collection_source_dir: str | Path | None = None,
    max_age_days: int = 30,
    now: float | None = None,
) -> SourceCleanupResult:
    """Delete expired legacy task sources that are not referenced by task_status.

    The managed ``reading`` tree is intentionally outside this cleanup lifecycle.
    Reading document deletion is solely responsible for removing those sources.
    """
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
    """Yield only legacy task paths; never traverse ``source_root/reading``."""
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
