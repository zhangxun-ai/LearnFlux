"""Validate and persist private reading source files."""

from __future__ import annotations

import codecs
import hashlib
import hmac
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO


SUPPORTED_READING_EXTS = {
    ".pdf",
    ".epub",
    ".docx",
    ".txt",
    ".md",
    ".markdown",
}

MAX_READING_UPLOAD_BYTES = 100 * 1024 * 1024
READING_UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200.0

_DOCUMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_OWNER_COMPONENT_PATTERN = re.compile(r"u_[a-f0-9]{32}\Z")
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}


class ReadingSourceError(ValueError):
    """A reading source failed a safe validation or storage operation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class StagedReadingUpload:
    """A streamed upload held in a private temporary file."""

    temp_path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class InspectedReadingUpload(StagedReadingUpload):
    """A staged upload with a validated reading format."""

    extension: str
    format: str


def safe_user_component(owner_user_id: str) -> str:
    """Return a deterministic opaque directory component for an owner."""
    if not isinstance(owner_user_id, str) or not owner_user_id:
        raise ReadingSourceError("invalid_owner")
    digest = hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:32]
    return f"u_{digest}"


def reading_source_path(
    data_root: str | Path,
    owner_user_id: str,
    document_id: str,
    extension: str,
) -> Path:
    """Build the only supported path shape for a persisted reading source."""
    normalized_extension = str(extension).lower()
    if normalized_extension not in SUPPORTED_READING_EXTS:
        raise ReadingSourceError("unsupported_extension")
    if not isinstance(document_id, str) or not _DOCUMENT_ID_PATTERN.fullmatch(
        document_id
    ):
        raise ReadingSourceError("invalid_document_id")
    root = Path(data_root).resolve()
    return (
        root
        / "reading"
        / safe_user_component(owner_user_id)
        / f"{document_id}{normalized_extension}"
    )


def stage_upload(
    stream: BinaryIO,
    *,
    staging_dir: str | Path,
    max_bytes: int = MAX_READING_UPLOAD_BYTES,
    chunk_size: int = READING_UPLOAD_CHUNK_BYTES,
) -> StagedReadingUpload:
    """Stream an upload to disk while enforcing size and computing SHA-256."""
    if max_bytes <= 0 or chunk_size <= 0:
        raise ReadingSourceError("invalid_limit")

    directory = Path(staging_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".reading-upload-",
            suffix=".tmp",
            dir=directory,
            delete=False,
        ) as destination:
            temp_path = Path(destination.name)
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise ReadingSourceError("invalid_upload")
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise ReadingSourceError("file_too_large")
                digest.update(chunk)
                destination.write(chunk)
            if size_bytes == 0:
                raise ReadingSourceError("empty_file")
            destination.flush()
            os.fsync(destination.fileno())
    except ReadingSourceError:
        _unlink_temp(temp_path)
        raise
    except (OSError, ValueError, TypeError):
        _unlink_temp(temp_path)
        raise ReadingSourceError("staging_failed") from None

    return StagedReadingUpload(
        temp_path=temp_path,
        sha256=digest.hexdigest(),
        size_bytes=size_bytes,
    )


def inspect_upload(
    staged: StagedReadingUpload,
    original_filename: str,
    *,
    max_zip_entries: int = MAX_ZIP_ENTRIES,
    max_zip_entry_bytes: int = MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES,
    max_zip_total_bytes: int = MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES,
    max_zip_compression_ratio: float = MAX_ZIP_COMPRESSION_RATIO,
) -> InspectedReadingUpload:
    """Validate a staged upload's extension, signature, and container metadata."""
    extension = Path(str(original_filename)).suffix.lower()
    if extension not in SUPPORTED_READING_EXTS:
        _unlink_temp(staged.temp_path)
        raise ReadingSourceError("unsupported_extension")

    try:
        if extension == ".pdf":
            _validate_pdf(staged.temp_path)
            source_format = "pdf"
        elif extension in {".docx", ".epub"}:
            _validate_zip_container(
                staged.temp_path,
                extension=extension,
                max_entries=max_zip_entries,
                max_entry_bytes=max_zip_entry_bytes,
                max_total_bytes=max_zip_total_bytes,
                max_compression_ratio=max_zip_compression_ratio,
            )
            source_format = extension[1:]
        else:
            _validate_text(staged.temp_path)
            source_format = "txt" if extension == ".txt" else "markdown"
    except ReadingSourceError:
        _unlink_temp(staged.temp_path)
        raise
    except (OSError, UnicodeError, zipfile.BadZipFile, ValueError):
        _unlink_temp(staged.temp_path)
        raise ReadingSourceError("format_mismatch") from None

    return InspectedReadingUpload(
        temp_path=staged.temp_path,
        sha256=staged.sha256,
        size_bytes=staged.size_bytes,
        extension=extension,
        format=source_format,
    )


def save_staged_upload(
    inspected: InspectedReadingUpload,
    *,
    data_root: str | Path,
    owner_user_id: str,
    document_id: str,
) -> Path:
    """Atomically save a validated source without replacing different content."""
    final_temp: Path | None = None
    try:
        destination = reading_source_path(
            data_root,
            owner_user_id,
            document_id,
            inspected.extension,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _validate_save_destination(destination)
        if destination.exists():
            if _hash_file(destination) == inspected.sha256:
                return destination
            raise ReadingSourceError("source_exists")

        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{document_id}-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as output:
            final_temp = Path(output.name)
            copied_hash = hashlib.sha256()
            copied_size = 0
            with inspected.temp_path.open("rb") as source:
                while True:
                    chunk = source.read(READING_UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    copied_hash.update(chunk)
                    copied_size += len(chunk)
                    output.write(chunk)
            if (
                copied_size != inspected.size_bytes
                or copied_hash.hexdigest() != inspected.sha256
            ):
                raise ReadingSourceError("staged_source_changed")
            output.flush()
            os.fsync(output.fileno())

        if destination.exists():
            if _hash_file(destination) == inspected.sha256:
                return destination
            raise ReadingSourceError("source_exists")
        os.replace(final_temp, destination)
        final_temp = None
        _fsync_directory(destination.parent)
        return destination
    except ReadingSourceError:
        raise
    except OSError:
        raise ReadingSourceError("save_failed") from None
    finally:
        _unlink_temp(final_temp)
        _unlink_temp(inspected.temp_path)


def repair_missing_source(
    inspected: InspectedReadingUpload,
    *,
    data_root: str | Path,
    owner_user_id: str,
    document_id: str,
    expected_sha256: str,
) -> Path:
    """Repair a missing deduplicated source only with identical uploaded bytes."""
    if not hmac.compare_digest(inspected.sha256, str(expected_sha256).lower()):
        _unlink_temp(inspected.temp_path)
        raise ReadingSourceError("hash_mismatch")
    return save_staged_upload(
        inspected,
        data_root=data_root,
        owner_user_id=owner_user_id,
        document_id=document_id,
    )


def delete_reading_source(
    source_path: str | Path,
    *,
    data_root: str | Path,
) -> bool:
    """Delete a file only when its path has the managed reading path shape."""
    candidate_resolved = validate_reading_source_path(
        source_path, data_root=data_root
    )
    if not candidate_resolved.exists():
        return False
    if not candidate_resolved.is_file():
        raise ReadingSourceError("unmanaged_source_path")
    try:
        candidate_resolved.unlink()
    except OSError:
        raise ReadingSourceError("delete_failed") from None
    return True


def validate_reading_source_path(
    source_path: str | Path,
    *,
    data_root: str | Path,
) -> Path:
    """Resolve a source only when it has the managed reading path shape."""
    candidate = Path(source_path)
    root = Path(data_root).resolve()
    managed_root = root / "reading"
    candidate_absolute = candidate if candidate.is_absolute() else root / candidate
    candidate_resolved = candidate_absolute.resolve(strict=False)

    try:
        relative = candidate_resolved.relative_to(managed_root)
    except ValueError:
        raise ReadingSourceError("unmanaged_source_path") from None

    if candidate_absolute.absolute() != candidate_resolved:
        raise ReadingSourceError("unmanaged_source_path")
    if len(relative.parts) != 2:
        raise ReadingSourceError("unmanaged_source_path")
    owner_component, filename = relative.parts
    file_path = Path(filename)
    if (
        not _OWNER_COMPONENT_PATTERN.fullmatch(owner_component)
        or file_path.suffix.lower() not in SUPPORTED_READING_EXTS
        or not _DOCUMENT_ID_PATTERN.fullmatch(file_path.stem)
    ):
        raise ReadingSourceError("unmanaged_source_path")
    if candidate_resolved.is_symlink():
        raise ReadingSourceError("unmanaged_source_path")
    if candidate_resolved.exists() and not candidate_resolved.is_file():
        raise ReadingSourceError("unmanaged_source_path")
    return candidate_resolved


def _validate_pdf(path: Path) -> None:
    with path.open("rb") as source:
        if source.read(4) != b"%PDF":
            raise ReadingSourceError("format_mismatch")


def _validate_text(path: Path) -> None:
    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    first_chunk = True
    control_bytes = 0
    total_bytes = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(READING_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            if first_chunk:
                first_chunk = False
                if chunk.startswith((b"%PDF", b"PK\x03\x04")):
                    raise ReadingSourceError("format_mismatch")
            if b"\x00" in chunk:
                raise ReadingSourceError("format_mismatch")
            total_bytes += len(chunk)
            control_bytes += sum(
                byte < 32 and byte not in {9, 10, 12, 13} for byte in chunk
            )
            decoder.decode(chunk, final=False)
    decoder.decode(b"", final=True)
    if control_bytes and control_bytes / total_bytes > 0.05:
        raise ReadingSourceError("format_mismatch")


def _validate_zip_container(
    path: Path,
    *,
    extension: str,
    max_entries: int,
    max_entry_bytes: int,
    max_total_bytes: int,
    max_compression_ratio: float,
) -> None:
    if (
        max_entries <= 0
        or max_entry_bytes <= 0
        or max_total_bytes <= 0
        or max_compression_ratio <= 0
    ):
        raise ReadingSourceError("invalid_limit")
    if not zipfile.is_zipfile(path):
        raise ReadingSourceError("format_mismatch")

    with zipfile.ZipFile(path, "r") as archive:
        entries = archive.infolist()
        if len(entries) > max_entries:
            raise ReadingSourceError("unsafe_archive")

        names: set[str] = set()
        total_size = 0
        for entry in entries:
            normalized_name = entry.filename.replace("\\", "/")
            if not _is_safe_archive_name(entry.filename):
                raise ReadingSourceError("unsafe_archive")
            if normalized_name in names:
                raise ReadingSourceError("unsafe_archive")
            names.add(normalized_name)
            if entry.flag_bits & 0x1:
                raise ReadingSourceError("unsafe_archive")
            file_mode = entry.external_attr >> 16
            if stat.S_ISLNK(file_mode):
                raise ReadingSourceError("unsafe_archive")
            if entry.file_size > max_entry_bytes:
                raise ReadingSourceError("unsafe_archive")
            total_size += entry.file_size
            if total_size > max_total_bytes:
                raise ReadingSourceError("unsafe_archive")
            if entry.file_size:
                if entry.compress_size <= 0:
                    raise ReadingSourceError("unsafe_archive")
                if entry.file_size / entry.compress_size > max_compression_ratio:
                    raise ReadingSourceError("unsafe_archive")

        if extension == ".docx":
            if "[Content_Types].xml" not in names or not any(
                name.startswith("word/") and not name.endswith("/") for name in names
            ):
                raise ReadingSourceError("format_mismatch")
            return

        if "mimetype" not in names or "META-INF/container.xml" not in names:
            raise ReadingSourceError("format_mismatch")
        try:
            mimetype = archive.read("mimetype")
        except (KeyError, RuntimeError, zipfile.BadZipFile):
            raise ReadingSourceError("format_mismatch") from None
        if mimetype != b"application/epub+zip":
            raise ReadingSourceError("format_mismatch")


def _is_safe_archive_name(name: str) -> bool:
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(name).drive:
        return False
    path = PurePosixPath(normalized)
    return not path.is_absolute() and all(
        part not in {".", ".."} for part in path.parts
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(READING_UPLOAD_CHUNK_BYTES)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _validate_save_destination(destination: Path) -> None:
    """Reject symlinks anywhere below the trusted, resolved data root."""
    if destination.parent.resolve(strict=True) != destination.parent.absolute():
        raise ReadingSourceError("unmanaged_source_path")
    if destination.is_symlink():
        raise ReadingSourceError("unmanaged_source_path")


def _unlink_temp(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _fsync_directory(directory: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
