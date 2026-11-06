from pathlib import Path

import pytest
import requests

from video_transcript_api.downloaders.generic import GenericDownloader


class _FakeResponse:
    def __init__(self, body: bytes, status=200, *, headers=None, interrupted=False):
        self.body = body
        self.status_code = status
        self.headers = requests.structures.CaseInsensitiveDict(
            {"Content-Length": str(len(body)), **(headers or {})}
        )
        self.interrupted = interrupted
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def iter_content(self, chunk_size=1024):
        yield self.body
        if self.interrupted:
            raise requests.exceptions.ChunkedEncodingError("interrupted")


def test_download_improvement(monkeypatch, tmp_path):
    body = b"media-bytes" * 128
    calls = []

    def fake_get(url, headers=None, stream=False, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "stream": stream, "timeout": timeout})
        return _FakeResponse(body)

    monkeypatch.setattr("video_transcript_api.downloaders.generic.requests.get", fake_get)

    downloader = GenericDownloader()
    downloader.temp_dir = str(tmp_path)

    result = downloader.download_file("https://example.com/audio.mp3", "test_audio.mp3")

    assert Path(result).parent == tmp_path
    assert Path(result).suffix == ".mp3"
    assert Path(result).read_bytes() == body
    assert calls == [
        {
            "url": "https://example.com/audio.mp3",
            "headers": {"Accept-Encoding": "identity"},
            "stream": True,
            "timeout": (30, 300),
        }
    ]


@pytest.mark.parametrize("retry_mode", ["partial", "ignored", "bad_range", "changed", "unsatisfiable", "no_validator"])
def test_resume_download(monkeypatch, tmp_path, retry_mode):
    validator = {} if retry_mode == "no_validator" else {"ETag": '"original"'}
    first = _FakeResponse(b"abc", headers={"Content-Length": "6", **validator}, interrupted=True)
    whole = _FakeResponse(b"abcdef")
    retries = {
        "partial": [_FakeResponse(b"def", 206, headers={"Content-Range": "bytes 3-5/6"})],
        "ignored": [_FakeResponse(b"uvwxyz", headers={"ETag": '"changed"'})],
        "bad_range": [_FakeResponse(b"cde", 206, headers={"Content-Range": "bytes 2-4/6"}), whole],
        "changed": [_FakeResponse(b"xyz", 206, headers={"Content-Range": "bytes 3-5/6", "ETag": '"changed"'}), whole],
        "unsatisfiable": [_FakeResponse(b"", 416), whole],
        "no_validator": [whole],
    }[retry_mode]
    responses = [first, *retries]
    pending = iter(responses)
    calls = []

    def fake_get(url, headers, **_):
        calls.append(headers)
        return next(pending)

    monkeypatch.setattr("video_transcript_api.downloaders.generic.requests.get", fake_get)

    downloader = GenericDownloader()
    downloader.temp_dir = str(tmp_path)

    result = downloader.download_file("https://example.com/audio.mp3", "test_resume.mp3")
    assert Path(result).read_bytes() == (b"uvwxyz" if retry_mode == "ignored" else b"abcdef")
    full = {"Accept-Encoding": "identity"}
    expected = [full]
    if retry_mode != "no_validator":
        expected.append({**full, "Range": "bytes=3-", "If-Range": '"original"'})
    if len(responses) == 3 or retry_mode == "no_validator":
        expected.append(full)
    assert calls == expected
    assert all(response.closed for response in responses)


def test_same_basename_downloads_keep_independent_files(monkeypatch, tmp_path):
    old_path = tmp_path / "audio.mp3"
    old_path.write_bytes(b"older temporary media")
    contents = iter([b"first", b"second"])

    def fake_get(url, headers, **_):
        assert "Range" not in headers
        return _FakeResponse(next(contents))

    monkeypatch.setattr("video_transcript_api.downloaders.generic.requests.get", fake_get)
    downloader = GenericDownloader()
    downloader.temp_dir = str(tmp_path)

    first = downloader.download_file("https://example.com/first/audio.mp3", "audio.mp3")
    second = downloader.download_file("https://example.com/second/audio.mp3", "audio.mp3")

    assert first != second
    assert Path(first).read_bytes() == b"first"
    assert Path(second).read_bytes() == b"second"
    assert old_path.read_bytes() == b"older temporary media"
