from pathlib import Path

from video_transcript_api.api.services.source_preservation import (
    extract_document_text,
    preserve_source_file,
    source_kind_for_path,
)


def test_preserve_source_file_uses_explicit_source_root(tmp_path):
    source_root = tmp_path / "source-files"
    downloaded = tmp_path / "video.mp4"
    downloaded.write_bytes(b"video bytes")

    saved_path = preserve_source_file(
        source_path=str(downloaded),
        source_root=source_root,
        platform="wechat_channels",
        media_id="A1kpVPJjiX",
        title="WeChat Demo",
        source_kind="video",
    )

    saved = Path(saved_path)
    assert saved.parent == source_root / "online_downloads"
    assert saved.suffix == ".mp4"
    assert saved.read_bytes() == b"video bytes"


def test_preserve_document_source_as_markdown(tmp_path):
    source_root = tmp_path / "source-files"
    downloaded = tmp_path / "article.txt"
    downloaded.write_text("# Article\n\nbody", encoding="utf-8")

    saved_path = preserve_source_file(
        source_path=str(downloaded),
        source_root=source_root,
        platform="generic",
        media_id="doc123",
        title="Article",
        source_kind="document",
    )

    saved = Path(saved_path)
    assert saved.parent == source_root / "online_downloads"
    assert saved.suffix == ".md"
    assert saved.read_text(encoding="utf-8") == "# Article\n\nbody"


def test_extract_document_text_reads_plain_text_with_fallback_encoding(tmp_path):
    source = tmp_path / "note.txt"
    source.write_bytes("中文内容".encode("gb18030"))

    assert extract_document_text(str(source), ".txt") == "中文内容"


def test_source_kind_for_path_classifies_document_video_and_media():
    assert source_kind_for_path("guide.pdf") == "document"
    assert source_kind_for_path("lesson.mp4") == "video"
    assert source_kind_for_path("archive.bin") == "media"
