import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote

_SAFE_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,9}$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")

_MEDIA_TYPES = {
    ".mp4": "video/mp4",
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
) -> Path | None:
    parsed = parse_study_local_url(url)
    lookup_media_id = media_id
    lookup_title = title
    if parsed:
        lookup_media_id, lookup_title = parsed

    if not lookup_media_id:
        return None

    path = build_study_source_path(source_root, lookup_media_id, lookup_title or title or "")
    return path if path.exists() else None
