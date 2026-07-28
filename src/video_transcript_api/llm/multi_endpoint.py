"""Multi-endpoint LLM client routing for cross-provider content fallbacks.

llm-compat's SyncLLMClient keeps a single base_url/api_key for the whole
fallback chain. This module adds a thin routing layer so models such as
qwen-plus can hit DashScope while DeepSeek models stay on the primary endpoint.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from llm_compat import SyncLLMClient
from loguru import logger


def resolve_model_endpoint(
    model: str,
    model_endpoints: Optional[Mapping[str, str]],
) -> Optional[str]:
    """Return endpoint name for model, or None to use the primary client."""
    if not model_endpoints:
        return None
    model_lower = (model or "").lower()
    for pattern, endpoint_name in model_endpoints.items():
        if fnmatch.fnmatch(model_lower, str(pattern).lower()):
            return str(endpoint_name)
    return None


def _resolve_api_key(endpoint_cfg: Mapping[str, Any]) -> str:
    api_key = str(endpoint_cfg.get("api_key") or "").strip()
    if api_key:
        return api_key
    env_name = endpoint_cfg.get("api_key_env")
    if not env_name:
        return ""
    if isinstance(env_name, (list, tuple)):
        for name in env_name:
            value = os.environ.get(str(name), "").strip()
            if value:
                return value
        return ""
    return os.environ.get(str(env_name), "").strip()


def build_endpoint_clients(
    llm_cfg: Mapping[str, Any],
    *,
    max_retries: int,
    total_timeout: float,
    sensitive_detector: Any = None,
) -> Dict[str, SyncLLMClient]:
    """Build secondary SyncLLMClient instances from llm.endpoints config."""
    endpoints = llm_cfg.get("endpoints") or {}
    clients: Dict[str, SyncLLMClient] = {}
    if not isinstance(endpoints, Mapping):
        return clients

    for name, raw_cfg in endpoints.items():
        if name in {"default", "primary"}:
            continue
        if not isinstance(raw_cfg, Mapping):
            logger.warning(f"[LLM] Ignoring invalid endpoint config: {name}")
            continue
        base_url = str(raw_cfg.get("base_url") or "").strip()
        api_key = _resolve_api_key(raw_cfg)
        if not base_url or not api_key:
            logger.warning(
                f"[LLM] Endpoint {name} skipped (missing base_url or api key)"
            )
            continue
        clients[str(name)] = SyncLLMClient(
            base_url=base_url,
            api_key=api_key,
            max_retries=int(raw_cfg.get("max_retries", max_retries)),
            total_timeout=float(raw_cfg.get("total_timeout", total_timeout)),
            # Secondary clients never own the fallback chain; the primary client does.
            content_fallbacks=None,
            collector_url=None,
            sensitive_detector=sensitive_detector,
        )
        logger.info(f"[LLM] Secondary endpoint ready: {name}")
    return clients


class MultiEndpointSyncLLMClient(SyncLLMClient):
    """SyncLLMClient that routes per-model HTTP calls to secondary endpoints."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        endpoint_clients: Optional[Dict[str, SyncLLMClient]] = None,
        model_endpoints: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(base_url=base_url, api_key=api_key, **kwargs)
        self._endpoint_clients = dict(endpoint_clients or {})
        self._model_endpoints = dict(model_endpoints or {})

    def _client_for_model(self, model: str) -> SyncLLMClient:
        endpoint_name = resolve_model_endpoint(model, self._model_endpoints)
        if not endpoint_name:
            return self
        client = self._endpoint_clients.get(endpoint_name)
        if client is None:
            raise RuntimeError(
                f"LLM endpoint {endpoint_name} is unavailable for model {model}"
            )
        return client

    def _single_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        request_id: str,
        *,
        reasoning_effort: str | None = None,
        remaining_timeout: float | None = None,
        **extra: Any,
    ) -> Tuple[dict[str, Any], int]:
        client = self._client_for_model(model)
        if client is self:
            return super()._single_chat(
                model,
                messages,
                request_id,
                reasoning_effort=reasoning_effort,
                remaining_timeout=remaining_timeout,
                **extra,
            )
        logger.info(
            f"[{request_id}] LLM endpoint route | model={model} | secondary endpoint"
        )
        return client._single_chat(
            model,
            messages,
            request_id,
            reasoning_effort=reasoning_effort,
            remaining_timeout=remaining_timeout,
            **extra,
        )

    def close(self) -> None:
        for client in self._endpoint_clients.values():
            try:
                client.close()
            except Exception:
                logger.debug("[LLM] Secondary endpoint close failed", exc_info=True)
        super().close()
