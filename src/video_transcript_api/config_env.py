"""Apply private deployment configuration from environment variables.

This module deliberately uses only the standard library so startup scripts can
reuse the same mapping and validation without importing the application.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import os
import re
from typing import Any


LLM_MODEL_FIELDS = (
    "calibrate_model",
    "summary_model",
    "collection_summary_model",
    "collection_summary_module_model",
    "visual_learning_outline_model",
    "visual_learning_render_model",
    "study_chat_model",
)

# The wildcard is resolved against the LLM model fields in the loaded config.
ENV_CONFIG_PATHS: dict[str, str] = {
    "LEARNFLUX_LLM_API_KEY": "llm.api_key",
    "LEARNFLUX_LLM_BASE_URL": "llm.base_url",
    "LEARNFLUX_LLM_MODEL": "llm.*_model",
    **{
        f"LEARNFLUX_LLM_{field.upper()}": f"llm.{field}"
        for field in LLM_MODEL_FIELDS
    },
    "LEARNFLUX_TIKHUB_API_KEY": "tikhub.api_key",
    "LEARNFLUX_TIKHUB_BASE_URL": "tikhub.base_url",
    "LEARNFLUX_AUTH_TOKEN": "api.auth_token",
    "LEARNFLUX_API_HOST": "api.host",
    "LEARNFLUX_API_PORT": "api.port",
    "LEARNFLUX_LLM_COLLECTOR_URL": "llm.collector_url",
    "LEARNFLUX_LLM_COLLECTOR_PROJECT": "llm.collector_project",
    "LEARNFLUX_LLM_COLLECTOR_API_KEY": "llm.collector_api_key",
    "LEARNFLUX_CAPSWRITER_SERVER_URL": "capswriter.server_url",
    "LEARNFLUX_FUNASR_SERVER_URL": "funasr_spk_server.server_url",
    "LEARNFLUX_YOUTUBE_API_BASE_URL": "youtube_api_server.base_url",
    "LEARNFLUX_YOUTUBE_API_KEY": "youtube_api_server.api_key",
    "LEARNFLUX_OBSIDIAN_VAULT_PATH": "obsidian.vault_path",
    "LEARNFLUX_OBSIDIAN_VAULT_ID": "obsidian.vault_id",
}


def _environment_values(
    config: dict[str, Any], environ: Mapping[str, str]
) -> dict[str, Any]:
    """Resolve active overrides, without reading files or exposing values."""
    values: dict[str, Any] = {}
    llm = config.get("llm", {})
    model_fields = set(LLM_MODEL_FIELDS)
    if isinstance(llm, dict):
        model_fields.update(key for key in llm if key.endswith("_model"))

    general_model = environ.get("LEARNFLUX_LLM_MODEL", "")
    if general_model.strip():
        values.update({f"llm.{field}": general_model for field in model_fields})

    paths = ENV_CONFIG_PATHS | {
        f"LEARNFLUX_LLM_{field.upper()}": f"llm.{field}"
        for field in model_fields
    }
    for variable, path in paths.items():
        if variable == "LEARNFLUX_LLM_MODEL":
            continue
        value = environ.get(variable, "")
        if value == "":
            continue
        if variable == "LEARNFLUX_API_PORT":
            if not re.fullmatch(r"[0-9]{1,5}", value):
                raise ValueError("Invalid LEARNFLUX_API_PORT")
            port = int(value)
            if not 1 <= port <= 65535:
                raise ValueError("Invalid LEARNFLUX_API_PORT")
            values[path] = port
        elif value.strip():
            values[path] = value
    return values


def environment_managed_paths(
    config: dict[str, Any], environ: Mapping[str, str] | None = None
) -> set[str]:
    """Return dotted config paths controlled by nonempty environment values."""
    return set(_environment_values(config, os.environ if environ is None else environ))


def apply_environment_overrides(
    config: dict[str, Any], environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Return an independent config with environment values taking precedence.

    Empty values keep existing configuration. A common LLM model covers all
    main LLM model fields; specific model variables take precedence over it.
    No values are persisted, and neither input mapping is modified.
    """
    values = _environment_values(config, os.environ if environ is None else environ)
    result = deepcopy(config)
    for path, value in values.items():
        section, field = path.split(".", 1)
        if not isinstance(result.get(section), dict):
            result[section] = {}
        result[section][field] = value
    return result
