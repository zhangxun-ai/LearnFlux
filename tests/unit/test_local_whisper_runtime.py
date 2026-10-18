"""Offline regression coverage for local runtime failures and long media."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from video_transcript_api.transcriber.providers.local_whisper import (
    LocalTranscriptionError,
    LocalWhisperProvider,
    local_transcription_error_message,
)


@pytest.fixture
def provider(tmp_path):
    binary = tmp_path / "mlx_whisper"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return LocalWhisperProvider(
        {"local_whisper": {"binary": str(binary)}}, str(tmp_path)
    )


@pytest.mark.parametrize("duration,expected", [(60, 1800), (9240, 9240), (50000, 14400)])
def test_timeout_scales_for_long_media(provider, monkeypatch, duration, expected):
    monkeypatch.setattr(provider, "_probe_duration", lambda _: duration)
    assert provider._transcription_timeout("lesson.mp3", {}) == expected


def test_timeout_keeps_configured_minimum_and_factor(provider, monkeypatch):
    monkeypatch.setattr(provider, "_probe_duration", lambda _: 7200)
    assert provider._transcription_timeout(
        "lesson.mp3", {"timeout": 1800, "timeout_duration_factor": 0.5}
    ) == 3600
    assert provider._transcription_timeout("lesson.mp3", {"timeout": 20000}) == 20000


@pytest.mark.parametrize("stdout", ["not-a-duration", "nan", "inf", "-1", "0", ""])
def test_invalid_duration_does_not_break_transcription(provider, monkeypatch, stdout):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout),
    )
    assert provider._transcription_timeout("lesson.mp3", {"timeout": 17}) == 17


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("ffprobe", 10)])
def test_unavailable_probe_keeps_base_timeout(provider, monkeypatch, error):
    def fail_probe(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail_probe)
    assert provider._transcription_timeout("lesson.mp3", {"timeout": 17}) == 17


@pytest.mark.parametrize("mode", ["directory", "not_executable"])
def test_binary_must_be_executable_file(tmp_path, mode):
    binary = tmp_path / "mlx_whisper"
    if mode == "directory":
        binary.mkdir()
    else:
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o644)
    provider = LocalWhisperProvider({"local_whisper": {"binary": str(binary)}}, str(tmp_path))
    with pytest.raises(LocalTranscriptionError) as error:
        provider.transcribe("lesson.mp3", "result")
    assert error.value.code == "local_binary_unavailable"
    assert str(binary) not in str(error.value)


@pytest.mark.parametrize("payload", [[], None, {"text": 5}, {"segments": None}, {"segments": [{"text": 5}]}])
def test_malformed_result_has_stable_error(provider, tmp_path, monkeypatch, payload):
    monkeypatch.setattr(provider, "_probe_duration", lambda _: None)

    def write_output(*args, **kwargs):
        (tmp_path / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", write_output)
    with pytest.raises(LocalTranscriptionError) as error:
        provider.transcribe("lesson.mp3", "result")
    assert error.value.code == "local_result_invalid"


def test_invalid_json_is_recoverable(provider, tmp_path, monkeypatch):
    monkeypatch.setattr(provider, "_probe_duration", lambda _: None)

    def write_output(*args, **kwargs):
        (tmp_path / "result.json").write_text("broken JSON", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", write_output)
    with pytest.raises(LocalTranscriptionError, match="local_result_invalid"):
        provider.transcribe("lesson.mp3", "result")


def test_provider_does_not_expose_stderr(provider, monkeypatch):
    monkeypatch.setattr(provider, "_probe_duration", lambda _: None)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=3, stderr="sensitive-token"),
    )
    with pytest.raises(LocalTranscriptionError) as error:
        provider.transcribe("private/lesson.mp3", "result")
    assert error.value.code == "local_transcription_failed"
    assert "sensitive-token" not in str(error.value)
    assert "private" not in str(error.value)
    assert "sensitive-token" not in local_transcription_error_message(error.value.code)


def test_long_media_subprocess_receives_extended_timeout(provider, tmp_path, monkeypatch):
    monkeypatch.setattr(provider, "_probe_duration", lambda _: 9240)
    captured = {}

    def write_output(*args, **kwargs):
        captured.update(kwargs)
        (tmp_path / "result.json").write_text(json.dumps({"text": "Speech"}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", write_output)
    assert provider.transcribe("lesson.mp3", "result").transcript == "Speech"
    assert captured["timeout"] == 9240


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "invalid"])
def test_invalid_timestamps_do_not_escape_result(value):
    assert LocalWhisperProvider.as_seconds(value) is None
