"""Unit tests for ordinary transcription provider implementations."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_transcript_api.transcriber.providers.local_whisper import (
    LocalWhisperProvider,
)
from video_transcript_api.transcriber.providers import capswriter as capswriter_module
from video_transcript_api.transcriber.providers.capswriter import CapsWriterProvider
from video_transcript_api.transcriber.contracts import TranscriptionContext


def _local_config(binary_path: Path, **overrides):
    local_whisper = {
        "binary": str(binary_path),
        "model": "test-model",
        "language": "zh",
        "timeout": 17,
    }
    local_whisper.update(overrides)
    return {"local_whisper": local_whisper}


def test_local_whisper_uses_config_and_returns_seekable_result(tmp_path, monkeypatch):
    """The provider must preserve command, artifacts, and second-based timestamps."""
    binary_path = tmp_path / "mlx_whisper"
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")
    binary_path.chmod(0o755)
    audio_path = tmp_path / "lesson.mp3"
    audio_path.write_bytes(b"audio")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        (tmp_path / "result.json").write_text(
            json.dumps(
                {
                    "text": "",
                    "segments": [
                        {"start": 999.36, "end": 1001.0, "text": "Before."},
                        {"start": 1002.0, "end": 1005.0, "text": "After."},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = LocalWhisperProvider(_local_config(binary_path), str(tmp_path))

    result = provider.transcribe(
        str(audio_path),
        "result",
        context=TranscriptionContext("task-1", "bilibili", "media-1"),
    )

    assert captured["command"] == [
        str(binary_path),
        str(audio_path),
        "--model",
        "test-model",
        "--output-dir",
        str(tmp_path),
        "--output-name",
        "result",
        "--output-format",
        "json",
        "--verbose",
        "False",
        "--language",
        "zh",
    ]
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": 17,
    }
    assert result.transcript == "Before.\nAfter."
    assert Path(result.txt_path).read_text(encoding="utf-8") == result.transcript
    assert result.funasr_json_data["duration"] == 1005.0
    assert result.funasr_json_data["segments"][0]["end_time"] == 1001.0
    assert result.funasr_json_data["segments"][1]["start_time"] == 1002.0
    assert result.generated_files == (
        tmp_path / "result.txt",
        tmp_path / "result.json",
    )
    assert result.provider == "local_whisper"
    assert result.model == "test-model"
    assert result.elapsed_seconds is not None
    assert result.elapsed_seconds >= 0


def test_local_whisper_rejects_missing_binary(tmp_path):
    provider = LocalWhisperProvider(
        _local_config(tmp_path / "missing-binary"), str(tmp_path)
    )

    with pytest.raises(RuntimeError, match="mlx-whisper"):
        provider.transcribe(str(tmp_path / "audio.mp3"), "result")


def test_local_whisper_converts_subprocess_timeout(tmp_path, monkeypatch):
    binary_path = tmp_path / "mlx_whisper"
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")
    provider = LocalWhisperProvider(_local_config(binary_path), str(tmp_path))

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mlx_whisper", timeout=17)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    with pytest.raises(RuntimeError, match="17"):
        provider.transcribe(str(tmp_path / "audio.mp3"), "result")


def test_local_whisper_rejects_nonzero_exit(tmp_path, monkeypatch):
    binary_path = tmp_path / "mlx_whisper"
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")
    provider = LocalWhisperProvider(_local_config(binary_path), str(tmp_path))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=3, stdout="", stderr="provider failed"
        ),
    )

    with pytest.raises(RuntimeError, match="exit 3"):
        provider.transcribe(str(tmp_path / "audio.mp3"), "result")


def test_local_whisper_rejects_missing_json(tmp_path, monkeypatch):
    binary_path = tmp_path / "mlx_whisper"
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")
    provider = LocalWhisperProvider(_local_config(binary_path), str(tmp_path))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="JSON"):
        provider.transcribe(str(tmp_path / "audio.mp3"), "result")


def test_local_whisper_rejects_empty_transcript(tmp_path, monkeypatch):
    binary_path = tmp_path / "mlx_whisper"
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")
    provider = LocalWhisperProvider(_local_config(binary_path), str(tmp_path))

    def fake_run(*args, **kwargs):
        (tmp_path / "result.json").write_text(
            json.dumps({"text": "", "segments": []}), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="empty|为空"):
        provider.transcribe(str(tmp_path / "audio.mp3"), "result")


def test_capswriter_preserves_client_config_and_generated_files(tmp_path, monkeypatch):
    """CapsWriter configuration and artifact parsing must remain unchanged."""
    audio_path = tmp_path / "lesson.mp3"
    audio_path.write_bytes(b"audio")
    txt_path = tmp_path / "lesson.txt"
    txt_path.write_text("CapsWriter text", encoding="utf-8")
    merge_path = tmp_path / "lesson.merge.txt"
    merge_path.write_text("Merged text", encoding="utf-8")
    json_path = tmp_path / "lesson_funasr.json"
    json_path.write_text(
        json.dumps({"segments": [{"text": "CapsWriter text"}]}),
        encoding="utf-8",
    )
    generated_files = [merge_path, txt_path, json_path]
    captured = {}
    progress_callback = object()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def transcribe_file(self, file_path):
            captured["audio_path"] = file_path
            return True, generated_files

    client_config = SimpleNamespace()
    monkeypatch.setattr(capswriter_module, "CapsWriterClient", FakeClient)
    monkeypatch.setattr(capswriter_module, "ClientConfig", client_config)
    provider = CapsWriterProvider(
        config={
            "capswriter": {
                "server_url": "ws://asr.internal:6123",
                "max_retries": 4,
                "retry_delay": 2,
            }
        },
        output_dir=str(tmp_path),
        progress_callback=progress_callback,
    )

    result = provider.transcribe(
        str(audio_path),
        "ignored-output-base",
        context=TranscriptionContext("task-1", "bilibili", "media-1"),
    )

    assert captured["kwargs"] == {
        "server_addr": "asr.internal",
        "server_port": 6123,
        "output_dir": str(tmp_path),
        "max_retries": 4,
        "retry_delay": 2,
        "progress_callback": progress_callback,
    }
    assert captured["audio_path"] == str(audio_path)
    assert client_config.server_addr == "asr.internal"
    assert client_config.server_port == 6123
    assert client_config.generate_txt is True
    assert client_config.generate_merge_txt is False
    assert client_config.generate_srt is False
    assert client_config.generate_lrc is False
    assert client_config.generate_json is False
    assert result.transcript == "CapsWriter text"
    assert result.txt_path == str(txt_path)
    assert result.funasr_json_data == {
        "segments": [{"text": "CapsWriter text"}]
    }
    assert result.generated_files == tuple(generated_files)
    assert result.provider == "capswriter"
    assert result.model is None
    assert result.elapsed_seconds is not None
    assert result.elapsed_seconds >= 0


def test_capswriter_keeps_empty_txt_as_success(tmp_path, monkeypatch):
    """The provider refactor must not change the legacy empty-file behavior."""
    txt_path = tmp_path / "empty.txt"
    txt_path.write_text("", encoding="utf-8")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def transcribe_file(self, file_path):
            return True, [txt_path]

    monkeypatch.setattr(capswriter_module, "CapsWriterClient", FakeClient)
    provider = CapsWriterProvider({}, str(tmp_path))

    result = provider.transcribe(str(tmp_path / "audio.mp3"), "result")

    assert result.transcript == ""
    assert result.txt_path == str(txt_path)


@pytest.mark.parametrize(
    ("success", "generated_files"),
    [
        (False, []),
        (True, []),
        (True, [Path("result_funasr.json")]),
    ],
)
def test_capswriter_rejects_failed_or_missing_txt_result(
    tmp_path, monkeypatch, success, generated_files
):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def transcribe_file(self, file_path):
            return success, generated_files

    monkeypatch.setattr(capswriter_module, "CapsWriterClient", FakeClient)
    provider = CapsWriterProvider({}, str(tmp_path))

    with pytest.raises(RuntimeError):
        provider.transcribe(str(tmp_path / "audio.mp3"), "result")
