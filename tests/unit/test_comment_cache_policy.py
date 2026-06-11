"""Unit tests for cached LLM result reuse with optional comment insight.

All console output must be in English only.
"""

from video_transcript_api.api.services.transcription import _should_use_cached_llm_results


def test_uses_cached_llm_results_when_comments_not_requested():
    cache_data = {"llm_calibrated": "calibrated", "llm_summary": "summary"}
    assert _should_use_cached_llm_results(cache_data, include_comments=False) is True


def test_does_not_use_cached_llm_results_when_requested_comment_is_missing():
    cache_data = {"llm_calibrated": "calibrated", "llm_summary": "summary"}
    assert _should_use_cached_llm_results(cache_data, include_comments=True) is False


def test_uses_cached_llm_results_when_requested_comment_exists():
    cache_data = {
        "llm_calibrated": "calibrated",
        "llm_summary": "summary",
        "comment_insight": "comment insight",
    }
    assert _should_use_cached_llm_results(cache_data, include_comments=True) is True
