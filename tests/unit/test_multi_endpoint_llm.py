"""Unit tests for multi-endpoint LLM routing (DeepSeek primary, DashScope fallback).

All console output must be in English only.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestResolveModelEndpoint:
    def test_qwen_routes_to_dashscope(self):
        from video_transcript_api.llm.multi_endpoint import resolve_model_endpoint

        routes = {"qwen*": "dashscope", "qwen-plus*": "dashscope"}
        assert resolve_model_endpoint("qwen-plus-2025-12-01", routes) == "dashscope"
        assert resolve_model_endpoint("qwen-plus", routes) == "dashscope"

    def test_deepseek_uses_default(self):
        from video_transcript_api.llm.multi_endpoint import resolve_model_endpoint

        routes = {"qwen*": "dashscope"}
        assert resolve_model_endpoint("deepseek-v4-flash", routes) is None


class TestBuildEndpointClients:
    def test_builds_dashscope_from_env_key(self, monkeypatch):
        from video_transcript_api.llm.multi_endpoint import build_endpoint_clients

        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
        llm_cfg = {
            "endpoints": {
                "dashscope": {
                    "base_url": "https://dashscope.example.com/compatible-mode/v1",
                    "api_key_env": "DASHSCOPE_API_KEY",
                }
            }
        }
        with patch("video_transcript_api.llm.multi_endpoint.SyncLLMClient") as client_cls:
            client_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
            clients = build_endpoint_clients(
                llm_cfg,
                max_retries=2,
                total_timeout=300.0,
                sensitive_detector=None,
            )
        assert "dashscope" in clients
        assert clients["dashscope"].base_url.endswith("/compatible-mode/v1")
        assert clients["dashscope"].api_key == "sk-test-dashscope"
        assert clients["dashscope"].content_fallbacks is None

    def test_skips_endpoint_when_env_missing(self, monkeypatch):
        from video_transcript_api.llm.multi_endpoint import build_endpoint_clients

        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        llm_cfg = {
            "endpoints": {
                "dashscope": {
                    "base_url": "https://dashscope.example.com/compatible-mode/v1",
                    "api_key_env": "DASHSCOPE_API_KEY",
                }
            }
        }
        with patch("video_transcript_api.llm.multi_endpoint.SyncLLMClient"):
            clients = build_endpoint_clients(
                llm_cfg,
                max_retries=2,
                total_timeout=300.0,
                sensitive_detector=None,
            )
        assert clients == {}


class TestMultiEndpointSyncLLMClient:
    def test_single_chat_routes_qwen_to_secondary_client(self):
        from video_transcript_api.llm.multi_endpoint import MultiEndpointSyncLLMClient

        secondary = MagicMock()
        secondary._single_chat.return_value = ({"ok": True}, 12)

        with patch.object(MultiEndpointSyncLLMClient, "__init__", lambda self, **k: None):
            client = MultiEndpointSyncLLMClient()
            client._endpoint_clients = {"dashscope": secondary}
            client._model_endpoints = {"qwen*": "dashscope"}
            client._total_timeout = 300.0

            with patch(
                "video_transcript_api.llm.multi_endpoint.SyncLLMClient._single_chat"
            ) as primary_chat:
                primary_chat.return_value = ({"primary": True}, 1)
                data, latency = MultiEndpointSyncLLMClient._single_chat(
                    client,
                    "qwen-plus-2025-12-01",
                    [{"role": "user", "content": "hi"}],
                    "req1",
                    reasoning_effort="disabled",
                )

        assert data == {"ok": True}
        assert latency == 12
        secondary._single_chat.assert_called_once()
        primary_chat.assert_not_called()

    def test_configured_secondary_missing_fails_closed(self):
        from video_transcript_api.llm.multi_endpoint import MultiEndpointSyncLLMClient

        with patch.object(MultiEndpointSyncLLMClient, "__init__", lambda self, **k: None):
            client = MultiEndpointSyncLLMClient()
            client._endpoint_clients = {}
            client._model_endpoints = {"qwen*": "dashscope"}

        with pytest.raises(RuntimeError, match="endpoint dashscope.*unavailable"):
            client._client_for_model("qwen-plus-2025-12-01")


class TestSetDefaultConfigWiresEndpoints:
    def test_content_fallbacks_include_qwen_and_endpoints_loaded(self, monkeypatch):
        from video_transcript_api.llm import llm as llm_mod

        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
        config = {
            "llm": {
                "api_key": "sk-deepseek",
                "base_url": "https://api.deepseek.com/v1",
                "max_retries": 1,
                "total_timeout": 300,
                "content_fallbacks": {
                    "deepseek-v4-flash": ["deepseek-v4-pro", "qwen-plus-2025-12-01"],
                },
                "endpoints": {
                    "dashscope": {
                        "base_url": "https://dashscope.example.com/compatible-mode/v1",
                        "api_key_env": "DASHSCOPE_API_KEY",
                    }
                },
                "model_endpoints": {"qwen*": "dashscope"},
            },
            "risk_control": {"enabled": False},
        }

        with patch.object(llm_mod, "MultiEndpointSyncLLMClient") as multi_cls, patch.object(
            llm_mod, "SyncLLMClient"
        ) as sync_cls:
            multi_cls.return_value = MagicMock(name="multi")
            llm_mod.set_default_config(config)
            multi_cls.assert_called_once()
            kwargs = multi_cls.call_args.kwargs
            assert kwargs["base_url"] == "https://api.deepseek.com/v1"
            assert kwargs["content_fallbacks"]["deepseek-v4-flash"][-1] == (
                "qwen-plus-2025-12-01"
            )
            assert "dashscope" in kwargs["endpoint_clients"]
            sync_cls.assert_not_called()
