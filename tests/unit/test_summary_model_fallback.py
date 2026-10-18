"""Summary fallback ownership tests.

All console output must be in English only.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from video_transcript_api.llm.processors.summary_processor import SummaryProcessor


def _config(**overrides):
    base = {
        "summary_model": "deepseek-v4-flash",
        "summary_reasoning_effort": "high",
        "min_summary_threshold": 10,
        "content_fallbacks": {
            "deepseek-v4-flash": ["deepseek-v4-pro", "qwen-plus-2025-12-01"],
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestSummaryModelFallback:
    def test_long_interview_with_only_overview_is_not_success(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(
            text="# Interview\n\n## 1. 概述\n\n" + "访谈讨论了产业发展的三个阶段。" * 20 + "核心结论是：不确定"
        )
        processor = SummaryProcessor(client, _config())

        assert processor.process(text="interview " * 6000, title="Demo") is None
        client.call.assert_called_once()

    def test_short_video_accepts_complete_prose_without_sections(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(text="A complete explanation of the single practical idea and its conditions. " * 2)
        processor = SummaryProcessor(client, _config())

        result = processor.process(text="short video " * 60, title="Demo")

        assert result == client.call.return_value.text.strip()
        assert "【转录正文】" in client.call.call_args.kwargs["user_prompt"]

    def test_long_interview_accepts_expanded_themes(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(
            text="## Infrastructure\n\n" + "The argument and evidence are explained. " * 10
            + "\n\n## Organization\n\n" + "The second theme includes its conditions. " * 10
        )
        processor = SummaryProcessor(client, _config())

        assert processor.process(text="interview " * 6000, title="Demo") is not None

    def test_delegates_fallback_chain_to_shared_llm_client(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(text="x" * 80)
        processor = SummaryProcessor(client, _config())

        result = processor.process(
            text="transcript " * 20,
            title="Demo",
            author="A",
        )

        assert result == "x" * 80
        client.call.assert_called_once()
        assert client.call.call_args.kwargs["model"] == "deepseek-v4-flash"

    def test_returns_none_after_short_summary_without_replaying_chain(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(text="too short")
        processor = SummaryProcessor(client, _config())

        result = processor.process(text="transcript " * 20, title="Demo")

        assert result is None
        client.call.assert_called_once()

    def test_does_not_repeat_client_owned_fallback_chain_after_failure(self):
        client = MagicMock()
        client.call.side_effect = RuntimeError(
            "All models refused: "
            "['deepseek-v4-flash', 'deepseek-v4-pro', 'qwen-plus-2025-12-01']"
        )
        processor = SummaryProcessor(client, _config())

        result = processor.process(text="transcript " * 20, title="Demo")

        assert result is None
        client.call.assert_called_once()

    def test_source_defect_gets_one_correction_using_the_actual_fallback_model(self):
        client = MagicMock()
        client.call.side_effect = [
            SimpleNamespace(text="## Company history\n\nIBM depended on OS/360 and government contracts. " * 3, model="qwen-plus-2025-12-01"),
            SimpleNamespace(text="## Company history\n\nThe source discusses how new technology changes organizations. " * 3),
        ]
        processor = SummaryProcessor(client, _config())
        source = "The source discusses how new technology changes organizations. " * 100

        result = processor.process(text=source, title="Demo")

        assert result is not None
        assert "OS/360" not in result
        assert client.call.call_count == 2
        assert client.call.call_args.kwargs["model"] == "qwen-plus-2025-12-01"
        assert source in client.call.call_args.kwargs["user_prompt"]

    def test_unresolved_source_defect_is_not_retried_indefinitely(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(text="## Company history\n\nIBM depended on OS/360 and government contracts. " * 3, model="test")
        processor = SummaryProcessor(client, _config())

        assert processor.process(text="source " * 1000, title="Demo") is None
        assert client.call.call_count == 2
