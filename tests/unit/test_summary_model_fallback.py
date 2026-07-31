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
    def test_wechat_deep_learning_uses_article_learning_prompt(self):
        client = MagicMock()
        client.call.return_value = SimpleNamespace(text="x" * 80)
        processor = SummaryProcessor(client, _config())

        result = processor.process(
            text="article body " * 20,
            title="Demo",
            summary_profile="deep_learning_article",
        )

        assert result == "x" * 80
        system_prompt = client.call.call_args.kwargs["system_prompt"]
        for section in (
            "核心问题",
            "三分钟摘要",
            "结构化大纲",
            "关键概念",
            "原文证据",
            "事实、观点与待核实",
            "盲点与反思",
            "行动清单",
            "复习卡",
            "自测题",
            "继续追问",
        ):
            assert section in system_prompt

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
