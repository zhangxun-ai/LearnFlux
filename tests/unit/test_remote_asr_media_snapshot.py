from __future__ import annotations

import hashlib
import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from video_transcript_api.transcriber.media_preparer import (
    ASRMediaPreparer,
    PreparedASRMedia,
)
from video_transcript_api.transcriber.media_snapshot import (
    MediaSnapshotter,
    SnapshotError,
)


def _prepared_m4a(
    tmp_path: Path,
    *,
    task_id: str = "task-1",
    content: bytes = b"aac-media",
) -> tuple[Path, PreparedASRMedia]:
    temp_root = tmp_path / "private-temp"
    source = tmp_path / "source.m4a"
    source.write_bytes(content)

    prepared = ASRMediaPreparer(
        temp_root,
        probe=lambda _path: {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "44100",
                    "channels": 2,
                }
            ],
            "format": {"format_name": "mov,mp4,m4a", "duration": "2.5"},
        },
    ).prepare(source, task_id)
    return temp_root, prepared


def _snapshotter(temp_root: Path) -> MediaSnapshotter:
    return MediaSnapshotter(temp_root)


def test_promote_copies_m4a_to_attempt_without_hard_link(tmp_path: Path):
    temp_root, prepared = _prepared_m4a(tmp_path)

    snapshot = _snapshotter(temp_root).promote(
        prepared,
        task_id="task-1",
        attempt_no=1,
        expected_sha256=prepared.sha256,
        create=True,
    )

    assert snapshot.path.name == "input.m4a"
    assert snapshot.media_format == "m4a"
    assert snapshot.sha256 == prepared.sha256
    assert snapshot.path.read_bytes() == prepared.path.read_bytes()
    assert snapshot.path.stat().st_ino != prepared.path.stat().st_ino
    assert prepared.path.exists()


def test_find_attempt_accepts_exactly_one_allowlisted_file(tmp_path: Path):
    temp_root, prepared = _prepared_m4a(tmp_path)
    snapshotter = _snapshotter(temp_root)
    promoted = snapshotter.promote(
        prepared,
        task_id="task-1",
        attempt_no=1,
        expected_sha256=prepared.sha256,
        create=True,
    )
    recovered = snapshotter.find_attempt(
        task_id="task-1",
        attempt_no=1,
        expected_sha256=prepared.sha256,
        duration_seconds=prepared.duration_seconds,
    )

    assert recovered.path == promoted.path
    assert recovered.media_format == "m4a"

    (promoted.path.parent / "input.mp3").write_bytes(b"conflict")
    with pytest.raises(SnapshotError, match="^media_identity_conflict$"):
        snapshotter.find_attempt(
            task_id="task-1",
            attempt_no=1,
            expected_sha256=prepared.sha256,
            duration_seconds=prepared.duration_seconds,
        )


def test_promote_never_replaces_final_created_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    temp_root, prepared = _prepared_m4a(tmp_path)
    task_hash = hashlib.sha256(b"task-1").hexdigest()
    final_path = temp_root / "remote_asr" / task_hash / "1" / "input.m4a"
    conflicting_bytes = b"racing-conflict"
    original_link = os.link

    def create_conflict_before_link(source, destination, *args, **kwargs):
        Path(destination).write_bytes(conflicting_bytes)
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", create_conflict_before_link)

    with pytest.raises(SnapshotError, match="^media_identity_conflict$"):
        _snapshotter(temp_root).promote(
            prepared,
            task_id="task-1",
            attempt_no=1,
            expected_sha256=prepared.sha256,
            create=True,
        )

    assert final_path.read_bytes() == conflicting_bytes
    assert prepared.path.exists()
    assert not list(final_path.parent.glob("input.tmp.*"))


def test_partial_copy_never_replaces_or_deletes_quote_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    temp_root, prepared = _prepared_m4a(tmp_path)
    original_bytes = prepared.path.read_bytes()

    def fail_after_partial_copy(source, destination, length):
        destination.write(source.read(2))
        raise OSError("injected copy failure")

    monkeypatch.setattr(shutil, "copyfileobj", fail_after_partial_copy)
    snapshotter = _snapshotter(temp_root)

    with pytest.raises(SnapshotError, match="^media_promotion_failed$"):
        snapshotter.promote(
            prepared,
            task_id="task-1",
            attempt_no=1,
            expected_sha256=prepared.sha256,
            create=True,
        )

    task_hash = hashlib.sha256(b"task-1").hexdigest()
    attempt_dir = temp_root / "remote_asr" / task_hash / "1"
    assert prepared.path.read_bytes() == original_bytes
    assert not list(attempt_dir.glob("input.*"))


def test_verified_upload_uses_same_fd_and_detects_real_media_change(
    tmp_path: Path,
):
    temp_root, prepared = _prepared_m4a(tmp_path, content=b"stable-aac-media")
    snapshotter = _snapshotter(temp_root)
    snapshot = snapshotter.promote(
        prepared,
        task_id="task-1",
        attempt_no=1,
        expected_sha256=prepared.sha256,
        create=True,
    )

    with snapshotter.open_for_upload(snapshot) as handle:
        snapshotter.verify_unchanged(handle)
        assert handle.file.read() == b"stable-aac-media"
        replacement = snapshot.path.parent / "replacement.m4a"
        replacement.write_bytes(b"stable-aac-media")
        replacement.chmod(0o400)
        os.replace(replacement, snapshot.path)
        assert snapshot.path.stat().st_ino != handle.inode

        with pytest.raises(SnapshotError, match="^media_changed_before_submit$"):
            snapshotter.verify_unchanged(handle)
        assert handle.file.tell() == 0

    assert handle.file.closed
