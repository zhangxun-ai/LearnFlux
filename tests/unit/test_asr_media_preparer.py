from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import video_transcript_api.transcriber.media_preparer as media_preparer_module
from video_transcript_api.transcriber.media_preparer import (
    ASRMediaPreparer,
    MediaPreparationError,
)


ProbePayload = Mapping[str, Any]


def _probe_payload(
    *,
    codec: str,
    container: str,
    audio_streams: int = 1,
    video_streams: int = 0,
    duration: str = "12.5",
) -> dict[str, Any]:
    streams = [
        {
            "codec_type": "audio",
            "codec_name": codec,
            "sample_rate": "48000",
            "channels": 2,
        }
        for _ in range(audio_streams)
    ]
    streams.extend(
        {"codec_type": "video", "codec_name": "h264"}
        for _ in range(video_streams)
    )
    return {
        "streams": streams,
        "format": {"format_name": container, "duration": duration},
    }


def _queued_probe(
    *payloads: ProbePayload | Exception,
) -> Callable[[Path], ProbePayload]:
    remaining = list(payloads)

    def probe(_path: Path) -> ProbePayload:
        result = remaining.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return probe


def _writing_runner(commands: list[list[str]]):
    def runner(command: list[str], **_kwargs: Any):
        commands.append(command)
        Path(command[-1]).write_bytes(b"prepared-media")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    return runner


def test_supported_single_track_flac_is_copied_without_ffmpeg(tmp_path: Path):
    source = tmp_path / "lesson.flac"
    source.write_bytes(b"source-flac")
    commands: list[list[str]] = []
    flac_probe = _probe_payload(codec="flac", container="flac")
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        runner=_writing_runner(commands),
        probe=_queued_probe(flac_probe, flac_probe),
    )

    prepared = preparer.prepare(source, "task-1")

    assert prepared.media_format == "flac"
    assert prepared.preparation == "reused"
    assert prepared.path.name == "input.flac"
    assert prepared.path.read_bytes() == source.read_bytes()
    assert commands == []


def test_source_replacement_after_probe_does_not_change_prepared_inode(
    tmp_path: Path,
):
    source = tmp_path / "lesson.flac"
    original = b"original-inode"
    replacement = b"replacement-inode"
    source.write_bytes(original)
    flac_probe = _probe_payload(codec="flac", container="flac")
    probe_calls = 0

    def probe(probed_path: Path) -> ProbePayload:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 1:
            assert probed_path.read_bytes() == original
            source.unlink()
            source.write_bytes(replacement)
        return flac_probe

    prepared = ASRMediaPreparer(
        tmp_path / "private",
        probe=probe,
    ).prepare(source, "task-stable-source")

    assert source.read_bytes() == replacement
    assert prepared.path.read_bytes() == original


def test_aac_video_uses_one_stream_copy_without_transcode(tmp_path: Path):
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"source-video")
    commands: list[list[str]] = []
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        runner=_writing_runner(commands),
        probe=_queued_probe(
            _probe_payload(
                codec="aac",
                container="mov,mp4,m4a,3gp,3g2,mj2",
                video_streams=1,
            ),
            _probe_payload(
                codec="aac", container="mov,mp4,m4a,3gp,3g2,mj2"
            ),
        ),
    )

    prepared = preparer.prepare(source, "task-2")

    assert prepared.media_format == "m4a"
    assert prepared.preparation == "demuxed"
    assert prepared.path.name == "input.m4a"
    assert len(commands) == 1
    assert commands[0][commands[0].index("-c:a") + 1] == "copy"
    assert commands[0][commands[0].index("-map") + 1] == "0:a:0"
    assert "-vn" in commands[0]


def test_unsupported_opus_transcodes_to_flac_exactly_once(tmp_path: Path):
    source = tmp_path / "lesson.webm"
    source.write_bytes(b"source-opus")
    commands: list[list[str]] = []
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        runner=_writing_runner(commands),
        probe=_queued_probe(
            _probe_payload(codec="opus", container="matroska,webm"),
            _probe_payload(codec="flac", container="flac"),
        ),
    )

    prepared = preparer.prepare(source, "task-3")

    assert prepared.media_format == "flac"
    assert prepared.preparation == "transcoded"
    assert prepared.path.name == "input.flac"
    assert len(commands) == 1
    assert commands[0][commands[0].index("-c:a") + 1] == "flac"
    assert "-ar" not in commands[0]
    assert "-ac" not in commands[0]


def test_failed_stream_copy_cleans_partial_and_falls_back_to_flac_once(
    tmp_path: Path,
):
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"source-video")
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: Any):
        commands.append(command)
        output = Path(command[-1])
        output.write_bytes(b"partial" if len(commands) == 1 else b"flac")
        if len(commands) == 1:
            raise subprocess.CalledProcessError(1, command, stderr=b"private")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    prepared = ASRMediaPreparer(
        tmp_path / "private",
        runner=runner,
        probe=_queued_probe(
            _probe_payload(
                codec="aac",
                container="mov,mp4,m4a,3gp,3g2,mj2",
                video_streams=1,
            ),
            _probe_payload(codec="flac", container="flac"),
        ),
    ).prepare(source, "task-copy-fallback")

    assert [command[command.index("-c:a") + 1] for command in commands] == [
        "copy",
        "flac",
    ]
    assert prepared.preparation == "transcoded"
    assert prepared.path.name == "input.flac"
    assert not list(prepared.path.parent.glob("*.m4a"))


def test_failed_final_validation_cleans_only_owned_candidate(tmp_path: Path):
    source = tmp_path / "keep-source.webm"
    source.write_bytes(b"source-opus")
    outside_sentinel = tmp_path / "keep-outside"
    outside_sentinel.write_text("outside", encoding="utf-8")
    task_id = "task-4"
    task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    task_root = tmp_path / "private" / "cloud_quotes" / task_hash
    sibling = task_root / "keep-sibling"
    sibling.mkdir(parents=True)
    sibling_sentinel = sibling / "sentinel"
    sibling_sentinel.write_text("sibling", encoding="utf-8")
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        runner=_writing_runner([]),
        probe=_queued_probe(
            _probe_payload(codec="opus", container="matroska,webm"),
            RuntimeError("private probe detail"),
        ),
    )

    with pytest.raises(MediaPreparationError, match="^media_probe_failed$"):
        preparer.prepare(source, task_id)

    assert source.read_bytes() == b"source-opus"
    assert outside_sentinel.read_text(encoding="utf-8") == "outside"
    assert sibling_sentinel.read_text(encoding="utf-8") == "sibling"
    assert not list(task_root.glob("*/input.*"))


def test_verify_existing_rejects_suffix_probe_profile_mismatch(tmp_path: Path):
    task_hash = hashlib.sha256(b"task-profile").hexdigest()
    candidate_dir = (
        tmp_path / "private" / "cloud_quotes" / task_hash / "quote-profile"
    )
    candidate_dir.mkdir(parents=True)
    path = candidate_dir / "input.flac"
    contents = b"retained-media"
    path.write_bytes(contents)
    commands: list[list[str]] = []
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        runner=_writing_runner(commands),
        probe=_queued_probe(
            _probe_payload(codec="aac", container="mov,mp4,m4a,3gp,3g2,mj2")
        ),
    )

    with pytest.raises(MediaPreparationError, match="^media_identity_mismatch$"):
        preparer.verify_existing(
            path,
            hashlib.sha256(contents).hexdigest(),
            Decimal("12.5"),
        )

    assert commands == []


def test_verify_existing_rejects_outside_path_before_probe(tmp_path: Path):
    path = tmp_path / "input.flac"
    contents = b"outside-media"
    path.write_bytes(contents)
    probe_calls = 0

    def probe(_path: Path) -> ProbePayload:
        nonlocal probe_calls
        probe_calls += 1
        return _probe_payload(codec="flac", container="flac")

    preparer = ASRMediaPreparer(tmp_path / "private", probe=probe)

    with pytest.raises(MediaPreparationError, match="^media_identity_mismatch$"):
        preparer.verify_existing(
            path,
            hashlib.sha256(contents).hexdigest(),
            Decimal("12.5"),
        )

    assert probe_calls == 0


def test_configured_limits_cannot_widen_provider_hard_limits(tmp_path: Path):
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        max_duration_seconds=Decimal("99999"),
        max_size_bytes=2 * 1024**3 + 1,
    )

    assert preparer.max_duration_seconds == Decimal("43200")
    assert preparer.max_size_bytes == 2 * 1024**3


def test_verify_existing_registers_validated_candidate_for_cleanup(tmp_path: Path):
    source = tmp_path / "lesson.flac"
    source.write_bytes(b"source-flac")
    flac_probe = _probe_payload(codec="flac", container="flac")
    creator = ASRMediaPreparer(
        tmp_path / "private",
        probe=_queued_probe(flac_probe, flac_probe),
    )
    prepared = creator.prepare(source, "task-retained")
    verifier = ASRMediaPreparer(
        tmp_path / "private",
        probe=_queued_probe(flac_probe),
    )

    verified = verifier.verify_existing(
        prepared.path,
        prepared.sha256,
        prepared.duration_seconds,
    )
    verifier.cleanup(verified)

    assert not prepared.path.parent.exists()


def test_cleanup_keeps_ownership_when_removal_does_not_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "lesson.flac"
    source.write_bytes(b"source-flac")
    flac_probe = _probe_payload(codec="flac", container="flac")
    preparer = ASRMediaPreparer(
        tmp_path / "private",
        probe=_queued_probe(flac_probe, flac_probe),
    )
    prepared = preparer.prepare(source, "task-cleanup-retry")
    real_rmtree = media_preparer_module.shutil.rmtree
    removal_attempts = 0

    def skip_first_removal(path: Path, **kwargs: Any) -> None:
        nonlocal removal_attempts
        removal_attempts += 1
        if removal_attempts > 1:
            real_rmtree(path, **kwargs)

    monkeypatch.setattr(media_preparer_module.shutil, "rmtree", skip_first_removal)

    preparer.cleanup(prepared)
    assert prepared.path.exists()
    preparer.cleanup(prepared)

    assert removal_attempts == 2
    assert not prepared.path.parent.exists()


def test_cleanup_handles_symlink_alias_above_private_temp_root(tmp_path: Path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    temp_root = alias_parent / "private"
    source = tmp_path / "lesson.flac"
    source.write_bytes(b"source-flac")
    flac_probe = _probe_payload(codec="flac", container="flac")
    preparer = ASRMediaPreparer(
        temp_root,
        probe=_queued_probe(flac_probe, flac_probe),
    )
    prepared = preparer.prepare(source, "task-aliased-root")
    candidate_dir = prepared.path.parent

    assert not temp_root.is_symlink()
    preparer.cleanup(prepared)

    assert not candidate_dir.exists()
