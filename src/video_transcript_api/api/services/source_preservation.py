"""Source file preservation and document extraction helpers."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional


DOC_EXTS = {".txt", ".md", ".markdown", ".csv", ".log", ".html", ".htm", ".pdf", ".docx"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".flv", ".avi"}


def _read_text_file(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract_document_text(path: str, ext: str) -> str:
    """Extract plain text from supported local document files."""
    ext = (ext or "").lower()
    if ext in (".txt", ".md", ".markdown", ".csv", ".log"):
        return _read_text_file(path).strip()
    if ext in (".html", ".htm"):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_read_text_file(path), "html.parser")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        root = soup.body or soup
        lines = [line.strip() for line in root.get_text("\n").splitlines()]
        return "\n".join(line for line in lines if line).strip()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(parts).strip()
    if ext == ".docx":
        import docx

        document = docx.Document(path)
        return "\n".join(p.text for p in document.paragraphs).strip()
    raise ValueError(f"不支持的文档格式: {ext}")


def preserve_source_file(
    source_path: Optional[str] = None,
    *,
    source_root: str | Path,
    platform: str,
    media_id: str,
    title: str,
    source_kind: str = "media",
    source_text: Optional[str] = None,
) -> Optional[str]:
    """Persist an online source file outside temp storage and return its path."""
    source_ext = Path(source_path).suffix.lower() if source_path else ""
    if source_kind == "video":
        target_ext = ".mp4"
    elif source_kind == "document":
        target_ext = ".pdf" if source_ext == ".pdf" else ".md"
    else:
        target_ext = source_ext if source_ext and len(source_ext) <= 10 else ".bin"

    target_dir = online_source_files_dir(source_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{safe_source_stem(platform, media_id, title)}{target_ext}"

    if source_text is not None:
        target_path.write_text(source_text, encoding="utf-8")
        return str(target_path)

    if not source_path or not os.path.exists(source_path):
        return None

    if source_kind == "document" and target_ext == ".md":
        target_path.write_text(
            read_text_source(source_path, source_ext).strip(),
            encoding="utf-8",
        )
    else:
        shutil.copy2(source_path, target_path)
    return str(target_path)


def source_kind_for_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in DOC_EXTS:
        return "document"
    if ext in VIDEO_EXTS:
        return "video"
    return "media"


def online_source_files_dir(source_root: str | Path) -> Path:
    return Path(source_root) / "online_downloads"


def safe_source_stem(platform: str, media_id: str, title: str) -> str:
    raw = "_".join(part for part in (platform, media_id) if part)
    if not raw:
        raw = title or "source"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return safe[:160] or "source"


def read_text_source(path: str, ext: str) -> str:
    if ext in DOC_EXTS:
        return extract_document_text(path, ext)
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")
