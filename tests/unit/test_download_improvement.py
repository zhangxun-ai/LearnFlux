from pathlib import Path

from video_transcript_api.downloaders.generic import GenericDownloader


class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1024):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]


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

    assert result == str(tmp_path / "test_audio.mp3")
    assert Path(result).read_bytes() == body
    assert calls == [
        {
            "url": "https://example.com/audio.mp3",
            "headers": {},
            "stream": True,
            "timeout": (30, 300),
        }
    ]


def test_resume_download(monkeypatch, tmp_path):
    body = b"resume-bytes" * 128
    filename = "test_resume.mp3"
    partial_size = len(body) // 2
    partial_path = tmp_path / filename
    partial_path.write_bytes(body[:partial_size])
    calls = []

    def fake_get(url, headers=None, stream=False, timeout=None):
        headers = headers or {}
        calls.append(headers)
        if headers.get("Range") == f"bytes={partial_size}-":
            return _FakeResponse(body[partial_size:])
        return _FakeResponse(body)

    monkeypatch.setattr("video_transcript_api.downloaders.generic.requests.get", fake_get)

    downloader = GenericDownloader()
    downloader.temp_dir = str(tmp_path)

    result = downloader.download_file("https://example.com/audio.mp3", filename)

    assert result == str(partial_path)
    assert partial_path.read_bytes() == body
    assert calls == [{"Range": f"bytes={partial_size}-"}]
