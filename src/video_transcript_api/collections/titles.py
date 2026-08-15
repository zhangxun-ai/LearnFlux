import os


DISPLAY_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".log",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
    ".ts",
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
}


def source_basename(value: str) -> str:
    """Return the uploaded filename without any browser-supplied folder path."""
    normalized = str(value or "").strip().replace("\\", "/")
    return normalized.rsplit("/", 1)[-1].strip()


def source_display_title(value: str) -> str:
    """Return a readable source title while preserving the stored filename."""
    filename = source_basename(value)
    stem, extension = os.path.splitext(filename)
    if stem and extension.lower() in DISPLAY_EXTENSIONS:
        return stem
    return filename
