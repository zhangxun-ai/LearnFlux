from pathlib import Path


def test_study_source_path_uses_safe_extension(tmp_path):
    from video_transcript_api.study.source_files import build_study_source_path

    path = build_study_source_path(
        source_root=tmp_path,
        media_id="local_abc123",
        filename="lesson.final.version.mp4",
    )

    assert path == tmp_path / "study_uploads" / "local_abc123.mp4"


def test_study_source_path_falls_back_to_bin_for_unsafe_extension(tmp_path):
    from video_transcript_api.study.source_files import build_study_source_path

    path = build_study_source_path(
        source_root=tmp_path,
        media_id="local_abc123",
        filename="lesson.verylongextension",
    )

    assert path == tmp_path / "study_uploads" / "local_abc123.bin"


def test_media_type_for_common_video_files():
    from video_transcript_api.study.source_files import media_type_for_filename

    assert media_type_for_filename("demo.mp4") == "video/mp4"
    assert media_type_for_filename("demo.webm") == "video/webm"
    assert media_type_for_filename("demo.mov") == "video/quicktime"
    assert media_type_for_filename("demo.mkv") == "video/x-matroska"


def test_find_study_source_file_resolves_existing_local_url(tmp_path):
    from video_transcript_api.study.source_files import build_study_source_path, find_study_source_file

    source = build_study_source_path(tmp_path, "local_abc123", "lesson.mp4")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")

    resolved = find_study_source_file(
        source_root=tmp_path,
        media_id="local_abc123",
        title="lesson.mp4",
        url="local://study-source/local_abc123/lesson.mp4",
    )

    assert resolved == source
