"""Offline environment configuration tests using no real config or data."""

from copy import deepcopy
import importlib
import json
import os
import sqlite3

import pytest

from video_transcript_api.config_env import (
    ENV_CONFIG_PATHS,
    LLM_MODEL_FIELDS,
    apply_environment_overrides,
    environment_managed_paths,
)


def test_environment_credentials_and_endpoints_override_without_mutating_inputs():
    config = {
        "llm": {"api_key": "file-key", "base_url": "https://file.invalid/v1"},
        "tikhub": {"api_key": "file-social-key", "cache_enabled": True},
        "api": {"port": 8000, "host": "127.0.0.1", "auth_token": "file-token"},
    }
    original = deepcopy(config)
    environ = {
        "LEARNFLUX_LLM_API_KEY": "env-key",
        "LEARNFLUX_LLM_BASE_URL": "https://env.invalid/v1",
        "LEARNFLUX_TIKHUB_API_KEY": "env-social-key",
        "LEARNFLUX_TIKHUB_BASE_URL": "https://social.invalid",
        "LEARNFLUX_AUTH_TOKEN": "env-token",
        "LEARNFLUX_API_HOST": "0.0.0.0",
        "LEARNFLUX_API_PORT": "8123",
        "LEARNFLUX_LLM_COLLECTOR_API_KEY": "env-collector-key",
    }
    before_env = dict(environ)
    result = apply_environment_overrides(config, environ)
    assert result["llm"]["api_key"] == "env-key"
    assert result["llm"]["base_url"] == "https://env.invalid/v1"
    assert result["llm"]["collector_api_key"] == "env-collector-key"
    assert result["tikhub"] == {
        "api_key": "env-social-key", "base_url": "https://social.invalid", "cache_enabled": True,
    }
    assert result["api"] == {"host": "0.0.0.0", "port": 8123, "auth_token": "env-token"}
    assert environment_managed_paths(config, environ) == {
        ENV_CONFIG_PATHS[name] for name in environ
    }
    result["llm"]["api_key"] = "modified-copy"
    assert config == original
    assert environ == before_env


def test_general_model_replaces_all_defaults_with_specific_models_taking_priority():
    config = {"llm": {"summary_model": "file-model", "future_model": "future-default"}}
    environ = {
        "LEARNFLUX_LLM_MODEL": "available-model",
        "LEARNFLUX_LLM_SUMMARY_MODEL": "special-summary",
        "LEARNFLUX_LLM_FUTURE_MODEL": "special-future",
    }
    result = apply_environment_overrides(config, environ)
    assert result["llm"]["summary_model"] == "special-summary"
    assert result["llm"]["future_model"] == "special-future"
    assert all(
        result["llm"][field] == "available-model"
        for field in LLM_MODEL_FIELDS if field != "summary_model"
    )
    assert environment_managed_paths(config, environ) == {
        f"llm.{field}" for field in (*LLM_MODEL_FIELDS, "future_model")
    }
    assert config["llm"] == {"summary_model": "file-model", "future_model": "future-default"}


def test_missing_empty_or_whitespace_values_keep_existing_configuration():
    config = {"llm": {"api_key": "file-key", "summary_model": "file-model"}, "api": {"port": 8000}}
    environ = {name: "" for name in ENV_CONFIG_PATHS}
    environ["LEARNFLUX_LLM_API_KEY"] = " \t"
    environ["LEARNFLUX_LLM_MODEL"] = " \n"
    assert apply_environment_overrides(config, environ) == config
    assert environment_managed_paths(config, environ) == set()
    assert apply_environment_overrides(config, {}) == config


@pytest.mark.parametrize("port", ["1", "8000", "65535"])
def test_valid_ports_are_integers(port):
    result = apply_environment_overrides({}, {"LEARNFLUX_API_PORT": port})
    assert result == {"api": {"port": int(port)}}


@pytest.mark.parametrize("port", [
    "0", "65536", "-1", "+8000", "8000.0", " ", "\t", "8000 ", " 8000",
    "８０００", "٨٠٠٠", "private-invalid-port", "1\n",
])
def test_invalid_port_errors_never_include_the_value(port):
    with pytest.raises(ValueError) as error:
        apply_environment_overrides({}, {"LEARNFLUX_API_PORT": port})
    assert str(error.value) == "Invalid LEARNFLUX_API_PORT"


def test_load_config_applies_environment_after_database_without_persisting_it(tmp_path, monkeypatch):
    logmod = importlib.import_module("video_transcript_api.utils.logging.logger")
    for name in list(os.environ):
        if name.startswith("LEARNFLUX_LLM_") or name in ENV_CONFIG_PATHS:
            monkeypatch.delenv(name)
    monkeypatch.setenv("LEARNFLUX_LLM_API_KEY", "env-key")
    monkeypatch.setenv("LEARNFLUX_LLM_MODEL", "env-model")
    monkeypatch.setattr(logmod, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(logmod, "_config_db_path", lambda: tmp_path / "config.db")
    monkeypatch.setattr("video_transcript_api.persistence.get_persistence_database", lambda: None)
    base = {"llm": {"api_key": "file-key", "summary_model": "file-model"}}
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(base), encoding="utf-8")
    logmod.reset_config_cache()
    try:
        logmod.save_config_overrides({"llm": {"api_key": "db-key", "summary_model": "db-model"}})
        effective = logmod.load_config()
        assert effective["llm"]["api_key"] == "env-key"
        assert effective["llm"]["summary_model"] == "env-model"
        assert logmod.load_config_overrides() == {
            "llm": {"api_key": "db-key", "summary_model": "db-model"},
        }
        assert json.loads(config_path.read_text(encoding="utf-8")) == base
        with sqlite3.connect(tmp_path / "config.db") as connection:
            assert connection.execute("SELECT COUNT(*) FROM config_overrides").fetchone()[0] == 2
        monkeypatch.delenv("LEARNFLUX_LLM_API_KEY")
        monkeypatch.delenv("LEARNFLUX_LLM_MODEL")
        logmod.reset_config_cache()
        assert logmod.load_config()["llm"] == {"api_key": "db-key", "summary_model": "db-model"}
    finally:
        logmod.reset_config_cache()
