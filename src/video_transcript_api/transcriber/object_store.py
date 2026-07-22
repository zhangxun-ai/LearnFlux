"""Private temporary object storage for transcription media."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from botocore.exceptions import ClientError


class ObjectStoreError(RuntimeError):
    """A storage failure represented only by a stable, safe code."""


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    size: int
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class PresignedObjectAccess:
    url: str = field(repr=False)
    expires_in_seconds: int


_CATEGORY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def _validate_key(key: str) -> str:
    if not isinstance(key, str) or not key or "\\" in key or "\x00" in key:
        raise ObjectStoreError("invalid_object_key")
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ObjectStoreError("invalid_object_key")
    normalized = path.as_posix()
    if normalized != key or len(key.encode("utf-8")) > 512:
        raise ObjectStoreError("invalid_object_key")
    return normalized


def _new_key(
    *, owner_user_id: str, task_id: str, category: str, suffix: str = ""
) -> str:
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise ObjectStoreError("invalid_object_identity")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ObjectStoreError("invalid_object_identity")
    if not _CATEGORY.fullmatch(category):
        raise ObjectStoreError("invalid_object_category")
    if suffix and not _SUFFIX.fullmatch(suffix):
        raise ObjectStoreError("invalid_object_suffix")
    owner_hash = hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:16]
    task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]
    return f"{category}/{owner_hash}/{task_hash}/{uuid.uuid4().hex}{suffix.lower()}"


def _regular_source(path: str | os.PathLike[str]) -> Path:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ObjectStoreError("invalid_source_file")
    return source


class LocalObjectStore:
    """Filesystem-backed private store for local development and tests."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._root.is_symlink() or not self._root.is_dir():
            raise ObjectStoreError("invalid_object_root")

    def __repr__(self) -> str:
        return "LocalObjectStore(private=True)"

    @staticmethod
    def new_key(**kwargs) -> str:
        return _new_key(**kwargs)

    def _path(self, key: str) -> Path:
        key = _validate_key(key)
        candidate = self._root.joinpath(*PurePosixPath(key).parts)
        resolved = candidate.resolve(strict=False)
        if self._root not in resolved.parents:
            raise ObjectStoreError("invalid_object_key")
        current = self._root
        for part in PurePosixPath(key).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ObjectStoreError("invalid_object_key")
        if candidate.is_symlink():
            raise ObjectStoreError("invalid_object_key")
        return candidate

    def put_file(self, key: str, source_path: str | os.PathLike[str]) -> ObjectMetadata:
        source = _regular_source(source_path)
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.parent / f".{uuid.uuid4().hex}.upload"
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
            temporary.chmod(0o600)
            os.replace(temporary, target)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ObjectStoreError("object_write_failed") from None
        return ObjectMetadata(key=key, size=target.stat().st_size)

    def download_to(self, key: str, destination: str | os.PathLike[str]) -> ObjectMetadata:
        source = self._path(key)
        if source.is_symlink() or not source.is_file():
            raise ObjectStoreError("object_not_found")
        target = Path(destination)
        if target.is_symlink():
            raise ObjectStoreError("invalid_destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open("rb") as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
        except OSError:
            raise ObjectStoreError("object_read_failed") from None
        return ObjectMetadata(key=key, size=source.stat().st_size)

    def head(self, key: str) -> ObjectMetadata | None:
        path = self._path(key)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ObjectStoreError("invalid_object_key")
        return ObjectMetadata(key=key, size=path.stat().st_size)

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_symlink():
            raise ObjectStoreError("invalid_object_key")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise ObjectStoreError("object_delete_failed") from None


class S3ObjectStore:
    """Private S3-compatible store; Cloudflare R2 is the MVP deployment target."""

    def __init__(
        self,
        *,
        client,
        bucket: str,
        presign_ttl_seconds: int = 900,
        acl: str = "private",
    ) -> None:
        if acl != "private":
            raise ObjectStoreError("public_acl_forbidden")
        if not isinstance(bucket, str) or not bucket.strip():
            raise ObjectStoreError("invalid_bucket")
        if not 60 <= presign_ttl_seconds <= 3600:
            raise ObjectStoreError("invalid_presign_ttl")
        self._client = client
        self._bucket = bucket
        self._presign_ttl_seconds = presign_ttl_seconds

    def __repr__(self) -> str:
        return (
            "S3ObjectStore(private=True, "
            f"presign_ttl_seconds={self._presign_ttl_seconds})"
        )

    @classmethod
    def from_settings(cls, settings):
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        return cls(
            client=client,
            bucket=settings.s3_bucket,
            presign_ttl_seconds=settings.presign_ttl_seconds,
        )

    @staticmethod
    def new_key(**kwargs) -> str:
        return _new_key(**kwargs)

    def put_file(self, key: str, source_path: str | os.PathLike[str]) -> ObjectMetadata:
        key = _validate_key(key)
        source = _regular_source(source_path)
        try:
            self._client.upload_file(str(source), self._bucket, key)
        except Exception:
            raise ObjectStoreError("object_write_failed") from None
        return ObjectMetadata(key=key, size=source.stat().st_size)

    def download_to(self, key: str, destination: str | os.PathLike[str]) -> ObjectMetadata:
        key = _validate_key(key)
        target = Path(destination)
        if target.is_symlink():
            raise ObjectStoreError("invalid_destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self._bucket, key, str(target))
        except Exception:
            raise ObjectStoreError("object_read_failed") from None
        metadata = self.head(key)
        if metadata is None:
            raise ObjectStoreError("object_not_found")
        return metadata

    def head(self, key: str) -> ObjectMetadata | None:
        key = _validate_key(key)
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStoreError("object_head_failed") from None
        except Exception:
            raise ObjectStoreError("object_head_failed") from None
        etag = response.get("ETag")
        return ObjectMetadata(
            key=key,
            size=int(response["ContentLength"]),
            etag=str(etag).strip('"') if etag else None,
        )

    def delete(self, key: str) -> None:
        key = _validate_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception:
            raise ObjectStoreError("object_delete_failed") from None

    def presign_get(self, key: str) -> PresignedObjectAccess:
        return self._presign("get_object", key)

    def presign_put(self, key: str) -> PresignedObjectAccess:
        return self._presign("put_object", key)

    def _presign(self, operation: str, key: str) -> PresignedObjectAccess:
        key = _validate_key(key)
        try:
            url = self._client.generate_presigned_url(
                operation,
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._presign_ttl_seconds,
            )
        except Exception:
            raise ObjectStoreError("object_presign_failed") from None
        return PresignedObjectAccess(
            url=url,
            expires_in_seconds=self._presign_ttl_seconds,
        )
