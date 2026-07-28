"""Safe private assets extracted from reading documents."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .source_files import ReadingSourceError, safe_user_component


_DOCUMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_ASSET_NAME = re.compile(r"[a-f0-9]{64}\.(?:png|jpe?g|gif|webp|avif)\Z")
_MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
}
_EXTENSION_MIMES = {extension: mime for mime, extension in _MIME_EXTENSIONS.items()}
_EXTENSION_MIMES["jpeg"] = "image/jpeg"


class ReadingAssetError(ValueError):
    """An extracted reading asset failed validation or storage."""


def _matches_signature(data: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if mime_type == "image/avif":
        return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {
            b"avif", b"avis"
        }
    return False


@dataclass(frozen=True)
class ParsedAsset:
    safe_name: str
    mime_type: str
    data: bytes
    alt: str = ""

    @classmethod
    def from_bytes(
        cls, data: bytes, mime_type: str, *, alt: str = ""
    ) -> "ParsedAsset":
        normalized = str(mime_type).lower().strip()
        extension = _MIME_EXTENSIONS.get(normalized)
        if extension is None:
            raise ReadingAssetError("unsupported_asset_type")
        if not isinstance(data, bytes) or not _matches_signature(data, normalized):
            raise ReadingAssetError("asset_signature_mismatch")
        digest = hashlib.sha256(data).hexdigest()
        return cls(f"{digest}.{extension}", normalized, data, alt[:500])


def document_asset_dir(
    data_root: str | Path, owner_user_id: str, document_id: str
) -> Path:
    if not isinstance(document_id, str) or not _DOCUMENT_ID.fullmatch(document_id):
        raise ReadingAssetError("invalid_document_id")
    try:
        owner = safe_user_component(owner_user_id)
    except ReadingSourceError as exc:
        raise ReadingAssetError(str(exc)) from None
    return Path(data_root).resolve() / "reading-assets" / owner / document_id


def validate_document_asset_dir(
    path: str | Path, *, data_root: str | Path
) -> Path:
    candidate = Path(path)
    root = Path(data_root).resolve() / "reading-assets"
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ReadingAssetError("unmanaged_asset_path") from None
    if candidate.absolute() != resolved or len(relative.parts) != 2:
        raise ReadingAssetError("unmanaged_asset_path")
    owner, document_id = relative.parts
    if not re.fullmatch(r"u_[a-f0-9]{32}", owner) or not _DOCUMENT_ID.fullmatch(document_id):
        raise ReadingAssetError("unmanaged_asset_path")
    if resolved.is_symlink():
        raise ReadingAssetError("unmanaged_asset_path")
    return resolved


def write_document_assets(
    data_root: str | Path,
    owner_user_id: str,
    document_id: str,
    items: Iterable[ParsedAsset],
) -> set[str]:
    directory = document_asset_dir(data_root, owner_user_id, document_id)
    directory.mkdir(parents=True, exist_ok=True)
    written: set[str] = set()
    for item in items:
        if not _ASSET_NAME.fullmatch(item.safe_name):
            raise ReadingAssetError("invalid_asset_name")
        if not _matches_signature(item.data, item.mime_type):
            raise ReadingAssetError("asset_signature_mismatch")
        destination = directory / item.safe_name
        if destination.exists():
            if destination.read_bytes() != item.data:
                raise ReadingAssetError("asset_hash_collision")
            written.add(item.safe_name)
            continue
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".asset-", dir=directory, delete=False
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(item.data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
        written.add(item.safe_name)
    return written


def resolve_document_asset(
    data_root: str | Path,
    owner_user_id: str,
    document_id: str,
    asset_name: str,
) -> tuple[Path, str]:
    if not isinstance(asset_name, str) or not _ASSET_NAME.fullmatch(asset_name):
        raise ReadingAssetError("invalid_asset_name")
    path = document_asset_dir(data_root, owner_user_id, document_id) / asset_name
    if path.is_symlink() or not path.is_file():
        raise ReadingAssetError("asset_not_found")
    extension = path.suffix.lower().lstrip(".")
    mime = _EXTENSION_MIMES.get(extension)
    if mime is None:
        raise ReadingAssetError("unsupported_asset_type")
    return path, mime


def delete_document_assets(
    data_root: str | Path, owner_user_id: str, document_id: str
) -> bool:
    directory = document_asset_dir(data_root, owner_user_id, document_id)
    validate_document_asset_dir(directory, data_root=data_root)
    if not directory.exists():
        return False
    if not directory.is_dir():
        raise ReadingAssetError("unmanaged_asset_path")
    shutil.rmtree(directory)
    return True

