import hashlib
import io
import struct
import zipfile
from pathlib import Path

import pytest

from src.video_transcript_api.reading.source_files import (
    MAX_READING_UPLOAD_BYTES,
    SUPPORTED_READING_EXTS,
    ReadingSourceError,
    delete_reading_source,
    inspect_upload,
    reading_source_path,
    repair_missing_source,
    save_staged_upload,
    stage_upload,
)


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def _docx_bytes(*extra: tuple[str, bytes]) -> bytes:
    return _zip_bytes(
        [
            ("[Content_Types].xml", b"<Types />"),
            ("word/document.xml", b"<document />"),
            *extra,
        ]
    )


def _epub_bytes(*extra: tuple[str, bytes]) -> bytes:
    return _zip_bytes(
        [
            ("mimetype", b"application/epub+zip"),
            ("META-INF/container.xml", b"<container />"),
            *extra,
        ]
    )


def _mark_first_zip_entry_encrypted(payload: bytes) -> bytes:
    marked = bytearray(payload)
    local = marked.find(b"PK\x03\x04")
    central = marked.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    local_flags = struct.unpack_from("<H", marked, local + 6)[0] | 1
    central_flags = struct.unpack_from("<H", marked, central + 8)[0] | 1
    struct.pack_into("<H", marked, local + 6, local_flags)
    struct.pack_into("<H", marked, central + 8, central_flags)
    return bytes(marked)


def _inspect(tmp_path: Path, filename: str, payload: bytes, **limits):
    staged = stage_upload(io.BytesIO(payload), staging_dir=tmp_path / "staging")
    return inspect_upload(staged, filename, **limits)


@pytest.mark.parametrize(
    ("filename", "payload", "expected_format", "expected_ext"),
    [
        ("BOOK.PDF", b"%PDF-1.7\nminimal", "pdf", ".pdf"),
        ("book.epub", _epub_bytes(), "epub", ".epub"),
        ("book.docx", _docx_bytes(), "docx", ".docx"),
        ("notes.txt", "plain text\n\u4e2d\u6587".encode(), "txt", ".txt"),
        ("notes.md", b"# Heading\n\nBody", "markdown", ".md"),
        ("notes.markdown", b"# Heading", "markdown", ".markdown"),
    ],
)
def test_inspect_upload_accepts_supported_formats(
    tmp_path, filename, payload, expected_format, expected_ext
):
    inspected = _inspect(tmp_path, filename, payload)
    try:
        assert SUPPORTED_READING_EXTS == {
            ".pdf",
            ".epub",
            ".docx",
            ".txt",
            ".md",
            ".markdown",
        }
        assert inspected.format == expected_format
        assert inspected.extension == expected_ext
        assert inspected.size_bytes == len(payload)
        assert inspected.sha256 == hashlib.sha256(payload).hexdigest()
    finally:
        inspected.temp_path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("fake.pdf", b"plain text"),
        ("fake.docx", _epub_bytes()),
        ("fake.epub", _docx_bytes()),
        ("fake.txt", b"%PDF-1.7\nnot text for this extension"),
    ],
)
def test_inspect_upload_rejects_extension_disguises_and_cleans_temp(
    tmp_path, filename, payload
):
    staged = stage_upload(io.BytesIO(payload), staging_dir=tmp_path / "staging")

    with pytest.raises(ReadingSourceError) as error:
        inspect_upload(staged, filename)

    assert error.value.code == "format_mismatch"
    assert str(error.value) == "format_mismatch"
    assert not staged.temp_path.exists()


def test_stage_upload_streams_hashing_and_rejects_oversized_files(tmp_path):
    class BoundedReadStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 4
            return super().read(size)

    with pytest.raises(ReadingSourceError) as error:
        stage_upload(
            BoundedReadStream(b"123456789"),
            staging_dir=tmp_path / "staging",
            max_bytes=8,
            chunk_size=4,
        )

    assert error.value.code == "file_too_large"
    assert not list((tmp_path / "staging").glob("*"))
    assert MAX_READING_UPLOAD_BYTES > 0


def test_stage_upload_rejects_empty_file_and_cleans_temp(tmp_path):
    with pytest.raises(ReadingSourceError) as error:
        stage_upload(io.BytesIO(b""), staging_dir=tmp_path / "staging")

    assert error.value.code == "empty_file"
    assert not list((tmp_path / "staging").glob("*"))


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("binary.txt", b"hello\x00world"),
        ("binary.md", b"\xff\xfe\xfa"),
    ],
)
def test_inspect_upload_rejects_binary_text(tmp_path, filename, payload):
    staged = stage_upload(io.BytesIO(payload), staging_dir=tmp_path / "staging")

    with pytest.raises(ReadingSourceError) as error:
        inspect_upload(staged, filename)

    assert error.value.code == "format_mismatch"
    assert not staged.temp_path.exists()


def test_inspect_upload_rejects_zip_entry_count_bomb(tmp_path):
    payload = _docx_bytes(*[(f"word/{index}.xml", b"x") for index in range(3)])

    with pytest.raises(ReadingSourceError) as error:
        _inspect(tmp_path, "book.docx", payload, max_zip_entries=4)

    assert error.value.code == "unsafe_archive"


def test_inspect_upload_rejects_zip_declared_total_size_bomb(tmp_path):
    payload = _docx_bytes(("word/large.xml", b"a" * 128))

    with pytest.raises(ReadingSourceError) as error:
        _inspect(tmp_path, "book.docx", payload, max_zip_total_bytes=100)

    assert error.value.code == "unsafe_archive"


def test_inspect_upload_rejects_zip_declared_single_entry_bomb(tmp_path):
    payload = _docx_bytes(("word/large.xml", b"a" * 128))

    with pytest.raises(ReadingSourceError) as error:
        _inspect(tmp_path, "book.docx", payload, max_zip_entry_bytes=100)

    assert error.value.code == "unsafe_archive"


def test_inspect_upload_rejects_zip_compression_ratio_bomb(tmp_path):
    payload = _docx_bytes(("word/large.xml", b"a" * 10_000))

    with pytest.raises(ReadingSourceError) as error:
        _inspect(tmp_path, "book.docx", payload, max_zip_compression_ratio=10)

    assert error.value.code == "unsafe_archive"


@pytest.mark.parametrize(
    "dangerous_name",
    [
        "../escape.xml",
        "/absolute.xml",
        "..\\escape.xml",
        "safe\\..\\escape.xml",
        "C:\\absolute.xml",
    ],
)
def test_inspect_upload_rejects_zip_slip_names(tmp_path, dangerous_name):
    payload = _docx_bytes((dangerous_name, b"unsafe"))

    with pytest.raises(ReadingSourceError) as error:
        _inspect(tmp_path, "book.docx", payload)

    assert error.value.code == "unsafe_archive"


def test_inspect_upload_rejects_encrypted_zip_entries(tmp_path):
    payload = _mark_first_zip_entry_encrypted(_docx_bytes())

    with pytest.raises(ReadingSourceError) as error:
        _inspect(tmp_path, "book.docx", payload)

    assert error.value.code == "unsafe_archive"


def test_save_uses_managed_path_without_original_filename_or_owner_traversal(tmp_path):
    original_name = "private-title.pdf"
    inspected = _inspect(tmp_path, original_name, b"%PDF-1.7\nminimal")

    saved = save_staged_upload(
        inspected,
        data_root=tmp_path / "data",
        owner_user_id="../../private-owner",
        document_id="doc-123",
    )

    assert saved.read_bytes() == b"%PDF-1.7\nminimal"
    assert saved.name == "doc-123.pdf"
    assert original_name not in str(saved)
    assert "private-owner" not in str(saved)
    assert saved.parent.parent == tmp_path / "data" / "reading"
    assert not inspected.temp_path.exists()


def test_reading_source_path_rejects_untrusted_document_id_and_extension(tmp_path):
    with pytest.raises(ReadingSourceError, match="invalid_document_id"):
        reading_source_path(tmp_path, "owner", "../escape", ".pdf")
    with pytest.raises(ReadingSourceError, match="unsupported_extension"):
        reading_source_path(tmp_path, "owner", "doc-123", ".exe")


def test_save_does_not_overwrite_an_existing_managed_file(tmp_path):
    data_root = tmp_path / "data"
    first = _inspect(tmp_path, "first.txt", b"first")
    saved = save_staged_upload(
        first,
        data_root=data_root,
        owner_user_id="owner",
        document_id="doc-123",
    )
    second = _inspect(tmp_path, "second.txt", b"second")

    with pytest.raises(ReadingSourceError) as error:
        save_staged_upload(
            second,
            data_root=data_root,
            owner_user_id="owner",
            document_id="doc-123",
        )

    assert error.value.code == "source_exists"
    assert saved.read_bytes() == b"first"
    assert not second.temp_path.exists()


def test_save_cleans_staged_file_when_managed_path_validation_fails(tmp_path):
    inspected = _inspect(tmp_path, "book.pdf", b"%PDF-1.7\nminimal")

    with pytest.raises(ReadingSourceError, match="invalid_document_id"):
        save_staged_upload(
            inspected,
            data_root=tmp_path / "data",
            owner_user_id="owner",
            document_id="../escape",
        )

    assert not inspected.temp_path.exists()


def test_save_rejects_existing_symlink_even_when_target_has_same_hash(tmp_path):
    data_root = tmp_path / "data"
    payload = b"same content"
    inspected = _inspect(tmp_path, "book.txt", payload)
    managed = reading_source_path(data_root, "owner", "doc-123", ".txt")
    managed.parent.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(payload)
    managed.symlink_to(outside)

    with pytest.raises(ReadingSourceError, match="unmanaged_source_path"):
        save_staged_upload(
            inspected,
            data_root=data_root,
            owner_user_id="owner",
            document_id="doc-123",
        )

    assert managed.is_symlink()
    assert outside.read_bytes() == payload
    assert not inspected.temp_path.exists()


def test_repair_missing_source_requires_same_hash_and_writes_atomically(tmp_path):
    data_root = tmp_path / "data"
    payload = b"# Restored\n"
    inspected = _inspect(tmp_path, "renamed.md", payload)

    repaired = repair_missing_source(
        inspected,
        data_root=data_root,
        owner_user_id="owner",
        document_id="doc-123",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert repaired.read_bytes() == payload
    assert repaired.name == "doc-123.md"
    assert not inspected.temp_path.exists()


def test_repair_rejects_hash_mismatch_without_writing_source(tmp_path):
    inspected = _inspect(tmp_path, "book.txt", b"replacement")

    with pytest.raises(ReadingSourceError) as error:
        repair_missing_source(
            inspected,
            data_root=tmp_path / "data",
            owner_user_id="owner",
            document_id="doc-123",
            expected_sha256="0" * 64,
        )

    assert error.value.code == "hash_mismatch"
    assert not inspected.temp_path.exists()
    assert not (tmp_path / "data" / "reading").exists()


def test_delete_only_accepts_verified_managed_reading_paths(tmp_path):
    data_root = tmp_path / "data"
    inspected = _inspect(tmp_path, "book.txt", b"content")
    managed = save_staged_upload(
        inspected,
        data_root=data_root,
        owner_user_id="owner",
        document_id="doc-123",
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    with pytest.raises(ReadingSourceError, match="unmanaged_source_path"):
        delete_reading_source(outside, data_root=data_root)

    assert outside.exists()
    assert delete_reading_source(managed, data_root=data_root) is True
    assert not managed.exists()
    assert delete_reading_source(managed, data_root=data_root) is False
