"""Prepare one verified, private media file for cloud ASR."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal


PreparedMediaFormat = Literal["flac", "mp3", "m4a", "wav"]
PreparationKind = Literal["reused", "demuxed", "transcoded"]

_SAFE_ERROR_CODES = frozenset(
    {
        "invalid_source_media",
        "media_probe_failed",
        "audio_stream_missing",
        "media_demux_failed",
        "media_transcode_failed",
        "prepared_media_too_large",
        "prepared_media_too_long",
        "media_identity_mismatch",
    }
)
_HASH_CHUNK_BYTES = 1024 * 1024
_HARD_MAX_DURATION_SECONDS = Decimal("43200")
_HARD_MAX_SIZE_BYTES = 2 * 1024**3

Runner = Callable[..., subprocess.CompletedProcess[Any]]
Probe = Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class _MediaProfile:
    suffix: str
    muxer: str
    codec: str
    codec_is_prefix: bool
    direct_containers: frozenset[str]

    def accepts_codec(self, codec_name: str) -> bool:
        if self.codec_is_prefix:
            return codec_name.startswith(self.codec)
        return codec_name == self.codec


_MEDIA_PROFILES: Mapping[PreparedMediaFormat, _MediaProfile] = MappingProxyType(
    {
        "flac": _MediaProfile(
            suffix=".flac",
            muxer="flac",
            codec="flac",
            codec_is_prefix=False,
            direct_containers=frozenset({"flac"}),
        ),
        "mp3": _MediaProfile(
            suffix=".mp3",
            muxer="mp3",
            codec="mp3",
            codec_is_prefix=False,
            direct_containers=frozenset({"mp3"}),
        ),
        "m4a": _MediaProfile(
            suffix=".m4a",
            muxer="ipod",
            codec="aac",
            codec_is_prefix=False,
            direct_containers=frozenset(
                {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}
            ),
        ),
        "wav": _MediaProfile(
            suffix=".wav",
            muxer="wav",
            codec="pcm_",
            codec_is_prefix=True,
            direct_containers=frozenset({"wav"}),
        ),
    }
)
MEDIA_SUFFIXES: Mapping[PreparedMediaFormat, str] = MappingProxyType(
    {
        media_format: profile.suffix
        for media_format, profile in _MEDIA_PROFILES.items()
    }
)
_SUFFIX_FORMATS: Mapping[str, PreparedMediaFormat] = MappingProxyType(
    {profile.suffix: media_format for media_format, profile in _MEDIA_PROFILES.items()}
)


@dataclass(frozen=True, slots=True)
class PreparedASRMedia:
    """Immutable identity of media ready for cloud ASR."""

    path: Path
    media_format: PreparedMediaFormat
    duration_seconds: Decimal
    size_bytes: int
    sha256: str
    preparation: PreparationKind


class MediaPreparationError(RuntimeError):
    """A media preparation failure containing only a stable safe code."""

    def __init__(self, code: str) -> None:
        safe_code = code if code in _SAFE_ERROR_CODES else "media_probe_failed"
        self.code = safe_code
        super().__init__(safe_code)


@dataclass(slots=True)
class _StableRegularFile:
    path: Path
    descriptor: int
    device: int
    inode: int
    size_bytes: int

    @classmethod
    def open(cls, path: Path) -> "_StableRegularFile":
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OSError
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            descriptor_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_dev != path_stat.st_dev
                or descriptor_stat.st_ino != path_stat.st_ino
            ):
                raise OSError
            return cls(
                path=path,
                descriptor=descriptor,
                device=descriptor_stat.st_dev,
                inode=descriptor_stat.st_ino,
                size_bytes=descriptor_stat.st_size,
            )
        except Exception:
            os.close(descriptor)
            raise

    def __enter__(self) -> "_StableRegularFile":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        os.close(self.descriptor)

    @property
    def tool_path(self) -> Path:
        return Path(f"/dev/fd/{self.descriptor}")

    def rewind(self) -> None:
        os.lseek(self.descriptor, 0, os.SEEK_SET)

    def still_matches_path(self) -> bool:
        path_stat = self.path.lstat()
        return (
            not stat.S_ISLNK(path_stat.st_mode)
            and stat.S_ISREG(path_stat.st_mode)
            and path_stat.st_dev == self.device
            and path_stat.st_ino == self.inode
            and path_stat.st_size == self.size_bytes
        )


@dataclass(frozen=True, slots=True)
class _SourceProbe:
    """The single normalized representation of FFprobe JSON in this module."""

    first_audio_codec: str | None
    audio_stream_count: int
    video_stream_count: int
    format_names: frozenset[str]
    duration_seconds: Decimal
    sample_rate: int | None
    channels: int | None

    @classmethod
    def from_ffprobe_json(cls, payload: Mapping[str, Any]) -> "_SourceProbe":
        streams = payload.get("streams")
        media_format = payload.get("format")
        if not isinstance(streams, list) or not isinstance(media_format, Mapping):
            raise ValueError

        audio_streams = [
            stream
            for stream in streams
            if isinstance(stream, Mapping) and stream.get("codec_type") == "audio"
        ]
        video_stream_count = sum(
            1
            for stream in streams
            if isinstance(stream, Mapping) and stream.get("codec_type") == "video"
        )
        first_audio = audio_streams[0] if audio_streams else None
        codec_value = first_audio.get("codec_name") if first_audio is not None else None
        codec = (
            codec_value.strip().lower()
            if isinstance(codec_value, str) and codec_value.strip()
            else None
        )

        raw_format_names = media_format.get("format_name")
        if not isinstance(raw_format_names, str):
            raise ValueError
        format_names = frozenset(
            name.strip().lower()
            for name in raw_format_names.split(",")
            if name.strip()
        )
        if not format_names:
            raise ValueError

        raw_duration = media_format.get("duration")
        if raw_duration is None and first_audio is not None:
            raw_duration = first_audio.get("duration")
        try:
            duration = Decimal(str(raw_duration))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError from None

        return cls(
            first_audio_codec=codec,
            audio_stream_count=len(audio_streams),
            video_stream_count=video_stream_count,
            format_names=format_names,
            duration_seconds=duration,
            sample_rate=_optional_positive_int(
                first_audio.get("sample_rate") if first_audio is not None else None
            ),
            channels=_optional_positive_int(
                first_audio.get("channels") if first_audio is not None else None
            ),
        )


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _direct_profile_for(
    codec_name: str | None, format_names: Collection[str]
) -> PreparedMediaFormat | None:
    if codec_name is None:
        return None
    for media_format, profile in _MEDIA_PROFILES.items():
        if profile.accepts_codec(codec_name) and profile.direct_containers.intersection(
            format_names
        ):
            return media_format
    return None


def _stream_copy_profile_for(codec_name: str | None) -> PreparedMediaFormat | None:
    if codec_name is None:
        return None
    for media_format, profile in _MEDIA_PROFILES.items():
        if profile.accepts_codec(codec_name):
            return media_format
    return None


class ASRMediaPreparer:
    """Create and verify one allowlisted cloud-ASR media artifact."""

    def __init__(
        self,
        temp_root: str | Path,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        runner: Runner = subprocess.run,
        probe: Probe | None = None,
        max_duration_seconds: Decimal | int = Decimal("43200"),
        max_size_bytes: int = 2 * 1024**3,
    ) -> None:
        try:
            configured_duration = Decimal(str(max_duration_seconds))
            if (
                not configured_duration.is_finite()
                or configured_duration <= 0
                or isinstance(max_size_bytes, bool)
                or not isinstance(max_size_bytes, int)
                or max_size_bytes <= 0
            ):
                raise ValueError
            self.temp_root = Path(temp_root)
        except Exception:
            raise MediaPreparationError("media_probe_failed") from None
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self._runner = runner
        self._probe = probe
        self.max_duration_seconds = min(
            configured_duration, _HARD_MAX_DURATION_SECONDS
        )
        self.max_size_bytes = min(max_size_bytes, _HARD_MAX_SIZE_BYTES)
        self._owned_candidate_dirs: set[Path] = set()

    def prepare(self, source_path: str | Path, task_id: str) -> PreparedASRMedia:
        """Prepare the first audio stream without modifying the source file."""
        try:
            source = Path(source_path)
            source_file = _StableRegularFile.open(source)
        except Exception:
            raise MediaPreparationError("invalid_source_media") from None
        with source_file:
            return self._prepare_open_source(source_file, task_id)

    def _prepare_open_source(
        self,
        source: _StableRegularFile,
        task_id: str,
    ) -> PreparedASRMedia:
        source_probe = self._probe_file(source)
        if (
            source_probe.audio_stream_count == 0
            or source_probe.first_audio_codec is None
        ):
            raise MediaPreparationError("audio_stream_missing")

        candidate_dir = self._create_candidate_dir(task_id)
        direct_format = _direct_profile_for(
            source_probe.first_audio_codec, source_probe.format_names
        )
        stream_copy_format = _stream_copy_profile_for(
            source_probe.first_audio_codec
        )

        try:
            if (
                source_probe.video_stream_count == 0
                and source_probe.audio_stream_count == 1
                and direct_format is not None
            ):
                final_path = self._copy_source(source, candidate_dir, direct_format)
                preparation: PreparationKind = "reused"
                media_format = direct_format
            elif stream_copy_format is not None:
                try:
                    final_path = self._run_ffmpeg(
                        source, candidate_dir, stream_copy_format, codec="copy"
                    )
                    preparation = "demuxed"
                    media_format = stream_copy_format
                except Exception:
                    self._remove_candidate_files(candidate_dir)
                    try:
                        final_path = self._run_ffmpeg(
                            source, candidate_dir, "flac", codec="flac"
                        )
                    except Exception:
                        raise MediaPreparationError(
                            "media_transcode_failed"
                        ) from None
                    preparation = "transcoded"
                    media_format = "flac"
            else:
                try:
                    final_path = self._run_ffmpeg(
                        source, candidate_dir, "flac", codec="flac"
                    )
                except Exception:
                    raise MediaPreparationError("media_transcode_failed") from None
                preparation = "transcoded"
                media_format = "flac"

            prepared = self._validate_prepared(
                final_path,
                media_format,
                preparation,
                mismatch_code="media_probe_failed",
            )
            self._register_owned(prepared, mismatch_code="media_probe_failed")
            return prepared
        except MediaPreparationError:
            self._cleanup_candidate_dir(candidate_dir)
            raise
        except Exception:
            self._cleanup_candidate_dir(candidate_dir)
            raise MediaPreparationError("media_probe_failed") from None

    def verify_existing(
        self,
        path: str | Path,
        expected_sha256: str,
        expected_duration: Decimal | int | str,
    ) -> PreparedASRMedia:
        """Verify retained media identity without invoking FFmpeg."""
        try:
            media_path = Path(path)
            media_format = _SUFFIX_FORMATS.get(media_path.suffix.lower())
            if media_format is None:
                raise MediaPreparationError("media_identity_mismatch")
            candidate_dir = self._validated_candidate_dir(
                media_path, media_format
            )
            prepared = self._validate_prepared(
                media_path,
                media_format,
                "reused",
                mismatch_code="media_identity_mismatch",
            )
            expected_duration_decimal = Decimal(str(expected_duration))
            if (
                prepared.sha256 != expected_sha256
                or prepared.duration_seconds != expected_duration_decimal
            ):
                raise MediaPreparationError("media_identity_mismatch")
            self._owned_candidate_dirs.add(candidate_dir)
            return prepared
        except MediaPreparationError as error:
            if error.code in {
                "prepared_media_too_large",
                "prepared_media_too_long",
            }:
                raise
            raise MediaPreparationError("media_identity_mismatch")
        except Exception:
            raise MediaPreparationError("media_identity_mismatch") from None

    def cleanup(self, prepared: PreparedASRMedia) -> None:
        """Delete only an owned random quote directory beneath ``cloud_quotes``."""
        try:
            if not isinstance(prepared, PreparedASRMedia):
                return
            candidate_key = prepared.path.parent.resolve(strict=False)
            if (
                candidate_key in self._owned_candidate_dirs
                and not os.path.lexists(candidate_key)
            ):
                self._owned_candidate_dirs.discard(candidate_key)
                return
            candidate_dir = self._validated_candidate_dir(
                prepared.path, prepared.media_format
            )
            if candidate_dir not in self._owned_candidate_dirs:
                return
            if self._cleanup_candidate_dir(candidate_dir):
                self._owned_candidate_dirs.discard(candidate_dir)
        except Exception:
            return

    def _probe_file(self, media_file: _StableRegularFile) -> _SourceProbe:
        try:
            media_file.rewind()
        except Exception:
            raise MediaPreparationError("media_probe_failed") from None
        return self._probe_path(
            media_file.tool_path,
            pass_fd=media_file.descriptor,
        )

    def _probe_path(self, path: Path, *, pass_fd: int | None = None) -> _SourceProbe:
        try:
            payload = (
                self._probe(path)
                if self._probe is not None
                else self._probe_with_ffprobe(path, pass_fd=pass_fd)
            )
            return _SourceProbe.from_ffprobe_json(payload)
        except Exception:
            raise MediaPreparationError("media_probe_failed") from None

    def _probe_with_ffprobe(
        self,
        path: Path,
        *,
        pass_fd: int | None,
    ) -> Mapping[str, Any]:
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            (
                "stream=codec_type,codec_name,sample_rate,channels,duration:"
                "format=format_name,duration"
            ),
            "-of",
            "json",
            str(path),
        ]
        runner_kwargs: dict[str, Any] = {
            "check": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if pass_fd is not None:
            runner_kwargs["pass_fds"] = (pass_fd,)
        result = self._runner(command, **runner_kwargs)
        if result.returncode != 0:
            raise ValueError
        raw_output = result.stdout
        if isinstance(raw_output, bytes):
            raw_output = raw_output.decode("utf-8")
        payload = json.loads(raw_output)
        if not isinstance(payload, Mapping):
            raise ValueError
        return payload

    def _create_candidate_dir(self, task_id: str) -> Path:
        candidate_dir: Path | None = None
        try:
            task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
            cloud_root = self.temp_root / "cloud_quotes"
            task_root = cloud_root / task_hash
            self.temp_root.mkdir(parents=True, exist_ok=True)
            temp_root_stat = self.temp_root.lstat()
            if stat.S_ISLNK(temp_root_stat.st_mode) or not stat.S_ISDIR(
                temp_root_stat.st_mode
            ):
                raise OSError
            self._ensure_private_directory(cloud_root)
            self._ensure_private_directory(task_root)
            candidate_dir = Path(tempfile.mkdtemp(prefix="quote-", dir=task_root))
            candidate_dir.chmod(0o700)
            return candidate_dir
        except Exception:
            if candidate_dir is not None:
                self._cleanup_candidate_dir(candidate_dir)
            raise MediaPreparationError("invalid_source_media") from None

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        try:
            path.mkdir()
        except FileExistsError:
            pass
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
            raise OSError
        path.chmod(0o700)

    def _copy_source(
        self,
        source: _StableRegularFile,
        candidate_dir: Path,
        media_format: PreparedMediaFormat,
    ) -> Path:
        temporary_path, final_path = self._candidate_paths(
            candidate_dir, media_format
        )
        try:
            source.rewind()
            with temporary_path.open("xb") as output:
                while chunk := os.read(source.descriptor, _HASH_CHUNK_BYTES):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            self._publish_candidate(temporary_path, final_path)
            return final_path
        except Exception:
            raise MediaPreparationError("invalid_source_media") from None

    def _run_ffmpeg(
        self,
        source: _StableRegularFile,
        candidate_dir: Path,
        media_format: PreparedMediaFormat,
        *,
        codec: Literal["copy", "flac"],
    ) -> Path:
        temporary_path, final_path = self._candidate_paths(
            candidate_dir, media_format
        )
        source.rewind()
        command = [
            self.ffmpeg_binary,
            "-nostdin",
            "-y",
            "-i",
            str(source.tool_path),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            codec,
            "-f",
            _MEDIA_PROFILES[media_format].muxer,
            str(temporary_path),
        ]
        result = self._runner(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(source.descriptor,),
        )
        if result.returncode != 0:
            raise OSError
        self._publish_candidate(temporary_path, final_path)
        return final_path

    @staticmethod
    def _candidate_paths(
        candidate_dir: Path, media_format: PreparedMediaFormat
    ) -> tuple[Path, Path]:
        suffix = MEDIA_SUFFIXES[media_format]
        return candidate_dir / f"input.tmp{suffix}", candidate_dir / f"input{suffix}"

    def _publish_candidate(self, temporary_path: Path, final_path: Path) -> None:
        temporary_stat = temporary_path.lstat()
        if (
            stat.S_ISLNK(temporary_stat.st_mode)
            or not stat.S_ISREG(temporary_stat.st_mode)
            or temporary_stat.st_size <= 0
        ):
            raise OSError
        self._fsync_file(temporary_path)
        os.replace(temporary_path, final_path)
        final_path.chmod(0o400)
        self._fsync_file(final_path)
        self._fsync_directory(final_path.parent)

    def _validate_prepared(
        self,
        path: Path,
        media_format: PreparedMediaFormat,
        preparation: PreparationKind,
        *,
        mismatch_code: str,
    ) -> PreparedASRMedia:
        try:
            media_file = _StableRegularFile.open(path)
        except Exception:
            raise MediaPreparationError(mismatch_code) from None
        with media_file:
            if media_file.size_bytes <= 0:
                raise MediaPreparationError(mismatch_code)
            if media_file.size_bytes > self.max_size_bytes:
                raise MediaPreparationError("prepared_media_too_large")

            probe = self._probe_file(media_file)
            if (
                probe.audio_stream_count != 1
                or probe.video_stream_count != 0
                or _direct_profile_for(
                    probe.first_audio_codec, probe.format_names
                )
                != media_format
            ):
                raise MediaPreparationError(mismatch_code)
            duration = probe.duration_seconds
            if not duration.is_finite() or duration <= 0:
                raise MediaPreparationError(mismatch_code)
            if duration > self.max_duration_seconds:
                raise MediaPreparationError("prepared_media_too_long")
            try:
                sha256 = self._hash_file(media_file)
                if not media_file.still_matches_path():
                    raise OSError
            except Exception:
                raise MediaPreparationError(mismatch_code) from None
        return PreparedASRMedia(
            path=path,
            media_format=media_format,
            duration_seconds=duration,
            size_bytes=media_file.size_bytes,
            sha256=sha256,
            preparation=preparation,
        )

    @staticmethod
    def _hash_file(media_file: _StableRegularFile) -> str:
        digest = hashlib.sha256()
        media_file.rewind()
        while chunk := os.read(media_file.descriptor, _HASH_CHUNK_BYTES):
            digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fsync_file(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove_candidate_files(candidate_dir: Path) -> None:
        for suffix in MEDIA_SUFFIXES.values():
            for name in (f"input.tmp{suffix}", f"input{suffix}"):
                try:
                    (candidate_dir / name).unlink()
                except FileNotFoundError:
                    pass

    def _register_owned(
        self,
        prepared: PreparedASRMedia,
        *,
        mismatch_code: str,
    ) -> None:
        try:
            candidate_dir = self._validated_candidate_dir(
                prepared.path, prepared.media_format
            )
        except Exception:
            raise MediaPreparationError(mismatch_code) from None
        self._owned_candidate_dirs.add(candidate_dir)

    def _validated_candidate_dir(
        self,
        path: Path,
        media_format: PreparedMediaFormat,
    ) -> Path:
        profile = _MEDIA_PROFILES.get(media_format)
        if profile is None or path.name != f"input{profile.suffix}":
            raise ValueError
        candidate_dir = self._validated_candidate_structure(path.parent)
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise ValueError
        if path.resolve(strict=True).parent != candidate_dir:
            raise ValueError
        return candidate_dir

    def _validated_candidate_structure(self, candidate_dir: Path) -> Path:
        temp_root = self.temp_root.absolute()
        cloud_root = (self.temp_root / "cloud_quotes").absolute()
        resolved_temp_root = temp_root.resolve(strict=True)
        resolved_cloud_root = cloud_root.resolve(strict=True)
        resolved_candidate = candidate_dir.resolve(strict=True)
        relative = resolved_candidate.relative_to(resolved_cloud_root)
        if len(relative.parts) != 2:
            raise ValueError
        task_hash, random_name = relative.parts
        if (
            len(task_hash) != 64
            or any(character not in "0123456789abcdef" for character in task_hash)
            or not random_name.startswith("quote-")
        ):
            raise ValueError

        task_root = cloud_root / task_hash
        lexical_candidate = task_root / random_name
        for directory in (temp_root, cloud_root, task_root, lexical_candidate):
            directory_stat = directory.lstat()
            if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(
                directory_stat.st_mode
            ):
                raise ValueError

        if resolved_cloud_root.parent != resolved_temp_root:
            raise ValueError
        if lexical_candidate.resolve(strict=True) != resolved_candidate:
            raise ValueError
        return resolved_candidate

    def _cleanup_candidate_dir(self, candidate_dir: Path) -> bool:
        try:
            if not os.path.lexists(candidate_dir):
                return True
        except Exception:
            return False
        try:
            validated_dir = self._validated_candidate_structure(candidate_dir)
        except Exception:
            return False
        try:
            shutil.rmtree(validated_dir)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return not os.path.lexists(validated_dir)
