"""Unit tests for SCHEMA-driven settings_service: schema tiers, masking, writes.

Config access is monkeypatched so tests never touch real config / DB.
"""

import json
import asyncio

import pytest
from fastapi import HTTPException

from video_transcript_api.api.services import settings_service as svc
from video_transcript_api.api.routes import settings as settings_routes


def _field(data, key):
    for group in data["groups"]:
        for f in group["fields"]:
            if f["key"] == key:
                return f
    return None


@pytest.mark.unit
def test_mask_secret_hides_body_keeps_tail():
    m = svc._mask_secret("sk-1234567890abcd")
    assert m.endswith("abcd") and "1234567890" not in m
    assert svc._mask_secret("your-llm-api-key-here") == ""
    assert svc._mask_secret(None) == ""


@pytest.mark.unit
def test_schema_tiers_and_no_duplicate_auth_token():
    schema = svc.get_schema()
    assert any(p["id"] == "google" for p in schema["providers"])

    keys = {f["key"] for g in schema["groups"] for f in g["fields"]}
    # 核心项必须在
    for required in ("llm.base_url", "llm.api_key", "llm.calibrate_model", "tikhub.api_key"):
        assert required in keys
    # 管理口令不再作为配置字段（去重，仅顶部入口）
    assert "api.auth_token" not in keys
    assert "concurrent.local_asr_workers" in keys
    assert "concurrent.cloud_asr_workers" in keys
    assert "concurrent.max_workers" not in keys
    assert "concurrent.llm_max_workers" not in keys

    tiers = {g["title"]: g["tier"] for g in schema["groups"]}
    assert tiers["AI 模型"] == "core"
    assert tiers["视频下载"] == "core"
    # 让人懵的项收进高级（默认折叠）
    assert tiers["转录服务地址"] == "advanced"
    assert tiers["YouTube 远程下载"] == "advanced"

    # AI 服务商带 provider_key_link，便于在 Key 旁给跳转
    assert _field(schema, "llm.api_key").get("provider_key_link") is True
    # schema 不含当前值
    assert "value" not in _field(schema, "llm.api_key")


@pytest.mark.unit
def test_read_settings_masks_and_never_leaks(monkeypatch):
    monkeypatch.setattr(svc, "load_config", lambda: {
        "llm": {"api_key": "sk-secretXYZ9", "base_url": "https://api.deepseek.com/v1",
                "calibrate_model": "deepseek-chat", "summary_model": "deepseek-reasoner"},
        "tikhub": {"api_key": "tk-secret7777"},
        "capswriter": {"server_url": "ws://localhost:6016"},
        "log": {"level": "INFO"},
    })
    data = svc.read_settings()
    assert _field(data, "llm.api_key")["set"] is True
    assert _field(data, "llm.api_key")["value"] == ""
    assert _field(data, "llm.api_key")["masked"].endswith("XYZ9")
    assert _field(data, "llm.base_url")["value"] == "https://api.deepseek.com/v1"
    assert _field(data, "llm.calibrate_model")["value"] == "deepseek-chat"
    assert _field(data, "log.level")["value"] == "INFO"

    blob = json.dumps(data)
    for secret in ("sk-secretXYZ9", "tk-secret7777"):
        assert secret not in blob


@pytest.mark.unit
def test_read_settings_returns_effective_concurrency_and_trusted_limits(monkeypatch):
    monkeypatch.setattr(svc, "load_config", lambda: {
        "concurrent": {
            "local_asr_workers": 1,
            "cloud_asr_workers": 8,
            "cloud_asr_hard_limit": 2,
        }
    })

    data = svc.read_settings()

    assert _field(data, "concurrent.local_asr_workers")["value"] == 1
    assert _field(data, "concurrent.cloud_asr_workers")["value"] == 2
    assert data["concurrency_limits"] == {
        "local_asr_workers": 3,
        "cloud_asr_workers": 2,
    }


@pytest.mark.unit
def test_write_settings_types_and_filters(monkeypatch):
    captured = {}
    monkeypatch.setattr(svc, "load_config_overrides", lambda: {})
    monkeypatch.setattr(svc, "save_config_overrides", lambda o: captured.update({"o": o}))
    monkeypatch.setattr(svc, "load_config", lambda: {})

    svc.write_settings({
        "llm.api_key": "sk-real-new",
        "llm.base_url": "https://x/v1",
        "llm.calibrate_model": "",            # empty -> ignore
        "tikhub.api_key": "••••1234",         # masked -> ignore
        "youtube_api_server.enabled": True,   # bool -> write
        "concurrent.max_workers": "5",        # int -> coerce
        "log.level": "DEBUG",
        "api.auth_token": "should-be-ignored",  # not in schema -> ignore (de-dup)
        "unknown.key": "x",
    })
    o = captured["o"]
    assert o["llm"]["api_key"] == "sk-real-new"
    assert o["llm"]["base_url"] == "https://x/v1"
    assert "calibrate_model" not in o.get("llm", {})
    assert "tikhub" not in o
    assert o["youtube_api_server"]["enabled"] is True
    assert "concurrent" not in o  # 旧共享并发不再允许从浏览器改写
    assert o["log"]["level"] == "DEBUG"
    assert "api" not in o          # auth_token not a config field anymore
    assert "unknown" not in o


@pytest.mark.unit
def test_write_settings_bool_false_persists(monkeypatch):
    captured = {}
    monkeypatch.setattr(svc, "load_config_overrides", lambda: {})
    monkeypatch.setattr(svc, "save_config_overrides", lambda o: captured.update({"o": o}))
    monkeypatch.setattr(svc, "load_config", lambda: {})
    svc.write_settings({"youtube_api_server.enabled": False})
    assert captured["o"]["youtube_api_server"]["enabled"] is False


@pytest.mark.unit
def test_write_settings_noop_when_nothing_real(monkeypatch):
    called = {"save": False}
    monkeypatch.setattr(svc, "load_config_overrides", lambda: {})
    monkeypatch.setattr(svc, "save_config_overrides", lambda o: called.update({"save": True}))
    monkeypatch.setattr(svc, "load_config", lambda: {})
    svc.write_settings({"llm.api_key": "", "llm.base_url": ""})
    assert called["save"] is False


class _Controller:
    def __init__(self):
        self.updates = []

    def snapshot(self):
        return {
            "local_asr_workers": 1,
            "cloud_asr_workers": 3,
            "local_asr_hard_limit": 2,
            "cloud_asr_hard_limit": 4,
        }

    def update_soft_limits(self, **values):
        self.updates.append(values)


@pytest.mark.unit
def test_concurrency_write_is_partial_and_updates_runtime_after_persistence(monkeypatch):
    saved = {}
    controller = _Controller()
    monkeypatch.setattr(svc, "load_config_overrides", lambda: {
        "concurrent": {"local_asr_workers": 1, "cloud_asr_workers": 3}
    })
    monkeypatch.setattr(svc, "save_config_overrides", lambda value: saved.update(value))
    monkeypatch.setattr(svc, "load_config", lambda: {
        "concurrent": {
            "local_asr_workers": 1,
            "cloud_asr_workers": 3,
            "cloud_asr_hard_limit": 4,
        }
    })

    svc.write_settings(
        {"concurrent.local_asr_workers": "2"}, controller=controller
    )

    assert saved["concurrent"] == {
        "local_asr_workers": 2,
        "cloud_asr_workers": 3,
    }
    assert controller.updates == [{"local": 2, "cloud": 3}]


@pytest.mark.unit
@pytest.mark.parametrize("value", [True, 0, -1, 5])
def test_cloud_concurrency_write_rejects_invalid_or_over_hard(monkeypatch, value):
    controller = _Controller()
    with pytest.raises(svc.SettingsValidationError):
        svc.write_settings(
            {"concurrent.cloud_asr_workers": value}, controller=controller
        )


@pytest.mark.unit
def test_persistence_failure_does_not_change_runtime(monkeypatch):
    controller = _Controller()
    monkeypatch.setattr(svc, "load_config_overrides", lambda: {})
    monkeypatch.setattr(
        svc,
        "save_config_overrides",
        lambda value: (_ for _ in ()).throw(OSError("write failed")),
    )

    with pytest.raises(OSError):
        svc.write_settings(
            {"concurrent.local_asr_workers": 2}, controller=controller
        )

    assert controller.updates == []


@pytest.mark.unit
def test_settings_route_maps_concurrency_validation_to_422(monkeypatch):
    class Request:
        async def json(self):
            return {"concurrent.cloud_asr_workers": 99}

    monkeypatch.setattr(
        settings_routes,
        "write_settings",
        lambda payload, **kwargs: (_ for _ in ()).throw(
            svc.SettingsValidationError("invalid_cloud_limit")
        ),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            settings_routes.update_settings(Request(), user_info={"user_id": "u"})
        )

    assert raised.value.status_code == 422


class _FakeResp:
    """最小化的 requests 响应替身，仅供模型拉取测试。"""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.mark.unit
def test_fetch_provider_models_parses_sorts_and_falls_back_to_saved_key(monkeypatch):
    # base_url/api_key 留空 -> 回退到配置里已保存的值；解析 OpenAI 风格响应并去重排序
    monkeypatch.setattr(svc, "load_config", lambda: {
        "llm": {"base_url": "https://api.x.com/v1", "api_key": "sk-saved-key"}})
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = (headers or {}).get("Authorization")
        return _FakeResp(200, {"data": [{"id": "m-b"}, {"id": "m-a"}, {"id": "m-a"}]})

    monkeypatch.setattr(svc.requests, "get", fake_get)

    models = svc.fetch_provider_models("", "")
    assert models == ["m-a", "m-b"]
    assert seen["url"] == "https://api.x.com/v1/models"
    assert seen["auth"] == "Bearer sk-saved-key"


@pytest.mark.unit
def test_fetch_provider_models_raises_friendly_errors(monkeypatch):
    # 无 base_url/无 key -> 友好报错，且不应发起网络请求
    monkeypatch.setattr(svc, "load_config", lambda: {})

    def boom(*a, **k):  # 若被调用即说明过早发起了请求
        raise AssertionError("should not call network when config is empty")

    monkeypatch.setattr(svc.requests, "get", boom)
    with pytest.raises(RuntimeError):
        svc.fetch_provider_models("", "")

    # 401 -> 明确提示 Key 无效
    monkeypatch.setattr(svc, "load_config", lambda: {
        "llm": {"base_url": "https://api.x.com/v1", "api_key": "sk-x"}})
    monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _FakeResp(401, {}))
    with pytest.raises(RuntimeError, match="401"):
        svc.fetch_provider_models("https://api.x.com/v1", "sk-x")
