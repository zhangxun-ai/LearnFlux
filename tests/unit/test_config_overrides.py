"""Unit tests for the DB-backed frontend config-overrides layer.

Covers deep_merge / flatten / unflatten semantics and the SQLite override
roundtrip + load_config merge, with paths monkeypatched to a tmp dir so the
real project config and data/config.db are never touched.
"""

import json
import sqlite3
import sys

import pytest

# 包 __init__ 重导出了同名的 loguru `logger` 对象，遮蔽了 logger.py 子模块，
# 因此用 sys.modules 取真正的模块对象。
import video_transcript_api.utils.logging.logger  # noqa: F401
logmod = sys.modules["video_transcript_api.utils.logging.logger"]


@pytest.mark.unit
def test_deep_merge_nested_and_leaf_override():
    base = {"llm": {"api_key": "old", "base_url": "https://a/v1", "model": "x"},
            "api": {"port": 8000}}
    override = {"llm": {"api_key": "new", "base_url": "https://b/v1"}}
    merged = logmod._deep_merge(base, override)
    assert merged["llm"]["api_key"] == "new"
    assert merged["llm"]["base_url"] == "https://b/v1"
    assert merged["llm"]["model"] == "x"      # untouched nested leaf preserved
    assert merged["api"]["port"] == 8000      # untouched section preserved


@pytest.mark.unit
def test_deep_merge_does_not_mutate_inputs():
    base = {"llm": {"api_key": "old"}}
    logmod._deep_merge(base, {"llm": {"api_key": "new"}})
    assert base["llm"]["api_key"] == "old"


@pytest.mark.unit
def test_flatten_unflatten_roundtrip():
    nested = {"llm": {"api_key": "x", "base_url": "y"}, "tikhub": {"api_key": "z"}}
    flat = logmod._flatten(nested)
    assert flat == {"llm.api_key": "x", "llm.base_url": "y", "tikhub.api_key": "z"}
    assert logmod._unflatten(flat) == nested


@pytest.mark.unit
def test_db_overrides_roundtrip_and_load_config_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(logmod, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(logmod, "_config_db_path", lambda: tmp_path / "config.db")
    (tmp_path / "config.jsonc").write_text(
        json.dumps({"llm": {"api_key": "base-key", "model": "m1"}, "api": {"port": 8000}}),
        encoding="utf-8",
    )
    logmod.reset_config_cache()

    # No overrides yet -> plain config
    assert logmod.load_config()["llm"]["api_key"] == "base-key"

    # Write override to DB
    logmod.save_config_overrides({"llm": {"api_key": "frontend-key"}})

    cfg = logmod.load_config()  # save resets cache -> re-merge
    assert cfg["llm"]["api_key"] == "frontend-key"  # overridden
    assert cfg["llm"]["model"] == "m1"              # preserved from base
    assert cfg["api"]["port"] == 8000               # untouched section preserved
    assert logmod.load_config_overrides() == {"llm": {"api_key": "frontend-key"}}

    # Each variable is its own row (config_key = dotted path)
    rows = sqlite3.connect(str(tmp_path / "config.db")).execute(
        "SELECT config_key FROM config_overrides"
    ).fetchall()
    assert ("llm.api_key",) in rows

    logmod.reset_config_cache()


@pytest.mark.unit
def test_db_overrides_upsert_keeps_other_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(logmod, "_config_db_path", lambda: tmp_path / "config.db")
    logmod.save_config_overrides({"llm": {"api_key": "k1"}})
    logmod.save_config_overrides({"tikhub": {"api_key": "k2"}})  # separate write
    merged = logmod.load_config_overrides()
    assert merged == {"llm": {"api_key": "k1"}, "tikhub": {"api_key": "k2"}}
    logmod.reset_config_cache()


@pytest.mark.unit
def test_load_overrides_missing_db_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(logmod, "_config_db_path", lambda: tmp_path / "nope.db")
    assert logmod.load_config_overrides() == {}
