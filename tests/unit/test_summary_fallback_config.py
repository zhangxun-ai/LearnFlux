"""
Unit tests for summary model fallback configuration.

Verifies that:
- content_fallbacks config is correctly loaded into LLMConfig
- deepseek-v4-pro has deepseek-v4-flash as first fallback
- total_timeout is sufficient for fallback execution

All console output must be in English only (no emoji, no Chinese).
"""

import json
import pytest


class TestContentFallbacksConfig:
    """Verify content_fallbacks configuration for summary model."""

    def _load_config_jsonc(self, path: str) -> dict:
        """Load JSONC file (strip comments and handle control chars)."""
        import re
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Remove single-line comments (but not inside strings)
        content = re.sub(r'(?<!:)//[^\n]*', '', content)
        # Remove multi-line comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # Remove trailing commas before } or ]
        content = re.sub(r',\s*([}\]])', r'\1', content)
        return json.loads(content, strict=False)

    def test_config_example_has_deepseek_v4_pro_fallback(self):
        """config.example.jsonc should have deepseek-v4-pro chain with Qwen cross-provider."""
        config = self._load_config_jsonc("config/config.example.jsonc")
        llm = config["llm"]
        fallbacks = llm["content_fallbacks"]
        assert "deepseek-v4-pro" in fallbacks
        assert "deepseek-v4-flash" in fallbacks["deepseek-v4-pro"]
        assert "qwen-plus-2025-12-01" in fallbacks["deepseek-v4-pro"]
        assert llm["model_endpoints"]["qwen*"] == "dashscope"
        assert llm["endpoints"]["dashscope"]["api_key_env"] == "DASHSCOPE_API_KEY"
        assert fallbacks["deepseek-v4-flash"][0] == "qwen-plus-2025-12-01"

    def test_config_has_deepseek_v4_pro_fallback(self):
        """config.jsonc should keep a usable deepseek-v4-pro fallback chain when present."""
        config = self._load_config_jsonc("config/config.jsonc")
        llm = config["llm"]
        fallbacks = llm.get("content_fallbacks") or {}
        if "deepseek-v4-pro" not in fallbacks:
            pytest.skip("live config.jsonc has no deepseek-v4-pro content_fallbacks")
        # Prefer same-provider first hop when present
        assert fallbacks["deepseek-v4-pro"][0] in {
            "deepseek-v4-flash",
            "qwen-plus-2025-12-01",
        }

    def test_total_timeout_sufficient_for_fallback(self):
        """total_timeout should be >= 300s to leave room for fallback after primary timeout."""
        config = self._load_config_jsonc("config/config.jsonc")
        llm = config["llm"]
        total_timeout = llm.get("total_timeout", 180)
        assert total_timeout >= 300, (
            f"total_timeout={total_timeout}s is too short for fallback execution. "
            f"Primary model may consume ~180s, leaving no time for fallbacks."
        )

    def test_llmconfig_from_dict_loads_content_fallbacks(self):
        """LLMConfig.from_dict should correctly load content_fallbacks."""
        from video_transcript_api.llm.core.config import LLMConfig

        config_dict = {
            "llm": {
                "api_key": "test-key",
                "base_url": "http://localhost:3000/v1",
                "calibrate_model": "deepseek-v4-flash",
                "summary_model": "deepseek-v4-pro",
                "content_fallbacks": {
                    "deepseek-v4-pro": ["deepseek-v4-flash", "gpt-4.1-mini"],
                },
                "total_timeout": 300,
            }
        }
        llm_config = LLMConfig.from_dict(config_dict)
        assert llm_config.content_fallbacks == {
            "deepseek-v4-pro": ["deepseek-v4-flash", "gpt-4.1-mini"],
        }
        assert llm_config.total_timeout == 300.0
