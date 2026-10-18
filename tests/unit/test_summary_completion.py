"""Exercise real llm-compat orchestration against in-memory HTTP responses."""

from __future__ import annotations

import json

import httpx
import pytest
from llm_compat import SyncLLMClient

from video_transcript_api.llm import llm as llm_mod
from video_transcript_api.llm.multi_endpoint import MultiEndpointSyncLLMClient
from video_transcript_api.llm.response_client import CompletionAwareSyncLLMClient


PRIMARY_MODEL = "deepseek-v4-flash"
FALLBACK_MODEL = "qwen-plus-2025-12-01"
CONTENT = "A complete summary explains the question, evidence, and conclusion."


def _response(content=CONTENT, finish_reason="stop"):
    choice = {"message": {"role": "assistant", "content": content}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {
        "choices": [choice],
        "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
    }


@pytest.fixture
def install_http_stub(monkeypatch):
    """Bind each real client to MockTransport; any unstubbed request fails."""
    transports = []

    def reject_real_http(self):
        raise AssertionError("An unstubbed LLM HTTP request is forbidden in this test")

    monkeypatch.setattr(SyncLLMClient, "_get_http", reject_real_http)

    def install(client, response):
        payloads = []

        def handler(request):
            assert request.url.path.endswith("/chat/completions")
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json=response)

        http = httpx.Client(
            base_url=client._base_url,
            transport=httpx.MockTransport(handler),
        )
        transports.append(http)
        monkeypatch.setattr(client, "_get_http", lambda: http)
        return payloads

    yield install
    for http in transports:
        http.close()


def _client():
    return CompletionAwareSyncLLMClient(
        base_url="https://primary.example.invalid/v1",
        api_key="test-only-key",
        max_retries=0,
    )


def _call_text():
    return llm_mod.call_llm_api(
        model=PRIMARY_MODEL,
        prompt="Analyze the supplied transcript.",
        system_prompt="Return a faithful analysis.",
        task_type="summary",
    )


@pytest.mark.parametrize(
    "finish_reason",
    ["stop", "length", "aborted", "insufficient_system_resource"],
)
def test_real_chat_preserves_per_response_finish_reason(install_http_stub, finish_reason):
    client = _client()
    payloads = install_http_stub(client, _response(finish_reason=finish_reason))
    result = client.chat(PRIMARY_MODEL, [{"role": "user", "content": "Analyze this."}])
    assert result.finish_reason == finish_reason
    assert str(result) == CONTENT
    assert result.usage.total_tokens == 165
    assert len(payloads) == 1


def test_summary_accepts_normal_completion_and_sets_output_ceiling(
    monkeypatch, install_http_stub
):
    client = _client()
    payloads = install_http_stub(client, _response())
    monkeypatch.setattr(llm_mod, "get_sync_client", lambda: client)
    monkeypatch.setattr(llm_mod, "_default_config", None)

    assert _call_text() == CONTENT
    assert payloads[0]["max_tokens"] == 32768
    assert payloads[0]["stream"] is False


@pytest.mark.parametrize(
    "finish_reason",
    ["length", "aborted", "insufficient_system_resource", "resource_exhausted"],
)
def test_summary_rejects_incomplete_completion_even_with_nonempty_text(
    monkeypatch, install_http_stub, finish_reason
):
    client = _client()
    payloads = install_http_stub(client, _response(finish_reason=finish_reason))
    monkeypatch.setattr(llm_mod, "get_sync_client", lambda: client)
    monkeypatch.setattr(llm_mod, "_default_config", None)

    with pytest.raises(llm_mod.LLMCallError, match="finish_reason=" + finish_reason):
        _call_text()
    assert len(payloads) == 1


def test_summary_uses_configured_output_ceiling(monkeypatch, install_http_stub):
    client = _client()
    payloads = install_http_stub(client, _response())
    monkeypatch.setattr(llm_mod, "get_sync_client", lambda: client)
    monkeypatch.setattr(llm_mod, "_default_config", {"llm": {"summary_max_tokens": 16384}})

    assert _call_text() == CONTENT
    assert payloads[0]["max_tokens"] == 16384


def test_provider_without_finish_reason_remains_compatible(monkeypatch, install_http_stub):
    client = _client()
    install_http_stub(client, _response(finish_reason=None))
    monkeypatch.setattr(llm_mod, "get_sync_client", lambda: client)

    assert _call_text() == CONTENT


@pytest.mark.parametrize("finish_reason", ["length", "aborted"])
def test_non_summary_text_calls_keep_existing_behavior(
    monkeypatch, install_http_stub, finish_reason
):
    client = _client()
    payloads = install_http_stub(client, _response(finish_reason=finish_reason))
    monkeypatch.setattr(llm_mod, "get_sync_client", lambda: client)

    result = llm_mod.call_llm_api(
        model=PRIMARY_MODEL,
        prompt="Calibrate the supplied transcript.",
        task_type="calibration",
    )

    assert result == CONTENT
    assert "max_tokens" not in payloads[0]


@pytest.mark.parametrize("finish_reason", ["stop", "length", "aborted"])
def test_routed_fallback_retains_the_final_response_finish_reason(
    install_http_stub, finish_reason
):
    secondary = CompletionAwareSyncLLMClient(
        base_url="https://secondary.example.invalid/v1",
        api_key="test-only-secondary-key",
        max_retries=0,
    )
    client = MultiEndpointSyncLLMClient(
        base_url="https://primary.example.invalid/v1",
        api_key="test-only-primary-key",
        max_retries=0,
        content_fallbacks={PRIMARY_MODEL: [FALLBACK_MODEL]},
        endpoint_clients={"secondary": secondary},
        model_endpoints={"qwen*": "secondary"},
    )
    primary_payloads = install_http_stub(
        client, _response(content="I cannot assist", finish_reason="content_filter")
    )
    secondary_payloads = install_http_stub(
        secondary, _response(finish_reason=finish_reason)
    )

    result = client.chat(
        PRIMARY_MODEL,
        [{"role": "user", "content": "Analyze this."}],
        reasoning_effort="high",
    )

    assert result.finish_reason == finish_reason
    assert result.model == FALLBACK_MODEL
    assert result.fallback_from == PRIMARY_MODEL
    assert str(result) == CONTENT
    assert primary_payloads[0]["model"] == PRIMARY_MODEL
    assert secondary_payloads[0]["model"] == FALLBACK_MODEL
    assert secondary_payloads[0]["enable_thinking"] is True
    assert secondary_payloads[0]["thinking_budget"] == 8192
    assert "reasoning_effort" not in secondary_payloads[0]
    assert len(primary_payloads) == len(secondary_payloads) == 1


@pytest.mark.parametrize(
    "effort, enabled, budget",
    [(None, False, None), ("disabled", False, None), ("low", True, 1024),
     ("medium", True, 4096), ("high", True, 8192)],
)
def test_qwen_plus_reasoning_controls_reach_real_http(
    install_http_stub, effort, enabled, budget
):
    client = _client()
    payloads = install_http_stub(client, _response())
    client.chat(FALLBACK_MODEL, [{"role": "user", "content": "Analyze this."}],
                reasoning_effort=effort)
    assert payloads[0]["enable_thinking"] is enabled
    assert payloads[0].get("thinking_budget") == budget
    assert "reasoning_effort" not in payloads[0]


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "qwen-plus-2025-01-25", "qwen3.8-max"])
def test_other_models_keep_provider_reasoning_parameters(model):
    client = _client()
    payload = client._build_payload(model, [], reasoning_effort="high")
    assert "enable_thinking" not in payload
    assert "thinking_budget" not in payload


def test_explicit_qwen_thinking_options_are_preserved():
    client = _client()
    payload = client._build_payload(
        FALLBACK_MODEL, [], reasoning_effort="high", enable_thinking=False
    )
    assert payload["enable_thinking"] is False
    assert "thinking_budget" not in payload
    payload = client._build_payload(
        FALLBACK_MODEL, [], reasoning_effort="high", thinking_budget=512
    )
    assert payload["thinking_budget"] == 512
