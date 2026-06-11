"""Unit tests for LLM comment insight integration.

All console output must be in English only.
"""

from video_transcript_api.api.services.llm_ops import (
    _append_comment_insight,
    _build_comment_only_result_dict,
)


def test_append_comment_insight_skips_when_disabled():
    called = False

    def runner(**kwargs):
        nonlocal called
        called = True

    result_dict = {"内容总结": "summary"}

    _append_comment_insight(
        llm_task={"include_comments": False},
        result_dict=result_dict,
        summary_model="summary-model",
        summary_reasoning_effort="medium",
        analyzer=object(),
        insight_runner=runner,
    )

    assert called is False
    assert "评论洞察" not in result_dict


def test_append_comment_insight_adds_pipeline_result():
    runner_calls = []

    def runner(**kwargs):
        runner_calls.append(kwargs)
        return {
            "insight_text": "comment insight",
            "samples": [{"text": "useful", "like_count": 42}],
            "fetched_count": 3,
            "selected_count": 1,
        }

    result_dict = {"内容总结": "summary"}

    _append_comment_insight(
        llm_task={
            "include_comments": True,
            "comment_limit": 50,
            "url": "https://www.youtube.com/watch?v=abc123",
            "platform": "youtube",
            "media_id": "abc123",
            "video_title": "Demo",
            "author": "tester",
        },
        result_dict=result_dict,
        summary_model="summary-model",
        summary_reasoning_effort="medium",
        analyzer=object(),
        insight_runner=runner,
    )

    assert result_dict["评论洞察"] == "comment insight"
    assert result_dict["comment_samples"] == [{"text": "useful", "like_count": 42}]
    assert result_dict["comment_stats"] == {"fetched_count": 3, "selected_count": 1}
    assert runner_calls[0]["fetch_limit"] == 50
    assert runner_calls[0]["analysis_limit"] == 50
    assert runner_calls[0]["summary_text"] == "summary"


def test_append_comment_insight_swallows_pipeline_error():
    def runner(**kwargs):
        raise RuntimeError("comment api unavailable")

    result_dict = {"内容总结": "summary"}

    _append_comment_insight(
        llm_task={
            "include_comments": True,
            "comment_limit": 50,
            "url": "https://www.youtube.com/watch?v=abc123",
            "platform": "youtube",
            "media_id": "abc123",
        },
        result_dict=result_dict,
        summary_model="summary-model",
        summary_reasoning_effort=None,
        analyzer=object(),
        insight_runner=runner,
    )

    assert "评论洞察" not in result_dict
    assert result_dict["comment_error"] == "comment api unavailable"


def test_build_comment_only_result_dict_uses_cached_outputs():
    result = _build_comment_only_result_dict(
        {
            "transcript": "original transcript",
            "cached_calibrated": "cached calibrated",
            "cached_summary": "cached summary",
        }
    )

    assert result["校对文本"] == "cached calibrated"
    assert result["内容总结"] == "cached summary"
    assert result["calibrate_success"] is True
    assert result["summary_success"] is True
    assert result["stats"]["original_length"] == len("original transcript")
    assert result["stats"]["calibrated_length"] == len("cached calibrated")
    assert result["stats"]["summary_length"] == len("cached summary")
