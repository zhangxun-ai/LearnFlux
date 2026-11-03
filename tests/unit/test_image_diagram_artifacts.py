"""Reject corrupt provider files and keep durable artifacts private."""

import struct
import zlib

import pytest

from video_transcript_api.image_diagrams.artifacts import ImageDiagramArtifacts


def png(pixels=b"\0\xff\xff\xff", width=1, height=1):
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def test_verified_png_survives_a_new_store_instance(tmp_path):
    store = ImageDiagramArtifacts(tmp_path / "images")
    key = store.save_image("a" * 32, png())
    reopened = ImageDiagramArtifacts(tmp_path / "images")
    assert reopened.image_path(key).read_bytes() == png()
    assert reopened.image_path(key).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("invalid", [
    png()[:-8], png() + b"untrusted trailer",
    b"\x89PNG\r\n\x1a\n" + b"x" * 40,
    png(pixels=b"\x05\xff\xff\xff"),  # Invalid scanline filter.
    png(pixels=b"\0" * 10000),          # Oversized decompressed data.
    png(width=4096, height=4096),
])
def test_invalid_image_is_never_persisted(tmp_path, invalid):
    store = ImageDiagramArtifacts(tmp_path / "images")
    with pytest.raises(ValueError, match="invalid_generated_image"):
        store.save_image("b" * 32, invalid)
    assert not (tmp_path / "images" / ("b" * 32) / "image.png").exists()


def test_corrupt_checksum_is_not_accepted(tmp_path):
    content = bytearray(png())
    content[30] ^= 1
    with pytest.raises(ValueError, match="invalid_generated_image"):
        ImageDiagramArtifacts(tmp_path).save_image("c" * 32, bytes(content))


def test_private_artifact_path_cannot_escape_or_follow_symlinks(tmp_path):
    store = ImageDiagramArtifacts(tmp_path / "images")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / ("d" * 32)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="invalid_artifact_path"):
        store.save_image("d" * 32, png())
    with pytest.raises(ValueError, match="invalid_artifact_path"):
        store.image_path("../outside/image.png")
    assert not (outside / "image.png").exists()
