"""前端可配置项服务：配置 SCHEMA（核心 / 高级分组）驱动的读取（脱敏）/写入（数据库）。

设计要点：
- SCHEMA 单一来源声明界面可配置项；core=默认展示，advanced=默认折叠（小白看到的首屏只有核心项）。
- 不含 api.auth_token：它是“管理口令”，只在页面顶部作为加载/保存的钥匙，不重复成一个配置字段。
- 写入只落到 data/config.db：界面改 → 库里对应变量行更新 → 重启由 load_config 深合并到 config.jsonc 之上。
  页面填了用页面值，没填用默认值。读取永远脱敏，绝不回显完整密钥。
"""

from __future__ import annotations

from typing import Any

import requests

from ...utils.logging import (
    load_config,
    load_config_overrides,
    save_config_overrides,
)

# ============================================================
# AI Provider 注册表（OpenAI 兼容）：选择即带出 base_url + 获取地址 + 推荐模型
# ============================================================
PROVIDERS: list[dict[str, Any]] = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
     "api_key_url": "https://platform.deepseek.com/api_keys",
     "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1",
     "api_key_url": "https://platform.openai.com/api-keys",
     "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"]},
    {"id": "google", "name": "Google Gemini",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "api_key_url": "https://aistudio.google.com/apikey",
     "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]},
    {"id": "moonshot", "name": "Moonshot / Kimi", "base_url": "https://api.moonshot.cn/v1",
     "api_key_url": "https://platform.moonshot.cn/console/api-keys",
     "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]},
    {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "api_key_url": "https://open.bigmodel.cn/usercenter/apikeys",
     "models": ["glm-4-plus", "glm-4-air", "glm-4-flash"]},
    {"id": "dashscope", "name": "阿里云百炼 / 通义千问",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "api_key_url": "https://bailian.console.aliyun.com/?apiKey=1#/api-key",
     "models": ["qwen-plus", "qwen-turbo", "qwen-max"]},
    {"id": "volcengine", "name": "火山方舟 / 豆包",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "api_key_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
     "models": ["doubao-pro-32k", "doubao-pro-4k"]},
    {"id": "siliconflow", "name": "SiliconFlow 硅基流动", "base_url": "https://api.siliconflow.cn/v1",
     "api_key_url": "https://cloud.siliconflow.cn/account/ak",
     "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"]},
    {"id": "custom", "name": "自定义 (OpenAI 兼容)", "base_url": "", "api_key_url": "", "models": []},
]

# ============================================================
# 配置 SCHEMA。tier: "core"=默认展示；"advanced"=默认折叠。
# type: secret(密钥) | str | int | bool | select | model(随服务商给下拉)
# ============================================================
SCHEMA: list[dict[str, Any]] = [
    {"title": "AI 模型", "icon": "🤖", "tier": "core", "provider": True,
     "desc": "校对转录稿、生成总结所用的大模型。",
     "fields": [
         {"key": "llm.base_url", "label": "API Base URL", "type": "str"},
         {"key": "llm.api_key", "label": "API Key", "type": "secret", "provider_key_link": True},
         {"key": "llm.calibrate_model", "label": "校对模型", "type": "model"},
         {"key": "llm.summary_model", "label": "总结模型", "type": "model"},
     ]},
    {"title": "视频下载", "icon": "🎬", "tier": "core",
     "desc": "解析抖音 / 小红书等平台视频所需的密钥。",
     "fields": [
         {"key": "tikhub.api_key", "label": "TikHub API Key", "type": "secret",
          "key_url": "https://user.tikhub.io/dashboard/api"},
     ]},

    # ---- 以下默认折叠在“高级设置”里，小白可忽略 ----
    {"title": "转录服务地址", "icon": "🎙️", "tier": "advanced",
     "desc": "自行部署的语音转写服务 WebSocket 地址（不填则用配置文件默认）。",
     "fields": [
         {"key": "capswriter.server_url", "label": "CapsWriter 地址", "type": "str"},
         {"key": "funasr_spk_server.server_url", "label": "FunASR（分角色）地址", "type": "str"},
     ]},
    {"title": "YouTube 远程下载", "icon": "📺", "tier": "advanced",
     "desc": "可选：绕过本地 IP 风控的远程下载后端。",
     "fields": [
         {"key": "youtube_api_server.enabled", "label": "启用 YouTube API Server", "type": "bool"},
         {"key": "youtube_api_server.base_url", "label": "YouTube Server 地址", "type": "str"},
         {"key": "youtube_api_server.api_key", "label": "YouTube Server 密钥", "type": "secret"},
     ]},
    {"title": "通知", "icon": "📢", "tier": "advanced",
     "desc": "可选：任务完成 / 长任务提醒的推送渠道。",
     "fields": [
         {"key": "wechat.webhook", "label": "企业微信 Webhook", "type": "secret"},
         {"key": "feishu.webhook", "label": "飞书 Webhook", "type": "secret"},
         {"key": "feishu.secret", "label": "飞书签名密钥", "type": "secret"},
     ]},
    {"title": "性能与其它", "icon": "🧩", "tier": "advanced",
     "desc": "并发与开关，按需调整。",
     "fields": [
         {"key": "concurrent.max_workers", "label": "转录最大并发", "type": "int"},
         {"key": "concurrent.llm_max_workers", "label": "LLM 最大并发", "type": "int"},
         {"key": "risk_control.enabled", "label": "启用风控（敏感词脱敏）", "type": "bool"},
         {"key": "log.level", "label": "日志级别", "type": "select",
          "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
     ]},
]

# 路径 -> 类型 的快速查表（写入时按类型转换/校验）
_FIELD_TYPE: dict[str, str] = {f["key"]: f["type"] for g in SCHEMA for f in g["fields"]}

# 视为“未配置”的占位值（来自 config.example.jsonc）
_PLACEHOLDERS = {
    "", "your-auth-token-here", "your-llm-api-key-here", "your-tikhub-api-key-here",
    "your-api.com/v1", "https://your-api.com/v1", "your-webhook-url-here",
    "your-api-key-here", "http://your-youtube-api-server:8000",
}
_SECRET_TYPES = {"secret"}
_FIELD_OPTS = ("help", "key_url", "options", "provider_key_link")


def _get_by_path(cfg: dict, path: str) -> Any:
    node: Any = cfg
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _set_by_path(target: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = target
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _mask_secret(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    if s in _PLACEHOLDERS:
        return ""
    if len(s) <= 4:
        return "•" * len(s)
    return "•" * max(4, len(s) - 4) + s[-4:]


def _is_set(value: Any) -> bool:
    return value is not None and str(value) not in _PLACEHOLDERS


def _schema_groups(with_values: bool) -> list[dict[str, Any]]:
    """生成分组字段；with_values=True 时附带当前生效值（覆盖值或默认值）。"""
    cfg = load_config() if with_values else {}
    groups: list[dict[str, Any]] = []
    for g in SCHEMA:
        fields: list[dict[str, Any]] = []
        for spec in g["fields"]:
            field = {k: spec[k] for k in ("key", "label", "type") if k in spec}
            for opt in _FIELD_OPTS:
                if opt in spec:
                    field[opt] = spec[opt]
            if with_values:
                raw = _get_by_path(cfg, spec["key"])
                if spec["type"] in _SECRET_TYPES:
                    field["value"] = ""  # 密钥绝不回显
                    field["masked"] = _mask_secret(raw)
                    field["set"] = _is_set(raw)
                else:
                    value = "" if (isinstance(raw, str) and raw in _PLACEHOLDERS) else raw
                    field["value"] = value if value is not None else ""
                    field["set"] = _is_set(raw)
            fields.append(field)
        groups.append({
            "title": g["title"], "icon": g.get("icon", ""), "desc": g.get("desc", ""),
            "tier": g.get("tier", "core"), "provider": g.get("provider", False),
            "fields": fields,
        })
    return groups


def get_schema() -> dict[str, Any]:
    """返回配置结构（无当前值），供未登录时也能渲染整张表单。"""
    return {"providers": PROVIDERS, "groups": _schema_groups(with_values=False)}


def read_settings() -> dict[str, Any]:
    """返回配置结构 + 当前生效值（密钥脱敏）。"""
    return {"providers": PROVIDERS, "groups": _schema_groups(with_values=True)}


def fetch_provider_models(base_url: str, api_key: str) -> list[str]:
    """实时拉取服务商可用模型 id 列表（OpenAI 兼容的 GET {base_url}/models）。

    模型会持续迭代，写死的候选清单只作兜底；此处按当前 Key 拉取最新列表。
    - base_url 为空 → 回退到配置中的 llm.base_url。
    - api_key 为空 / 脱敏 / 占位 → 回退到配置中已保存的 llm.api_key。
    - 网络、鉴权、响应异常统一抛出携带友好信息的 RuntimeError，由上层转成可展示的提示。
    """
    cfg = load_config()
    base_url = (base_url or "").strip() or str(_get_by_path(cfg, "llm.base_url") or "").strip()
    key = (api_key or "").strip()
    if not key or "•" in key or key in _PLACEHOLDERS:
        key = str(_get_by_path(cfg, "llm.api_key") or "").strip()

    if not base_url or base_url in _PLACEHOLDERS:
        raise RuntimeError("未填写 API Base URL")
    if not key or key in _PLACEHOLDERS:
        raise RuntimeError("未填写 API Key（页面留空时会用已保存的 Key，但当前也未配置）")

    url = base_url.rstrip("/") + "/models"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=12)
    except requests.RequestException as exc:
        raise RuntimeError(f"无法连接服务商：{exc}") from exc

    if resp.status_code == 401:
        raise RuntimeError("API Key 无效（服务商返回 401）")
    if resp.status_code != 200:
        raise RuntimeError(f"服务商返回 HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("服务商响应不是合法 JSON") from exc

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("响应缺少 data 列表（可能不是 OpenAI 兼容接口）")

    ids = sorted({str(m.get("id")).strip() for m in items if isinstance(m, dict) and m.get("id")})
    if not ids:
        raise RuntimeError("服务商未返回任何模型")
    return ids


def _coerce(value: Any, kind: str) -> Any:
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if kind == "int":
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
    return value.strip() if isinstance(value, str) else value


def write_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """把前端提交的字段写入 overrides 数据库（按 SCHEMA 类型转换/过滤）。

    - 只处理 SCHEMA 已知字段；未知键忽略。
    - secret/str/select：空 = 不改动；secret 含脱敏圆点(•)忽略。
    - int：空或非法 = 不改动；bool：始终写入（开关要能从 true 改 false）。
    - 与既有 overrides 深合并后整体落盘。
    """
    payload = payload or {}
    new_override: dict[str, Any] = {}

    for key, raw in payload.items():
        kind = _FIELD_TYPE.get(key)
        if kind is None:
            continue
        if kind == "bool":
            _set_by_path(new_override, key, _coerce(raw, "bool"))
            continue
        if kind == "int":
            coerced = _coerce(raw, "int")
            if coerced is not None:
                _set_by_path(new_override, key, coerced)
            continue
        value = _coerce(raw, "str")
        if not value:
            continue  # 空 = 不改动
        if kind in _SECRET_TYPES and "•" in value:
            continue  # 脱敏回显，不当真值
        _set_by_path(new_override, key, value)

    if new_override:
        existing = load_config_overrides()
        save_config_overrides(_deep_merge_dicts(existing, new_override))

    return read_settings()


def _deep_merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
