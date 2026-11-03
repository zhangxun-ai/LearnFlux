"""Offline boundaries for paid image requests, full-source planning and visual review."""

import base64
from dataclasses import replace
import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_transcript_api.image_diagrams.client import (
    ImageDiagramAPIError,
    OpenAIImageDiagramClient,
)
from video_transcript_api.image_diagrams.config import ImageDiagramSettings
from video_transcript_api.image_diagrams.prompts import build_image_prompt


def test_usage_does_not_depend_on_sdk_model_dump_internals():
    from video_transcript_api.image_diagrams.client import _usage

    class ConstructedUsage:
        def __init__(self):
            self.input_tokens = 100
            self.output_tokens_details = SimpleNamespace(reasoning_tokens=9)
            self._private = 42

        def model_dump(self, **kwargs):
            raise AttributeError("missing optional Pydantic bookkeeping")

    assert _usage(SimpleNamespace(usage=ConstructedUsage())) == {
        "input_tokens": 100, "output_tokens_details": {"reasoning_tokens": 9},
    }


def test_plan_schema_permits_only_real_source_references():
    from video_transcript_api.image_diagrams.client import _plan_schema
    schema = _plan_schema({"P1", "P9"})
    for field in ("must_show", "sections", "case_studies"):
        reference = schema["properties"][field]["items"]["properties"]["source_ref_ids"]["items"]
        assert set(reference["enum"]) == {"P1", "P9"}


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image-bytes"


def _settings(**changes):
    return replace(ImageDiagramSettings(api_key="not-a-real-key", enabled=True), **{"planning_workers": 1, "single_pass_chars": 0, **changes})


def _plan(*refs):
    return {
        "title": "Source overview",
        "learning_goal": "Understand the source relationships",
        "visual_story": "A clear source-grounded relationship and practical example",
        "case_studies": [],
        "must_show": [{"text": "A grounded relationship", "source_ref_ids": list(refs)}],
        "sections": [{"id": "section-a", "title": "Section A", "source_ref_ids": list(refs)}],
        "caveats": ["The author describes personal experience"],
    }


def _response(payload, **changes):
    return SimpleNamespace(
        output_text=json.dumps(payload),
        usage={"input_tokens": 20, "output_tokens": 10},
        _request_id="req-test", **changes,
    )


def _client(responses=None, **settings):
    sdk = Mock()
    if responses:
        sdk.responses.create.side_effect = responses
    return OpenAIImageDiagramClient(_settings(**settings), client=sdk), sdk


def test_settings_keep_key_in_environment_and_out_of_repr():
    settings = ImageDiagramSettings.from_config(
        {"image_diagrams": {"api_key": "must-not-use-this"}},
        {"OPENAI_API_KEY": "private-key"},
    )
    assert settings.enabled
    assert settings.api_key == "private-key"
    assert "private-key" not in repr(settings)
    assert settings.planning_workers == 3
    assert settings.single_pass_chars == 200000

    assert not ImageDiagramSettings.from_config({}, {}).enabled
    assert not ImageDiagramSettings.from_config(
        {"image_diagrams": {"enabled": False}}, {"OPENAI_API_KEY": "private-key"}
    ).enabled


def test_old_review_flags_cannot_enable_a_removed_model_call():
    settings = ImageDiagramSettings.from_config({"image_diagrams": {
        "review_enabled": True, "review_model": "old-vision-model",
    }}, {"OPENAI_API_KEY": "test-key"})
    assert not hasattr(settings, "review_enabled")
    assert not hasattr(settings, "review_model")
    assert not hasattr(OpenAIImageDiagramClient, "review")


def test_long_source_within_budget_uses_one_full_planning_call():
    client, sdk = _client([_response(_plan("P1", "P2"))], single_pass_chars=200000)
    source = {"paragraphs": [{"id": "P1", "text": "BEGIN" + "a" * 60000},
                             {"id": "P2", "text": "b" * 61000 + "TAIL"}]}
    plan = client.plan(source, {"request_id": "PRIVATE_QUEUE_ID", "regenerate": True})
    assert sdk.responses.create.call_count == 1
    prompt = sdk.responses.create.call_args.kwargs["input"][0]["content"][0]["text"]
    assert "BEGIN" in prompt and "TAIL" in prompt
    assert "PRIVATE_QUEUE_ID" not in prompt
    assert "regenerate" not in prompt
    assert plan["coverage"]["covered_paragraphs"] == 2
    assert plan["coverage"]["chunks"] == 1


@pytest.mark.parametrize("values", [
    {"enabled": "false"}, {"size": "0x2048"},
    {"size": "1025x1536"}, {"image_model": "other-provider"},
    {"max_daily_generations": -1}, {"timeout": 0}, {"planning_workers": 0}, {"planning_workers": 5},
])
def test_invalid_dedicated_configuration_fails_closed(values):
    with pytest.raises(ValueError):
        ImageDiagramSettings.from_config({"image_diagrams": values}, {})


def test_sdk_initialization_pins_official_endpoint_and_disables_retries(monkeypatch):
    import sys

    constructor = Mock()
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=constructor))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://must-not-receive-key.invalid")
    OpenAIImageDiagramClient(_settings())
    kwargs = constructor.call_args.kwargs
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["max_retries"] == 0
    assert kwargs["timeout"] == 240


def test_long_planning_covers_tail_and_every_character_before_synthesis():
    source = {
        "title": "Long source", "paragraphs": [
            {"id": "P1", "text": "A" * 1400},
            {"id": "P2", "text": "TAIL" * 75},
        ],
    }
    client, sdk = _client([
        _response(_plan("P1")), _response(_plan("P1")),
        _response(_plan("P1")), _response(_plan("P2")),
        _response(_plan("P1", "P2")),
    ], chunk_chars=500)
    progress = []
    result = client.plan(source, {"scope": "overview"}, on_progress=progress.append)
    calls = sdk.responses.create.call_args_list
    assert len(calls) == 5
    chunks = [call.kwargs["input"][0]["content"][0]["text"] for call in calls[:4]]
    material = [prompt.split("<source>\n")[1].split("\n</source>")[0] for prompt in chunks]
    assert sum(part.count("A") for part in material[:3]) == 1400
    assert "TAIL" * 75 in material[-1]
    assert result["coverage"] == {
        "mode": "full_chunked", "source_paragraphs": 2,
        "covered_paragraphs": 2, "source_chars": 1700, "chunks": 4,
    }
    assert len(result["usage"]["calls"]) == 5
    assert all(call.kwargs["store"] is False for call in calls)
    assert all(call.kwargs["text"]["format"]["strict"] for call in calls)
    assert [item["completed_chunks"] for item in progress] == [0, 1, 2, 3, 4, 4]
    assert progress[-1]["phase"] == "composing"
    assert progress[-1]["read_chars"] == 1700
    assert all(item["total_chunks"] == 4 for item in progress)
    assert all("source" not in item for item in progress)


def test_plan_rejects_invented_source_reference():
    client, sdk = _client([_response(_plan("P-invented"))])
    with pytest.raises(ImageDiagramAPIError, match="invalid_image_plan_reference") as raised:
        client.plan({"paragraphs": [{"id": "P1", "text": "Real source"}]}, {})
    assert raised.value.usage["planning"]["calls"][0]["usage"]["input_tokens"] == 20
    sdk.images.generate.assert_not_called()
    sdk.images.edit.assert_not_called()


def test_parallel_planning_is_bounded_and_synthesis_keeps_source_order():
    client, sdk = _client(chunk_chars=500, planning_workers=2)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = maximum = 0
    synthesis_order = []

    def respond(**kwargs):
        nonlocal active, maximum
        text = kwargs["input"][0]["content"][0]["text"]
        if kwargs["text"]["format"]["name"] == "image_diagram_synthesis":
            briefs = json.loads(text.split("<source_briefs>\n")[1].split("\n</source_briefs>")[0])
            synthesis_order.extend(brief["must_show"][0]["source_ref_ids"][0] for brief in briefs)
            return _response(_plan("P1", "P2", "P3"))
        ref = re.search(r"\[(P[0-9]+)\]", text).group(1)
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            if ref in {"P1", "P2"}:
                barrier.wait(timeout=3)
            return _response(_plan(ref))
        finally:
            with lock:
                active -= 1

    sdk.responses.create.side_effect = respond
    progress = []
    result = client.plan({"paragraphs": [{"id": f"P{i}", "text": "e" * 400} for i in range(1, 4)]}, {}, on_progress=progress.append)
    assert maximum == 2
    assert synthesis_order == ["P1", "P2", "P3"]
    assert [item["completed_chunks"] for item in progress] == [0, 1, 2, 3, 3]
    assert result["coverage"]["source_chars"] == 1200
    assert len(result["usage"]["calls"]) == 4


def test_parallel_failure_does_not_launch_tail_and_records_inflight_usage():
    client, sdk = _client(chunk_chars=500, planning_workers=3)
    barrier = threading.Barrier(3)

    def invalid(**kwargs):
        barrier.wait(timeout=3)
        return _response(_plan("invented"))

    sdk.responses.create.side_effect = invalid
    with pytest.raises(ImageDiagramAPIError, match="invalid_image_plan_reference") as raised:
        client.plan({"paragraphs": [{"id": f"P{i}", "text": "e" * 400} for i in range(1, 7)]}, {})
    assert sdk.responses.create.call_count == 3
    assert len(raised.value.usage["planning"]["calls"]) == 3
    sdk.images.edit.assert_not_called()


def test_invented_case_evidence_is_rejected_before_image_submission():
    plan = _plan("P1")
    plan["case_studies"] = [{"title": "Example", "text": "A real mechanism", "source_ref_ids": ["invented"]}]
    client, sdk = _client([_response(plan)])
    with pytest.raises(ImageDiagramAPIError, match="invalid_image_plan_reference"):
        client.plan({"paragraphs": [{"id": "P1", "text": "Source"}]}, {})
    sdk.images.edit.assert_not_called()


def test_planning_does_not_repeat_existing_summary_in_every_chunk():
    from video_transcript_api.image_diagrams.prompts import build_planning_prompt

    prompt = build_planning_prompt({"title": "Title", "summary": "REPEATED_OLD_SUMMARY"}, {}, [{"id": "P1", "text": "Author evidence"}])
    assert "Author evidence" in prompt
    assert "REPEATED_OLD_SUMMARY" not in prompt


def test_revision_plan_is_supplied_once_to_synthesis_and_to_short_sources():
    prior = {**_plan("P1"), "visual_story": "PRESERVE_THIS_STORY"}
    client, sdk = _client([_response(_plan("P1")), _response(_plan("P2")), _response(_plan("P1", "P2"))], chunk_chars=500)
    client.plan({"paragraphs": [{"id": "P1", "text": "a" * 400}, {"id": "P2", "text": "b" * 400}]}, {"previous_plan": prior})
    texts = [call.kwargs["input"][0]["content"][0]["text"] for call in sdk.responses.create.call_args_list]
    assert all("PRESERVE_THIS_STORY" not in text for text in texts[:2])
    assert "PRESERVE_THIS_STORY" in texts[-1]
    client, sdk = _client([_response(_plan("P1"))])
    client.plan({"paragraphs": [{"id": "P1", "text": "Short source"}]}, {"previous_plan": prior})
    assert "PRESERVE_THIS_STORY" in sdk.responses.create.call_args.kwargs["input"][0]["content"][0]["text"]


def test_source_limit_stops_before_any_provider_call():
    client, sdk = _client(max_source_chars=1000)
    with pytest.raises(ImageDiagramAPIError, match="image_source_too_large"):
        client.plan({"paragraphs": [{"id": "P1", "text": "x" * 1001}]}, {})
    sdk.responses.create.assert_not_called()


def test_progress_failure_preserves_confirmed_planning_usage():
    client, sdk = _client([_response(_plan("P1"))])

    def unavailable(progress):
        if progress["completed_chunks"]:
            raise ImageDiagramAPIError("image_progress_unavailable")

    with pytest.raises(ImageDiagramAPIError, match="image_progress_unavailable") as raised:
        client.plan({"paragraphs": [{"id": "P1", "text": "Source evidence"}]}, {}, on_progress=unavailable)
    assert sdk.responses.create.call_count == 1
    assert raised.value.usage["planning"]["calls"][0]["usage"]["input_tokens"] == 20
    sdk.images.edit.assert_not_called()


def test_prompt_keeps_complete_short_source_and_flexible_art_direction():
    source = {"paragraphs": [{"id": "P1", "text": "An exact original sentence."}]}
    result = build_image_prompt(source, _plan("P1"), {"style": "warm-guide"})
    assert "An exact original sentence." in result
    assert "P1" in result
    assert "3D" not in result
    assert "允许立体插画" in result


def test_long_image_prompt_uses_evidence_from_tail_with_disclosed_excerpting():
    source = {"paragraphs": [
        {"id": "P1", "text": "BEGIN" * 4000},
        {"id": "P2", "text": "MIDDLE" * 4000},
        {"id": "P3", "text": "TAIL" * 5000},
    ]}
    prompt = build_image_prompt(source, _plan("P1", "P2", "P3"), {"style": "handdrawn"})
    assert len(prompt) < 32000
    assert "不代表全文" in prompt
    assert "[P1] BEGIN" in prompt
    assert "[P2] MIDDLE" in prompt
    assert "[P3] TAIL" in prompt


def test_long_image_prompt_retains_evidence_for_sections_outside_headline_claims():
    source = {"paragraphs": [
        {"id": "P1", "text": "EARLY" * 8000},
        {"id": "P2", "text": "LATE_SECTION_EVIDENCE" * 2000},
    ]}
    plan = _plan("P1")
    plan["sections"].append({"id": "late", "title": "Late section", "source_ref_ids": ["P2"]})
    prompt = build_image_prompt(source, plan, {"style": "warm-guide"})
    assert "[P2] LATE_SECTION_EVIDENCE" in prompt
    assert len(prompt) <= 32000




def test_image_generation_uses_reference_edit_and_revision_first(tmp_path):
    previous, reference = tmp_path / "previous.png", tmp_path / "reference.png"
    previous.write_bytes(PNG)
    reference.write_bytes(PNG)
    client, sdk = _client()
    observed = {}

    def edit(**kwargs):
        observed["files"] = [Path(handle.name).name for handle in kwargs["image"]]
        observed["kwargs"] = kwargs
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(PNG).decode())], usage={"total_tokens": 7}, _request_id="image-req")

    sdk.images.edit.side_effect = edit
    result = client.generate("A source-grounded prompt", [reference], previous)
    assert observed["files"] == ["previous.png", "reference.png"]
    assert "图1为上一版" in observed["kwargs"]["prompt"]
    assert observed["kwargs"]["n"] == 1
    assert observed["kwargs"]["output_format"] == "png"
    assert result["image_bytes"] == PNG
    assert result["usage"] == {"total_tokens": 7}
    assert result["request_id"] == "image-req"
    sdk.images.generate.assert_not_called()


def test_timeout_is_unknown_and_never_automatically_retried():
    client, sdk = _client()
    sdk.images.generate.side_effect = TimeoutError("secret provider body must not escape")
    with pytest.raises(ImageDiagramAPIError) as raised:
        client.generate("prompt", [])
    assert raised.value.unknown_outcome
    assert str(raised.value) == "image_outcome_unknown"
    assert "secret" not in str(raised.value)
    assert sdk.images.generate.call_count == 1


def test_quota_failure_is_definite_and_secret_safe():
    class ProviderError(Exception):
        status_code = 429

    client, sdk = _client()
    sdk.images.generate.side_effect = ProviderError("sk-private-token")
    with pytest.raises(ImageDiagramAPIError) as raised:
        client.generate("prompt", [])
    assert not raised.value.unknown_outcome
    assert str(raised.value) == "openai_quota_or_rate_limit"
    assert "sk-private-token" not in str(raised.value)


def test_malformed_successful_image_is_not_treated_as_safe_to_resubmit():
    client, sdk = _client()
    sdk.images.generate.return_value = SimpleNamespace(data=[SimpleNamespace(b64_json="invalid")])
    with pytest.raises(ImageDiagramAPIError) as raised:
        client.generate("prompt", [])
    assert raised.value.unknown_outcome


def test_second_chunk_failure_keeps_confirmed_first_chunk_usage():
    client, sdk = _client([
        _response(_plan("P1")),
        TimeoutError("sensitive upstream error content"),
    ], chunk_chars=500)
    with pytest.raises(ImageDiagramAPIError) as raised:
        client.plan({"paragraphs": [
            {"id": "P1", "text": "A" * 400},
            {"id": "P2", "text": "B" * 400},
        ]}, {})
    calls = raised.value.usage["planning"]["calls"]
    assert len(calls) == 1
    assert calls[0]["usage"] == {"input_tokens": 20, "output_tokens": 10}
    assert sdk.responses.create.call_count == 2
    assert "sensitive" not in json.dumps(raised.value.usage)


def test_invalid_synthesis_preserves_all_confirmed_call_usage():
    client, _ = _client([
        _response(_plan("P1")), _response(_plan("P2")),
        _response(_plan("invented")),
    ], chunk_chars=500)
    with pytest.raises(ImageDiagramAPIError, match="invalid_image_plan_reference") as raised:
        client.plan({"paragraphs": [
            {"id": "P1", "text": "A" * 400},
            {"id": "P2", "text": "B" * 400},
        ]}, {})
    assert len(raised.value.usage["planning"]["calls"]) == 3


def test_invalid_json_response_preserves_its_billed_usage():
    client, _ = _client([SimpleNamespace(
        output_text="not JSON", usage={"input_tokens": 88}, _request_id="req-json",
    )])
    with pytest.raises(ImageDiagramAPIError, match="openai_invalid_json") as raised:
        client.plan({"paragraphs": [{"id": "P1", "text": "Original"}]}, {})
    assert raised.value.usage["planning"]["calls"][0]["usage"] == {"input_tokens": 88}


def test_malformed_image_response_keeps_numeric_usage_without_provider_text():
    client, sdk = _client()
    sdk.images.generate.return_value = SimpleNamespace(
        data=[], usage={"output_tokens": 900, "details": {"text_tokens": 20}, "error": "sk-private"},
        _request_id="req-image-123",
    )
    with pytest.raises(ImageDiagramAPIError) as raised:
        client.generate("prompt", [])
    assert raised.value.usage == {"image": {
        "model": "gpt-image-2", "usage": {"output_tokens": 900, "details": {"text_tokens": 20}},
        "request_id": "req-image-123",
    }}






