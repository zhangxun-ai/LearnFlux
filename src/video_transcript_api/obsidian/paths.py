"""Vault-contained path, identity lookup, and atomic write helpers."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Mapping


class VaultPathError(ValueError):
    """Raised when a client-supplied path is unsafe or leaves the Vault."""


class ManagedFileConflict(ValueError):
    """Raised when more than one file claims the same managed identity."""


_RESERVED_PATH_CHARS = set('<>:"|?*\\')
_RESERVED_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LEGACY_MANAGED_SOURCES = {"LearnFlux": frozenset({"VideoTranscriptAPI"})}


def _relative_parts(relative_path: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or "\x00" in relative_path:
        raise VaultPathError("invalid relative path")
    if relative_path != relative_path.strip():
        raise VaultPathError("relative path cannot have outer whitespace")
    if not relative_path:
        if allow_empty:
            return ()
        raise VaultPathError("relative path is required")
    path = PurePosixPath(relative_path)
    if path.is_absolute():
        raise VaultPathError("absolute paths are not allowed")
    parts = path.parts
    if not parts and not allow_empty:
        raise VaultPathError("relative path is required")
    for part in parts:
        if part in {"", ".", ".."} or part.startswith("."):
            raise VaultPathError("dot and traversal path segments are not allowed")
        if any(char in _RESERVED_PATH_CHARS for char in part):
            raise VaultPathError("reserved path characters are not allowed")
    return parts


def resolve_vault_path(
    vault_root: str | Path,
    relative_path: str,
    *,
    allow_empty: bool = False,
) -> Path:
    """Resolve a safe relative path and prove it remains inside the Vault."""
    root = Path(vault_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise VaultPathError("vault root is not a directory")
    parts = _relative_parts(relative_path, allow_empty=allow_empty)
    resolved = root.joinpath(*parts).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VaultPathError("path escapes the configured vault") from exc
    return resolved


def list_vault_directories(
    vault_root: str | Path,
    *,
    root: str = "vault",
    query: str = "",
) -> list[str]:
    """List visible, Vault-contained directory paths for a binding picker."""
    if root not in {"raw", "vault"}:
        raise VaultPathError("root must be raw or vault")
    base_relative = "raw" if root == "raw" else ""
    base = resolve_vault_path(vault_root, base_relative, allow_empty=True)
    if not base.is_dir():
        return []
    vault = Path(vault_root).expanduser().resolve(strict=True)
    needle = (query or "").casefold()
    results: list[str] = []
    if base_relative and (not needle or needle in base_relative.casefold()):
        results.append(base_relative)

    for current, directories, _files in os.walk(base, topdown=True, followlinks=False):
        visible: list[str] = []
        for name in sorted(directories):
            if name.startswith("."):
                continue
            candidate = Path(current) / name
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(vault)
            except (OSError, ValueError):
                continue
            if resolved.is_dir() and not candidate.is_symlink():
                visible.append(name)
        directories[:] = visible
        for name in visible:
            relative = ((Path(current) / name).relative_to(vault)).as_posix()
            if not needle or needle in relative.casefold():
                results.append(relative)
    return sorted(set(results), key=lambda value: (value.casefold(), value))


def list_raw_categories(vault_root: str | Path, *, raw_root: str = "raw") -> list[str]:
    """Return only visible direct category directories under the raw root."""
    base = resolve_vault_path(vault_root, raw_root)
    if not base.is_dir():
        return []
    vault = Path(vault_root).expanduser().resolve(strict=True)
    return sorted(
        (entry.name for entry in base.iterdir() if not entry.name.startswith(".") and entry.is_dir() and not entry.is_symlink() and entry.resolve().is_relative_to(vault)),
        key=lambda value: (value.casefold(), value),
    )


def build_knowledge_directory(*, root: str, category: str, collection_directory: str = "") -> str:
    """Build a safe relative directory for one managed knowledge layer."""
    root_parts = _relative_parts(root)
    category_parts = _relative_parts(category)
    if len(category_parts) != 1:
        raise VaultPathError("category must contain one path segment")
    collection_parts = _relative_parts(
        collection_directory, allow_empty=True
    )
    if len(collection_parts) > 1:
        raise VaultPathError(
            "collection directory must contain one path segment"
        )
    parts = (*root_parts, *category_parts, *collection_parts)
    return PurePosixPath(*parts).as_posix()


def ensure_vault_directory_tree(vault_root: str | Path, relative_directory: str) -> Path:
    """Create a validated, non-symlink directory tree only during apply."""
    target = resolve_vault_path(vault_root, relative_directory)
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or not target.is_dir():
        raise VaultPathError("unsafe vault directory")
    return target


def create_vault_directory(
    vault_root: str | Path,
    parent_relative_path: str,
    name: str,
) -> str:
    """Create one explicitly requested child directory inside the Vault."""
    parts = _relative_parts(name)
    if len(parts) != 1:
        raise VaultPathError("directory name must contain one path segment")
    parent = resolve_vault_path(vault_root, parent_relative_path, allow_empty=True)
    if not parent.is_dir():
        raise VaultPathError("parent directory does not exist")
    target_relative = PurePosixPath(parent_relative_path, name).as_posix()
    target = resolve_vault_path(vault_root, target_relative)
    target.mkdir(exist_ok=True)
    return target_relative


def sanitize_markdown_filename(title: str, *, fallback: str = "未命名课程") -> str:
    """Create a readable cross-platform Markdown filename from a lesson title."""
    cleaned = _RESERVED_FILENAME_RE.sub("-", str(title or "")).strip(" .")
    if not cleaned:
        cleaned = _RESERVED_FILENAME_RE.sub("-", fallback).strip(" .") or "untitled"
    encoded = cleaned.encode("utf-8")
    if len(encoded) > 180:
        encoded = encoded[:180]
        while True:
            try:
                cleaned = encoded.decode("utf-8").rstrip(" .")
                break
            except UnicodeDecodeError:
                encoded = encoded[:-1]
    return f"{cleaned}.md"


def _read_scalar_frontmatter(path: Path) -> dict[str, str]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            if handle.readline().rstrip("\r\n") != "---":
                return {}
            fields: dict[str, str] = {}
            for line in handle:
                stripped = line.rstrip("\r\n")
                if stripped == "---":
                    return fields
                if not stripped or stripped[0].isspace() or ":" not in stripped:
                    continue
                key, value = stripped.split(":", 1)
                fields[key.strip()] = value.strip().strip('"\'')
    except (OSError, UnicodeError):
        return {}
    return {}


def find_managed_markdown_files(
    vault_root: str | Path,
    directory_relative_path: str,
    identity: Mapping[str, str],
) -> list[str]:
    """Find direct child Markdown files with an exact managed identity tuple.

    The renamed LearnFlux brand accepts its legacy source marker so existing
    managed notes continue to resolve to their original files.
    """
    directory = resolve_vault_path(vault_root, directory_relative_path)
    if not directory.is_dir():
        raise VaultPathError("managed directory does not exist")
    vault = Path(vault_root).expanduser().resolve(strict=True)
    matches = []
    for path in sorted(directory.glob("*.md"), key=lambda item: item.name.casefold()):
        try:
            path.resolve(strict=True).relative_to(vault)
        except (OSError, ValueError):
            continue
        fields = _read_scalar_frontmatter(path)
        if all(
            fields.get(key) == str(value)
            or (
                key == "source"
                and fields.get(key)
                in _LEGACY_MANAGED_SOURCES.get(str(value), frozenset())
            )
            for key, value in identity.items()
        ):
            matches.append(path.relative_to(vault).as_posix())
    return matches


def allocate_managed_markdown_path(
    vault_root: str | Path,
    directory_relative_path: str,
    title: str,
    identity: Mapping[str, str],
) -> str:
    """Recover a managed file or allocate a collision-safe new relative path."""
    matches = find_managed_markdown_files(vault_root, directory_relative_path, identity)
    if len(matches) > 1:
        raise ManagedFileConflict("multiple files claim the same managed identity")
    if matches:
        return matches[0]

    directory = resolve_vault_path(vault_root, directory_relative_path)
    filename = sanitize_markdown_filename(title)
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = directory / filename
    index = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = directory / f"{stem} ({index}){suffix}"
        index += 1
    vault = Path(vault_root).expanduser().resolve(strict=True)
    return candidate.relative_to(vault).as_posix()


def atomic_write_text(
    vault_root: str | Path,
    relative_path: str,
    content: str,
) -> None:
    """Atomically replace one UTF-8 text file using a sibling temporary file."""
    target = resolve_vault_path(vault_root, relative_path)
    if not target.parent.is_dir():
        raise VaultPathError("target directory does not exist")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".vta-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
