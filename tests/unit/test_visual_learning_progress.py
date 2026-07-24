import pytest


def test_workflow_progress_is_monotonic_across_source_and_generation_phases():
    from video_transcript_api.visual_learning.progress import compose_workflow_progress

    states = [
        ("source_processing", {"stage": "extracting", "percent": 30}, None),
        (
            "source_processing",
            {
                "stage": "waiting_analysis",
                "percent": 94,
                "evidence": {"completed_segments": 5, "total_segments": 10},
            },
            None,
        ),
        ("ready_for_generation", {"stage": "ready_for_generation", "percent": 100}, None),
        (
            "generating_visual",
            {"stage": "ready_for_generation", "percent": 100},
            {"stage": "analyzing_outline", "percent": 50},
        ),
        (
            "generating_visual",
            None,
            {
                "stage": "selecting_evidence",
                "completed_units": 3,
                "total_units": 6,
            },
        ),
        ("generating_visual", None, {"stage": "generating_visual", "percent": 75}),
        ("generating_visual", None, {"stage": "validating", "percent": 95}),
        ("completed", None, {"stage": "completed", "percent": 100}),
    ]

    results = [
        compose_workflow_progress(phase, source, generation)
        for phase, source, generation in states
    ]
    percents = [item["overall_percent"] for item in results]

    assert percents == sorted(percents)
    assert results[1]["overall_percent"] == pytest.approx(36.5)
    assert results[2]["overall_percent"] == 55
    assert results[3]["overall_percent"] == 55
    assert results[-1]["overall_percent"] == 100


def test_document_quality_stage_advances_after_extraction():
    from video_transcript_api.visual_learning.progress import compose_workflow_progress

    extraction = compose_workflow_progress(
        "source_processing", {"stage": "extracting", "percent": 94}, None
    )
    quality = compose_workflow_progress(
        "source_processing",
        {"stage": "assessing_quality", "percent": 0},
        None,
    )

    assert extraction["overall_percent"] == 15
    assert quality["overall_percent"] == 15
    assert quality["stage"] == "assessing_quality"


def test_workflow_progress_uses_real_units_when_available():
    from video_transcript_api.visual_learning.progress import compose_workflow_progress

    source = compose_workflow_progress(
        "source_processing",
        {
            "stage": "waiting_analysis",
            "stage_label": "正在完整校对",
            "evidence": {"completed_segments": 2, "total_segments": 8},
            "basis": "completed_segments",
        },
        None,
    )
    evidence = compose_workflow_progress(
        "generating_visual",
        None,
        {
            "stage": "selecting_evidence",
            "stage_label": "正在回查原文依据",
            "completed_units": 2,
            "total_units": 5,
            "basis": "completed_sections",
        },
    )

    assert source["completed_units"] == 2
    assert source["total_units"] == 8
    assert source["phase_percent"] == 25
    assert evidence["overall_percent"] == 72
    assert evidence["phase_percent"] == 40


def test_workflow_progress_does_not_fake_remote_request_progress():
    from video_transcript_api.visual_learning.progress import compose_workflow_progress

    outline = compose_workflow_progress(
        "generating_visual",
        None,
        {
            "stage": "analyzing_outline",
            "stage_label": "正在建立全文知识架构",
            "updated_at": "2026-07-11T00:00:00+00:00",
        },
    )

    assert outline["overall_percent"] == 55
    assert outline["phase_percent"] is None
    assert outline["basis"] == "stage_transition"


def test_failed_generation_keeps_last_completed_stage_position():
    from video_transcript_api.visual_learning.progress import compose_workflow_progress

    failed = compose_workflow_progress(
        "failed",
        None,
        {
            "stage": "failed",
            "stage_label": "图解生成失败",
            "previous_stage": "generating_visual",
        },
    )

    assert failed["stage"] == "failed"
    assert failed["overall_percent"] == 75
