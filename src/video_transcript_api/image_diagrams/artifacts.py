"""Private durable image files, separated from temporary ASR media cleanup."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import uuid
import zlib


class ImageDiagramArtifacts:
    """Keep source/prompt evidence and images under an explicit private root."""

    def __init__(self, root: str | Path):
        root = Path(root).absolute()
        if root.is_symlink():
            raise ValueError("invalid_artifact_root")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve()

    def job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("invalid_job_id")
        directory = self.root / job_id
        if directory.is_symlink():
            raise ValueError("invalid_artifact_path")
        directory.mkdir(exist_ok=True, mode=0o700)
        return directory

    def write_json(self, job_id: str, name: str, value: dict) -> None:
        if name not in {"source", "request", "plan", "review", "usage"}:
            raise ValueError("invalid_artifact_name")
        self._write(self.job_dir(job_id) / f"{name}.json", json.dumps(
            value, ensure_ascii=False, indent=2,
        ).encode())

    def write_prompt(self, job_id: str, prompt: str) -> None:
        self._write(self.job_dir(job_id) / "prompt.txt", prompt.encode())

    @staticmethod
    def _write(target: Path, content: bytes) -> None:
        if target.is_symlink():
            raise ValueError("invalid_artifact_path")
        temporary = target.parent / f".{uuid.uuid4().hex}.pending"
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def save_image(self, job_id: str, content: bytes) -> str:
        if not isinstance(content, bytes) or not 40 < len(content) <= 32 * 1024 * 1024:
            raise ValueError("invalid_generated_image")
        if content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
            raise ValueError("invalid_generated_image")
        width, height = struct.unpack(">II", content[16:24])
        if not (0 < width <= 4096 and 0 < height <= 4096) or width * height > 9_000_000:
            raise ValueError("invalid_generated_image")
        self._validate_png(content, width, height)
        key = f"{job_id}/image.png"
        self._write(self.job_dir(job_id) / "image.png", content)
        return key

    @staticmethod
    def _validate_png(content: bytes, width: int, height: int) -> None:
        """Verify CRCs, bounded decompression and scanlines before delivery."""
        cursor, chunks, compressed = 8, [], bytearray()
        while cursor + 12 <= len(content):
            size = struct.unpack(">I", content[cursor:cursor + 4])[0]
            end = cursor + 12 + size
            if end > len(content):
                raise ValueError("invalid_generated_image")
            kind = content[cursor + 4:cursor + 8]
            payload = content[cursor + 8:cursor + 8 + size]
            checksum = struct.unpack(">I", content[cursor + 8 + size:end])[0]
            if zlib.crc32(kind + payload) & 0xffffffff != checksum:
                raise ValueError("invalid_generated_image")
            chunks.append(kind)
            if kind == b"IDAT":
                compressed.extend(payload)
            cursor = end
            if kind == b"IEND":
                break
        if (not chunks or chunks[0] != b"IHDR" or chunks[-1] != b"IEND"
                or cursor != len(content) or not compressed or chunks.count(b"IHDR") != 1
                or struct.unpack(">I", content[8:12])[0] != 13):
            raise ValueError("invalid_generated_image")
        depth, color, compression, filtering, interlace = content[24:29]
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
        if (channels is None or depth not in {1, 2, 4, 8, 16}
                or (color in {2, 4, 6} and depth not in {8, 16})
                or (color == 3 and (depth == 16 or b"PLTE" not in chunks))
                or compression or filtering or interlace):
            raise ValueError("invalid_generated_image")
        row_size = (width * channels * depth + 7) // 8 + 1
        expected = height * row_size
        try:
            decompressor = zlib.decompressobj()
            pixels = decompressor.decompress(bytes(compressed), expected + 1)
        except zlib.error:
            raise ValueError("invalid_generated_image") from None
        if (len(pixels) != expected or not decompressor.eof
                or decompressor.unused_data or any(pixels[i] > 4 for i in range(0, expected, row_size))):
            raise ValueError("invalid_generated_image")

    def image_path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}/image\.png", key or ""):
            raise ValueError("invalid_artifact_path")
        path = self.root / key
        if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
            raise FileNotFoundError("image_not_found")
        if self.root not in path.resolve().parents:
            raise ValueError("invalid_artifact_path")
        return path
