import os
import time

from video_transcript_api.utils.tempfile_manager import TempFileManager


def test_old_cleanup_protects_only_valid_contained_root_and_keeps_sibling_scope(tmp_path):
    manager = TempFileManager(tmp_path / "temp")
    protected = manager.base_dir / "remote_asr" / "task" / "1"
    sibling = manager.base_dir / "remote_asr" / "task" / "2"
    protected.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (protected / "input.flac").write_bytes(b"keep")
    (sibling / "input.flac").write_bytes(b"delete")
    old = time.time() - 48 * 3600
    for path in (protected, sibling, protected / "input.flac", sibling / "input.flac"):
        os.utime(path, (old, old))

    cleaned = manager.clean_up_old_files(
        hours=24, protected_roots={protected}
    )

    assert cleaned >= 1
    assert (protected / "input.flac").exists()
    assert not sibling.exists()
