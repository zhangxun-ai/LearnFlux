"""Tests for task progress helpers."""

from datetime import datetime, timezone

from src.video_transcript_api.utils.task_progress import (
    build_progress,
    compose_overall_percent,
    estimate_eta_seconds,
)


def test_compose_overall_percent_uses_stage_range_and_caps_in_flight():
    assert compose_overall_percent("downloading", 0) == 12
    assert compose_overall_percent("downloading", 0.5) == 22
    assert compose_overall_percent("downloading", 1) == 32
    assert compose_overall_percent("calibrating", 1) == 95
    assert compose_overall_percent("completed", None) == 100


def test_estimate_eta_from_completed_units_and_elapsed_seconds():
    eta = estimate_eta_seconds(completed=5, total=10, elapsed_seconds=100)

    assert eta == 100


def test_build_progress_includes_basis_confidence_and_evidence():
    progress = build_progress(
        stage="transcribing",
        stage_label="正在转录音视频",
        fraction=0.5,
        basis="funasr_server_progress",
        confidence="high",
        evidence={"completed": 50, "total": 100, "unit": "percent"},
        now=datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert progress["stage"] == "transcribing"
    assert progress["stage_label"] == "正在转录音视频"
    assert progress["percent"] == 62
    assert progress["basis"] == "funasr_server_progress"
    assert progress["confidence"] == "high"
    assert progress["evidence"] == {"completed": 50, "total": 100, "unit": "percent"}
    assert progress["updated_at"] == "2026-06-08T10:00:00+00:00"
