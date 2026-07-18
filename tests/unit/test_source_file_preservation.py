from pathlib import Path

from video_transcript_api.api.services import transcription


def test_preserve_source_file_copies_online_video_as_mp4(tmp_path, monkeypatch):
    source_root = tmp_path / "source-files"
    downloaded = tmp_path / "downloaded.mp4"
    downloaded.write_bytes(b"video bytes")

    monkeypatch.setattr(
        transcription,
        "get_config",
        lambda: {"storage": {"source_files_dir": str(source_root)}},
    )

    saved_path = transcription._preserve_source_file(
        source_path=str(downloaded),
        platform="wechat_channels",
        media_id="A1kpVPJjiX",
        title="WeChat Demo",
        source_kind="video",
    )

    saved = Path(saved_path)
    assert saved.suffix == ".mp4"
    assert saved.read_bytes() == b"video bytes"
    assert saved.parent == source_root / "online_downloads"


def test_preserve_source_file_saves_text_document_as_markdown(tmp_path, monkeypatch):
    source_root = tmp_path / "source-files"
    downloaded = tmp_path / "article.txt"
    downloaded.write_text("# Article\n\nbody", encoding="utf-8")

    monkeypatch.setattr(
        transcription,
        "get_config",
        lambda: {"storage": {"source_files_dir": str(source_root)}},
    )

    saved_path = transcription._preserve_source_file(
        source_path=str(downloaded),
        platform="generic",
        media_id="doc123",
        title="Article",
        source_kind="document",
    )

    saved = Path(saved_path)
    assert saved.suffix == ".md"
    assert saved.read_text(encoding="utf-8") == "# Article\n\nbody"


def test_preserve_source_file_keeps_pdf_document_as_pdf(tmp_path, monkeypatch):
    source_root = tmp_path / "source-files"
    downloaded = tmp_path / "report.pdf"
    downloaded.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        transcription,
        "get_config",
        lambda: {"storage": {"source_files_dir": str(source_root)}},
    )

    saved_path = transcription._preserve_source_file(
        source_path=str(downloaded),
        platform="generic",
        media_id="pdf123",
        title="Report",
        source_kind="document",
    )

    saved = Path(saved_path)
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == b"%PDF-1.4\n"
