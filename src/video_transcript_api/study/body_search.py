"""Read-only full-body search over owner-authorized result artifacts.

The source list must be scoped before calling this module. File versions and
PostgreSQL content digests invalidate a small process-local text cache, avoiding
re-reading and decoding unchanged long transcripts for each search request.
"""

from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
import re
import threading


_TYPES = ("llm_summary", "llm_calibrated", "transcript_capswriter", "transcript_funasr", "transcript_zh")
_FILES = tuple(f"{name}.{'json' if name == 'transcript_funasr' else 'txt'}" for name in _TYPES)
_MAX_CACHE_BYTES = 32 * 1024 * 1024
_cache: OrderedDict[tuple, tuple[str, int]] = OrderedDict()
_cache_bytes = 0
_lock = threading.RLock()


def _cached(key: tuple):
    with _lock:
        if key not in _cache:
            return None
        value, _ = _cache[key]
        _cache.move_to_end(key)
        return value


def _remember(key: tuple, value: str) -> str:
    global _cache_bytes
    size = len(value.encode("utf-8"))
    if size > _MAX_CACHE_BYTES:
        return value
    with _lock:
        previous = _cache.pop(key, None)
        if previous:
            _cache_bytes -= previous[1]
        _cache[key] = (value, size)
        _cache_bytes += size
        while _cache_bytes > _MAX_CACHE_BYTES:
            _, (_, discarded_size) = _cache.popitem(last=False)
            _cache_bytes -= discarded_size
    return value


def _search_text(raw: str, artifact_type: str) -> str:
    if artifact_type == "transcript_funasr":
        try:
            payload = json.loads(raw)
            from .transcript import normalize_transcript
            raw = "\n".join(line["text"] for line in normalize_transcript(payload))
        except (ValueError, TypeError, KeyError):
            return ""
    return re.sub(r"\s+", " ", raw).strip()


def _batches(values: list, size: int = 300):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _postgres_texts(connection, cache_ids: list, namespace: object) -> dict:
    results, missing = {}, {}
    for batch in _batches(cache_ids):
        marks = ",".join("?" for _ in batch)
        kinds = ",".join("?" for _ in _TYPES)
        rows = connection.execute(
            f"SELECT cache_id, artifact_type, content_sha256 FROM transcription_artifacts "
            f"WHERE cache_id IN ({marks}) AND artifact_type IN ({kinds})",
            batch + list(_TYPES),
        ).fetchall()
        for row in rows:
            key = (namespace, str(row[0]), row[1], row[2])
            value = _cached(key)
            if value is None:
                missing[(row[0], row[1])] = key
            else:
                results.setdefault(str(row[0]), []).append(value)
    missing_ids = list(dict.fromkeys(item[0] for item in missing))
    for batch in _batches(missing_ids):
        marks = ",".join("?" for _ in batch)
        kinds = ",".join("?" for _ in _TYPES)
        rows = connection.execute(
            f"SELECT cache_id, artifact_type, content, content_sha256 FROM transcription_artifacts "
            f"WHERE cache_id IN ({marks}) AND artifact_type IN ({kinds})",
            batch + list(_TYPES),
        ).fetchall()
        for row in rows:
            if (row[0], row[1]) not in missing:
                continue
            # Use the digest returned with the bytes, so a concurrent update
            # cannot associate new content with an old cache key.
            key = (namespace, str(row[0]), row[1], row[3])
            text = _search_text(bytes(row[2]).decode("utf-8", errors="replace"), row[1])
            results.setdefault(str(row[0]), []).append(_remember(key, text))
    return results


def authorized_body_texts(connection, prefix: str, cache_manager, cache_ids: list) -> dict:
    """Read only artifacts attached to the caller's already-authorized rows."""
    ids = list(dict.fromkeys(value for value in cache_ids if value is not None))
    if not ids:
        return {}
    if getattr(cache_manager, "_is_postgres", False) is True:
        # Database identity isolates independent installations inside one process.
        return _postgres_texts(connection, ids, cache_manager.database)
    has_table = connection.execute(
        "SELECT 1 FROM cache.sqlite_master WHERE type='table' AND name='video_cache'"
    ).fetchone()
    if not has_table:
        return {}
    configured_root = getattr(cache_manager, "cache_dir", None)
    if not isinstance(configured_root, (str, Path)):
        return {}
    root = Path(configured_root).resolve()
    results = {}
    for batch in _batches(ids):
        marks = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"SELECT id, files_loc FROM {prefix}video_cache WHERE id IN ({marks})", batch,
        ).fetchall()
        for row in rows:
            if not isinstance(row[1], (str, Path)) or not str(row[1]).strip():
                continue
            directory = (root / row[1]).resolve()
            if directory == root or root not in directory.parents:
                continue
            for artifact_type, filename in zip(_TYPES, _FILES):
                path = directory / filename
                try:
                    resolved = path.resolve()
                    if root not in resolved.parents or not resolved.is_file():
                        continue
                    stat = resolved.stat()
                    key = (str(resolved), stat.st_mtime_ns, stat.st_size)
                    value = _cached(key)
                    if value is None:
                        value = _remember(key, _search_text(resolved.read_text(encoding="utf-8"), artifact_type))
                    results.setdefault(str(row[0]), []).append(value)
                except (OSError, UnicodeError):
                    # A removed artifact must not hide accessible metadata rows.
                    continue
    return results


def matching_excerpt(texts: list[str], question: str) -> str | None:
    """Return a literal text match; wildcard characters are not SQL syntax."""
    needle = re.sub(r"\s+", " ", question).strip().casefold()
    if not needle:
        return None
    for text in texts:
        found = text.casefold().find(needle)
        if found >= 0:
            start, end = max(0, found - 55), min(len(text), found + len(needle) + 95)
            return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
    return None
