"""Preserve completion metadata discarded by the installed llm-compat version."""

import re
from typing import Any

from llm_compat import SyncLLMClient


class CompletionAwareSyncLLMClient(SyncLLMClient):
    """Attach finish reason to each result, including routed fallback responses."""

    def _build_payload(
        self,
        model: str,
        messages: list[dict[str, Any]],
        reasoning_effort: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload = super()._build_payload(model, messages, reasoning_effort, **extra)
        # Qwen Plus snapshots use enable_thinking, not OpenAI reasoning_effort.
        # Commercial Qwen Plus supports our existing synchronous HTTP path.
        name = model.lower()
        snapshot = re.fullmatch(r"qwen-plus-(\d{4}-\d{2}-\d{2})", name)
        supports_thinking = name in {"qwen-plus", "qwen-plus-latest"} or (
            snapshot is not None and snapshot.group(1) >= "2025-04-28"
        )
        if supports_thinking:
            effort = payload.pop("reasoning_effort", None)
            enabled = effort in {"low", "medium", "high"}
            payload.setdefault("enable_thinking", enabled)
            if payload["enable_thinking"]:
                # Bound extra latency and token use instead of using the model maximum.
                budget = {"low": 1024, "medium": 4096, "high": 8192}.get(effort, 4096)
                payload.setdefault("thinking_budget", budget)
        return payload

    def _extract_result(self, data: dict[str, Any], **kwargs: Any):
        result = super()._extract_result(data, **kwargs)
        choice = data["choices"][0]
        result.finish_reason = choice.get("finish_reason")
        return result
