import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote

_SAFE_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,9}$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")

_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".ts": "video/mp2t",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}

_DOCUMENT_EXTS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".log", ".html", ".htm"}
_VIDEO_EXTS = {ext for ext, media_type in _MEDIA_TYPES.items() if media_type.startswith("video/")}
_AUDIO_EXTS = {ext for ext, media_type in _MEDIA_TYPES.items() if media_type.startswith("audio/")}


def safe_media_id(media_id: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", (media_id or "").strip()).strip("_")
    return cleaned or "local_source"


def safe_extension(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if _SAFE_EXT_RE.match(ext):
        return ext
    return ".bin"


def build_study_source_path(source_root: str | Path, media_id: str, filename: str) -> Path:
    return Path(source_root) / "study_uploads" / f"{safe_media_id(media_id)}{safe_extension(filename)}"


def media_type_for_filename(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _MEDIA_TYPES:
        return _MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or "application/octet-stream"


def describe_study_source(
    *,
    url: str,
    title: str,
    source_file: Path | None,
    media_type: str = "",
    media_kind: str = "",
) -> dict[str, str]:
    """Describe a Study source without changing legacy playback fields."""
    clean_url = (url or "").strip()
    filename = (title or "").strip()
    parsed = parse_study_local_url(clean_url)
    if not filename and parsed:
        filename = parsed[1]
    if not filename and source_file is not None:
        filename = source_file.name
    filename = filename or "source"

    if clean_url.startswith("local://study-text/"):
        kind = "text"
    else:
        candidates = []
        if source_file is not None:
            candidates.append(source_file.suffix.lower())
        if parsed:
            candidates.append(Path(parsed[1]).suffix.lower())
        candidates.append(Path(filename).suffix.lower())
        extension = next((item for item in candidates if item), "")
        if extension in _DOCUMENT_EXTS:
            kind = "document"
        elif extension in _VIDEO_EXTS:
            kind = "video"
        elif extension in _AUDIO_EXTS:
            kind = "audio"
        else:
            trusted_media_type = (media_type or "").lower().strip()
            existing_kind = (media_kind or "").lower().strip()
            if trusted_media_type.startswith("video/"):
                kind = "video"
            elif trusted_media_type.startswith("audio/"):
                kind = "audio"
            elif trusted_media_type in {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain",
                "text/markdown",
                "text/html",
                "application/xhtml+xml",
            }:
                kind = "document"
            elif existing_kind in {"video", "audio", "document", "text"}:
                kind = existing_kind
            elif existing_kind == "article":
                kind = "document"
            else:
                kind = "unknown"

    resolved_media_type = media_type_for_filename(filename)
    if resolved_media_type == "application/octet-stream" and media_type:
        resolved_media_type = media_type
    return {
        "kind": kind,
        "filename": filename,
        "media_type": resolved_media_type,
    }


def parse_study_local_url(url: str) -> tuple[str, str] | None:
    if not (url or "").startswith("local://study-source/"):
        return None
    raw = url.replace("local://study-source/", "", 1)
    parts = raw.split("/", 1)
    if len(parts) != 2:
        return None
    return unquote(parts[0]), unquote(parts[1])


def find_study_source_file(
    *,
    source_root: str | Path,
    media_id: str,
    title: str,
    url: str,
    source_file_path: str = "",
    allowed_roots: tuple[str | Path, ...] = (),
) -> Path | None:
    roots = (Path(source_root), *[Path(root) for root in allowed_roots])
    if source_file_path:
        retained = _safe_existing_file(Path(source_file_path), roots)
        if retained is not None:
            return retained

    parsed = parse_study_local_url(url)
    lookup_media_id = media_id
    lookup_title = title
    if parsed:
        lookup_media_id, lookup_title = parsed

    if not lookup_media_id:
        return None

    path = build_study_source_path(source_root, lookup_media_id, lookup_title or title or "")
    return _safe_existing_file(path, roots)


def _safe_existing_file(path: Path, allowed_roots: tuple[Path, ...]) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except (OSError, ValueError):
            continue
    return None
