"""Private, immutable media snapshots for remote ASR uploads."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import fcntl

from .media_preparer import MEDIA_SUFFIXES, PreparedASRMedia, PreparedMediaFormat


@dataclass(frozen=True)
class MediaSnapshot:
    """A canonical snapshot bound to one remote ASR attempt."""

    path: Path
    task_hash: str
    attempt_no: int
    media_format: PreparedMediaFormat
    sha256: str
    size_bytes: int
    duration_seconds: Decimal


@dataclass
class VerifiedUploadHandle:
    """A read-only upload stream whose identity was captured from its open FD."""

    file: BinaryIO
    path: Path
    device: int
    inode: int
    size_bytes: int
    mtime_ns: int
    sha256: str

    def __enter__(self) -> "VerifiedUploadHandle":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.file.close()


class SnapshotError(Exception):
    """A media snapshot failure safe to expose to callers and logs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _HashingReader:
    """Update one digest while copyfileobj consumes its source once."""

    def __init__(self, source: BinaryIO, digest: Any) -> None:
        self._source = source
        self._digest = digest

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        self._digest.update(chunk)
        return chunk


class MediaSnapshotter:
    """Create private media snapshots before remote ASR credentials are used."""

    def __init__(
        self,
        temp_root: str | Path,
    ) -> None:
        self.temp_root = Path(temp_root)

    def promote(
        self,
        prepared: PreparedASRMedia,
        *,
        task_id: str,
        attempt_no: int,
        expected_sha256: str,
        create: bool,
    ) -> MediaSnapshot:
        """Copy verified quote media into one immutable attempt snapshot."""
        if not isinstance(prepared, PreparedASRMedia):
            raise SnapshotError("media_identity_mismatch")
        if (
            not isinstance(task_id, str)
            or not task_id
            or isinstance(attempt_no, bool)
            or not isinstance(attempt_no, int)
            or attempt_no <= 0
            or not isinstance(expected_sha256, str)
            or not isinstance(create, bool)
        ):
            raise SnapshotError("invalid_attempt")
        return self._promote_prepared(
            prepared,
            task_id=task_id,
            attempt_no=attempt_no,
            expected_sha256=expected_sha256,
            create=create,
        )

    def _promote_prepared(
        self,
        prepared: PreparedASRMedia,
        *,
        task_id: str,
        attempt_no: int,
        expected_sha256: str,
        create: bool,
    ) -> MediaSnapshot:
        task_hash, prepared_stat = self._validate_prepared_media(
            prepared,
            task_id=task_id,
            expected_sha256=expected_sha256,
        )
        if not create:
            existing = self.find_attempt(
                task_id=task_id,
                attempt_no=attempt_no,
                expected_sha256=expected_sha256,
                duration_seconds=prepared.duration_seconds,
            )
            if existing.media_format != prepared.media_format:
                raise SnapshotError("media_identity_conflict")
            return existing

        remote_root = self.temp_root / "remote_asr"
        task_root = remote_root / task_hash
        attempt_dir = task_root / str(attempt_no)
        suffix = MEDIA_SUFFIXES[prepared.media_format]
        temporary_path = attempt_dir / f"input.tmp{suffix}"
        final_path = attempt_dir / f"input{suffix}"
        try:
            self._mkdir_private_for_promotion(remote_root, task_root, attempt_dir)
            with self._locked_attempt(attempt_dir):
                existing_paths = self._allowlisted_attempt_paths(attempt_dir)
                if existing_paths:
                    existing = self.find_attempt(
                        task_id=task_id,
                        attempt_no=attempt_no,
                        expected_sha256=expected_sha256,
                        duration_seconds=prepared.duration_seconds,
                    )
                    if existing.media_format != prepared.media_format:
                        raise SnapshotError("media_identity_conflict")
                    return existing

                self._remove_stale_temporary(temporary_path)
                self._copy_prepared_media(
                    prepared,
                    prepared_stat=prepared_stat,
                    temporary_path=temporary_path,
                    expected_sha256=expected_sha256,
                )

                if self._allowlisted_attempt_paths(attempt_dir):
                    raise SnapshotError("media_identity_conflict")
                try:
                    os.link(temporary_path, final_path, follow_symlinks=False)
                except FileExistsError:
                    existing = self.find_attempt(
                        task_id=task_id,
                        attempt_no=attempt_no,
                        expected_sha256=expected_sha256,
                        duration_seconds=prepared.duration_seconds,
                    )
                    if existing.media_format != prepared.media_format:
                        raise SnapshotError("media_identity_conflict")
                    temporary_path.unlink()
                    self._fsync_directory(attempt_dir)
                    return existing
                temporary_path.unlink()
                self._fsync_directory(attempt_dir)
                self._fsync_directory(task_root)
        except SnapshotError:
            self._unlink_temporary_best_effort(temporary_path)
            raise
        except Exception:
            self._unlink_temporary_best_effort(temporary_path)
            raise SnapshotError("media_promotion_failed") from None

        return MediaSnapshot(
            path=final_path,
            task_hash=task_hash,
            attempt_no=attempt_no,
            media_format=prepared.media_format,
            sha256=expected_sha256,
            size_bytes=prepared.size_bytes,
            duration_seconds=prepared.duration_seconds,
        )

    def find_attempt(
        self,
        *,
        task_id: str,
        attempt_no: int,
        expected_sha256: str,
        duration_seconds: Decimal,
    ) -> MediaSnapshot:
        """Recover exactly one allowlisted, verified attempt snapshot."""
        if (
            not isinstance(task_id, str)
            or not task_id
            or isinstance(attempt_no, bool)
            or not isinstance(attempt_no, int)
            or attempt_no <= 0
            or not self._valid_sha256(expected_sha256)
        ):
            raise SnapshotError("media_identity_conflict")
        try:
            duration = Decimal(str(duration_seconds))
            if not duration.is_finite() or duration <= 0:
                raise ValueError
        except Exception:
            raise SnapshotError("media_identity_conflict") from None

        task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        task_root = self.temp_root / "remote_asr" / task_hash
        attempt_dir = task_root / str(attempt_no)
        self._validate_attempt_directory(attempt_dir, task_root)
        candidates = self._allowlisted_attempt_paths(attempt_dir)
        if len(candidates) != 1:
            raise SnapshotError("media_identity_conflict")
        media_format, path = candidates[0]
        try:
            path_stat = path.lstat()
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(
                path_stat.st_mode
            ):
                raise OSError
            actual_sha256 = self._hash_stable_path(path, path_stat)
        except Exception:
            raise SnapshotError("media_identity_conflict") from None
        if actual_sha256 != expected_sha256:
            raise SnapshotError("media_identity_conflict")
        return MediaSnapshot(
            path=path,
            task_hash=task_hash,
            attempt_no=attempt_no,
            media_format=media_format,
            sha256=actual_sha256,
            size_bytes=path_stat.st_size,
            duration_seconds=duration,
        )

    def _validate_prepared_media(
        self,
        prepared: PreparedASRMedia,
        *,
        task_id: str,
        expected_sha256: str,
    ) -> tuple[str, os.stat_result]:
        try:
            if (
                prepared.media_format not in MEDIA_SUFFIXES
                or not self._valid_sha256(prepared.sha256)
                or not self._valid_sha256(expected_sha256)
                or prepared.sha256 != expected_sha256
                or isinstance(prepared.size_bytes, bool)
                or not isinstance(prepared.size_bytes, int)
                or prepared.size_bytes <= 0
            ):
                raise ValueError
            duration = Decimal(str(prepared.duration_seconds))
            if not duration.is_finite() or duration <= 0:
                raise ValueError

            task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
            cloud_root = self.temp_root / "cloud_quotes"
            task_root = cloud_root / task_hash
            quote_dir = prepared.path.parent
            expected_path = quote_dir / f"input{MEDIA_SUFFIXES[prepared.media_format]}"
            if (
                prepared.path != expected_path
                or not quote_dir.name.startswith("quote-")
            ):
                raise ValueError

            temp_root_stat = self.temp_root.lstat()
            cloud_root_stat = cloud_root.lstat()
            task_root_stat = task_root.lstat()
            quote_dir_stat = quote_dir.lstat()
            prepared_stat = prepared.path.lstat()
            directory_stats = (
                temp_root_stat,
                cloud_root_stat,
                task_root_stat,
                quote_dir_stat,
            )
            if any(
                stat.S_ISLNK(path_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                for path_stat in directory_stats
            ):
                raise ValueError
            if (
                stat.S_ISLNK(prepared_stat.st_mode)
                or not stat.S_ISREG(prepared_stat.st_mode)
                or prepared_stat.st_size != prepared.size_bytes
            ):
                raise ValueError

            temp_root_resolved = self.temp_root.resolve(strict=True)
            cloud_root_resolved = cloud_root.resolve(strict=True)
            task_root_resolved = task_root.resolve(strict=True)
            quote_dir_resolved = quote_dir.resolve(strict=True)
            prepared_resolved = prepared.path.resolve(strict=True)
            if (
                cloud_root_resolved.parent != temp_root_resolved
                or task_root_resolved.parent != cloud_root_resolved
                or quote_dir_resolved.parent != task_root_resolved
                or prepared_resolved.parent != quote_dir_resolved
                or prepared_resolved.name != expected_path.name
            ):
                raise ValueError
        except Exception:
            raise SnapshotError("media_identity_mismatch") from None
        return task_hash, prepared_stat

    def _copy_prepared_media(
        self,
        prepared: PreparedASRMedia,
        *,
        prepared_stat: os.stat_result,
        temporary_path: Path,
        expected_sha256: str,
    ) -> None:
        source_descriptor: int | None = None
        target_descriptor: int | None = None
        try:
            source_descriptor = os.open(
                prepared.path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            source_stat = os.fstat(source_descriptor)
            if (
                not stat.S_ISREG(source_stat.st_mode)
                or source_stat.st_dev != prepared_stat.st_dev
                or source_stat.st_ino != prepared_stat.st_ino
                or source_stat.st_size != prepared.size_bytes
            ):
                raise OSError
            with os.fdopen(source_descriptor, "rb", closefd=True) as source_file:
                source_descriptor = None
                target_descriptor = os.open(
                    temporary_path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                with os.fdopen(target_descriptor, "wb", closefd=True) as target_file:
                    target_descriptor = None
                    source_digest = hashlib.sha256()
                    shutil.copyfileobj(
                        _HashingReader(source_file, source_digest),
                        target_file,
                        1024 * 1024,
                    )
                    if source_digest.hexdigest() != expected_sha256:
                        raise OSError
                    final_source_stat = os.fstat(source_file.fileno())
                    if (
                        final_source_stat.st_dev != source_stat.st_dev
                        or final_source_stat.st_ino != source_stat.st_ino
                        or final_source_stat.st_size != source_stat.st_size
                    ):
                        raise OSError
                    target_file.flush()
                    os.fchmod(target_file.fileno(), 0o400)
                    os.fsync(target_file.fileno())

            temporary_stat = temporary_path.lstat()
            if (
                stat.S_ISLNK(temporary_stat.st_mode)
                or not stat.S_ISREG(temporary_stat.st_mode)
                or temporary_stat.st_size != prepared.size_bytes
                or self._hash_stable_path(temporary_path, temporary_stat)
                != expected_sha256
            ):
                raise OSError
        finally:
            if target_descriptor is not None:
                os.close(target_descriptor)
            if source_descriptor is not None:
                os.close(source_descriptor)

    @staticmethod
    def _valid_sha256(value: object) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    @staticmethod
    def _allowlisted_attempt_paths(
        attempt_dir: Path,
    ) -> list[tuple[PreparedMediaFormat, Path]]:
        return [
            (media_format, path)
            for media_format, suffix in MEDIA_SUFFIXES.items()
            if os.path.lexists(path := attempt_dir / f"input{suffix}")
        ]

    @staticmethod
    def _remove_stale_temporary(path: Path) -> None:
        if not os.path.lexists(path):
            return
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise SnapshotError("media_promotion_failed")
        path.unlink()

    @staticmethod
    def _unlink_temporary_best_effort(path: Path) -> None:
        try:
            path_stat = path.lstat()
            if stat.S_ISREG(path_stat.st_mode) and not stat.S_ISLNK(path_stat.st_mode):
                path.unlink()
        except OSError:
            pass

    def _mkdir_private_for_promotion(self, *paths: Path) -> None:
        try:
            temp_root_stat = self.temp_root.lstat()
            if stat.S_ISLNK(temp_root_stat.st_mode) or not stat.S_ISDIR(
                temp_root_stat.st_mode
            ):
                raise OSError
            for path in paths:
                path.mkdir(mode=0o700, exist_ok=True)
                path_stat = path.lstat()
                if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(
                    path_stat.st_mode
                ):
                    raise OSError
                path.chmod(0o700)
        except Exception:
            raise SnapshotError("media_promotion_failed") from None

    @staticmethod
    def _validate_attempt_directory(attempt_dir: Path, task_root: Path) -> None:
        remote_root = task_root.parent
        temp_root = remote_root.parent
        try:
            directory_stats = (
                temp_root.lstat(),
                remote_root.lstat(),
                task_root.lstat(),
                attempt_dir.lstat(),
            )
            if any(
                stat.S_ISLNK(path_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                for path_stat in directory_stats
            ):
                raise OSError
            temp_resolved = temp_root.resolve(strict=True)
            remote_resolved = remote_root.resolve(strict=True)
            task_resolved = task_root.resolve(strict=True)
            attempt_resolved = attempt_dir.resolve(strict=True)
            if (
                remote_resolved.parent != temp_resolved
                or task_resolved.parent != remote_resolved
                or attempt_resolved.parent != task_resolved
            ):
                raise OSError
        except Exception:
            raise SnapshotError("media_identity_conflict") from None

    @staticmethod
    @contextmanager
    def _locked_attempt(attempt_dir: Path) -> Iterator[None]:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                attempt_dir / ".promotion.lock",
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    def open_for_upload(self, snapshot: MediaSnapshot) -> VerifiedUploadHandle:
        """Open and verify the exact read-only FD that the uploader will consume."""
        descriptor: int | None = None
        media_file: BinaryIO | None = None
        try:
            path_stat = snapshot.path.lstat()
            if not stat.S_ISREG(path_stat.st_mode):
                raise OSError
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(snapshot.path, flags)
            descriptor_stat = os.fstat(descriptor)
            if (
                descriptor_stat.st_dev != path_stat.st_dev
                or descriptor_stat.st_ino != path_stat.st_ino
                or descriptor_stat.st_size != snapshot.size_bytes
            ):
                raise OSError
            media_file = os.fdopen(descriptor, "rb", closefd=True)
            descriptor = None
            actual_sha256 = self._hash_file(media_file)
            if actual_sha256 != snapshot.sha256:
                raise OSError
            return VerifiedUploadHandle(
                file=media_file,
                path=snapshot.path,
                device=descriptor_stat.st_dev,
                inode=descriptor_stat.st_ino,
                size_bytes=descriptor_stat.st_size,
                mtime_ns=descriptor_stat.st_mtime_ns,
                sha256=actual_sha256,
            )
        except Exception:
            if media_file is not None:
                media_file.close()
            if descriptor is not None:
                os.close(descriptor)
            raise SnapshotError("media_changed_before_submit") from None

    def verify_unchanged(self, handle: VerifiedUploadHandle) -> None:
        """Revalidate upload media from the same FD and rewind for submission."""
        try:
            path_stat = handle.path.lstat()
            descriptor_stat = os.fstat(handle.file.fileno())
            unchanged_path = (
                not stat.S_ISLNK(path_stat.st_mode)
                and stat.S_ISREG(path_stat.st_mode)
                and path_stat.st_dev == handle.device
                and path_stat.st_ino == handle.inode
                and path_stat.st_size == handle.size_bytes
                and path_stat.st_mtime_ns == handle.mtime_ns
            )
            unchanged_descriptor = (
                descriptor_stat.st_dev == handle.device
                and descriptor_stat.st_ino == handle.inode
                and descriptor_stat.st_size == handle.size_bytes
                and descriptor_stat.st_mtime_ns == handle.mtime_ns
            )
            actual_sha256 = self._hash_file(handle.file)
            if (
                not unchanged_path
                or not unchanged_descriptor
                or actual_sha256 != handle.sha256
            ):
                raise SnapshotError("media_changed_before_submit")
        except SnapshotError:
            raise
        except Exception:
            raise SnapshotError("media_changed_before_submit") from None
        finally:
            try:
                handle.file.seek(0)
            except (OSError, ValueError):
                pass

    def cleanup_attempt(self, snapshot: MediaSnapshot) -> None:
        """Delete only the canonical directory owned by ``snapshot``."""
        if not self._valid_task_hash(snapshot.task_hash) or snapshot.attempt_no <= 0:
            raise SnapshotError("unsafe_cleanup_path")
        suffix = MEDIA_SUFFIXES.get(snapshot.media_format)
        if suffix is None:
            raise SnapshotError("unsafe_cleanup_path")
        task_root = self.temp_root / "remote_asr" / snapshot.task_hash
        attempt_dir = task_root / str(snapshot.attempt_no)
        if (
            snapshot.path.parent != attempt_dir
            or snapshot.path.name != f"input{suffix}"
        ):
            raise SnapshotError("unsafe_cleanup_path")
        target = self._validated_cleanup_dir(attempt_dir, task_root)
        if target is None:
            return
        try:
            shutil.rmtree(target)
            self._fsync_directory(task_root)
        except OSError:
            raise SnapshotError("media_cleanup_failed") from None

    @staticmethod
    def _valid_task_hash(task_hash: str) -> bool:
        return len(task_hash) == 64 and all(
            character.lower() in "0123456789abcdef" for character in task_hash
        )

    @staticmethod
    def _validated_cleanup_dir(target: Path, parent: Path) -> Path | None:
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise SnapshotError("unsafe_cleanup_path") from None
        if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISDIR(target_stat.st_mode):
            raise SnapshotError("unsafe_cleanup_path")
        try:
            resolved_parent = parent.resolve(strict=True)
            resolved_target = target.resolve(strict=True)
        except OSError:
            raise SnapshotError("unsafe_cleanup_path") from None
        if resolved_target == resolved_parent or resolved_target.parent != resolved_parent:
            raise SnapshotError("unsafe_cleanup_path")
        return target

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _hash_stable_path(
        cls,
        path: Path,
        expected_stat: os.stat_result,
    ) -> str:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            descriptor_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_dev != expected_stat.st_dev
                or descriptor_stat.st_ino != expected_stat.st_ino
                or descriptor_stat.st_size != expected_stat.st_size
            ):
                raise OSError
            with os.fdopen(descriptor, "rb", closefd=False) as media_file:
                sha256 = cls._hash_file(media_file)
            final_path_stat = path.lstat()
            if (
                stat.S_ISLNK(final_path_stat.st_mode)
                or not stat.S_ISREG(final_path_stat.st_mode)
                or final_path_stat.st_dev != descriptor_stat.st_dev
                or final_path_stat.st_ino != descriptor_stat.st_ino
                or final_path_stat.st_size != descriptor_stat.st_size
            ):
                raise OSError
            return sha256
        finally:
            os.close(descriptor)

    @staticmethod
    def _hash_file(media_file: BinaryIO) -> str:
        digest = hashlib.sha256()
        media_file.seek(0)
        for chunk in iter(lambda: media_file.read(1024 * 1024), b""):
            digest.update(chunk)
        media_file.seek(0)
        return digest.hexdigest()
