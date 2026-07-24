"""Unit tests for provider-neutral transcription contracts."""

from decimal import Decimal
from pathlib import Path

import pytest

import video_transcript_api.transcriber as transcriber_package
from video_transcript_api.transcriber import contracts
from video_transcript_api.transcriber.contracts import TranscriptionResult


def test_transcription_context_requires_nonblank_identifiers():
    """Cloud routing metadata must identify a concrete request."""
    context_class = getattr(contracts, "TranscriptionContext", None)

    assert context_class is not None
    assert context_class("task-1", "bilibili", "media-1").task_id == "task-1"


def test_transcription_context_is_exported_by_transcriber_package():
    """Cloud integrations must access the public context contract."""
    assert (
        getattr(transcriber_package, "TranscriptionContext", None)
        is contracts.TranscriptionContext
    )


@pytest.mark.parametrize("field_name", ["task_id", "platform", "media_id"])
def test_transcription_context_rejects_blank_required_fields(field_name):
    """Cloud routing metadata cannot be empty or whitespace-only."""
    context_class = contracts.TranscriptionContext
    values = {
        "task_id": "task-1",
        "platform": "bilibili",
        "media_id": "media-1",
    }
    values[field_name] = " \t"

    with pytest.raises(ValueError, match=field_name):
        context_class(**values)


def test_transcription_result_converts_to_exact_legacy_shape():
    """Provider metadata must not leak into the existing public result."""
    result = TranscriptionResult(
        transcript="hello",
        txt_path="/tmp/result.txt",
        funasr_json_data={"segments": []},
        generated_files=(Path("/tmp/result.txt"),),
        provider="local_whisper",
        model="test-model",
        elapsed_seconds=1.25,
        language="zh",
        audio_seconds=120.0,
        usage_seconds=123.0,
        estimated_cost=Decimal("0.12"),
        currency="CNY",
        remote_status="SUCCEEDED",
        remote_task_id_hash="a1b2c3",
    )

    assert result.to_legacy_dict() == {
        "transcript": "hello",
        "txt_path": "/tmp/result.txt",
        "funasr_json_data": {"segments": []},
        "generated_files": [Path("/tmp/result.txt")],
    }
    assert result.estimated_cost == Decimal("0.12")
    assert result.remote_task_id_hash == "a1b2c3"


def test_transcription_result_returns_fresh_generated_file_lists():
    """Callers may mutate the legacy list without changing the typed result."""
    result = TranscriptionResult(
        transcript="hello",
        txt_path="/tmp/result.txt",
        funasr_json_data=None,
        generated_files=(Path("/tmp/result.txt"),),
        provider="capswriter",
    )

    first = result.to_legacy_dict()
    second = result.to_legacy_dict()

    assert first["generated_files"] is not second["generated_files"]
    first["generated_files"].clear()
    assert second["generated_files"] == [Path("/tmp/result.txt")]
