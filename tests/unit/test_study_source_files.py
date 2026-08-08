from pathlib import Path

import pytest


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
    assert media_type_for_filename("demo.ts") == "video/mp2t"


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


@pytest.mark.parametrize(
    ("url", "filename", "media_type", "media_kind", "expected"),
    [
        ("local://study-source/id/book.pdf", "book.pdf", "", "", "document"),
        ("local://study-source/id/book.docx", "book.docx", "", "", "document"),
        ("local://study-source/id/notes.txt", "notes.txt", "", "", "document"),
        ("local://study-source/id/notes.md", "notes.md", "", "", "document"),
        ("local://study-source/id/slides.html", "slides.html", "", "", "document"),
        ("local://study-source/id/clip.mp4", "clip.mp4", "application/octet-stream", "", "video"),
        ("local://study-source/id/clip.ts", "clip.ts", "", "", "video"),
        ("local://study-source/id/lesson.mp3", "lesson.mp3", "", "", "audio"),
        ("local://study-text/id/content.md", "content.md", "text/markdown", "", "text"),
        ("https://example.test/source", "source", "application/pdf", "", "document"),
        ("https://example.test/source", "source", "text/html", "", "document"),
        ("https://example.test/source", "source", "", "video", "video"),
        ("https://example.test/source", "source", "", "", "unknown"),
    ],
)
def test_describe_study_source_classifies_supported_sources(
    url, filename, media_type, media_kind, expected
):
    from video_transcript_api.study.source_files import describe_study_source

    descriptor = describe_study_source(
        url=url,
        title=filename,
        source_file=None,
        media_type=media_type,
        media_kind=media_kind,
    )

    assert descriptor["kind"] == expected
    assert descriptor["filename"] == filename
