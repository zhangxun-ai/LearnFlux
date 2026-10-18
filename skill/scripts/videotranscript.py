#!/usr/bin/env python3
"""LearnFlux CLI client — stdlib-only, cross-platform.

Subcommands:
  doctor         Validate local configuration, connectivity, and authentication.
  submit         Submit a transcription task for a video/podcast URL.
  status         Check the status of a task by task_id.
  result         Fetch the finished text (calibrated/summary/transcript) by view_token.
  history        Query past tasks with filters.
  filter-options List available filter values (platforms/authors/webhooks).
  profile        Show the current user profile.
  health         Probe the server health endpoint.

Env:
  VIDEO_TRANSCRIPT_API_BASE_URL  e.g. http://localhost:8000  (required for most ops)
  VIDEO_TRANSCRIPT_API_TOKEN     Bearer token                 (required for auth'd ops)

Exit codes:
  0 success
  1 business failure (task failed, not found, empty result)
  2 transport/infra (network, 5xx, auth 4xx)
  3 configuration (missing env, bad args)
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import textwrap
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

DEFAULT_TIMEOUT = 30
RESULT_TYPES = ("calibrated", "summary", "transcript")


# ---------- Error classes ----------


class ConfigError(Exception):
    """Missing env var or bad CLI args — exit 3."""


class TransportError(Exception):
    """Network / 5xx / auth failure — exit 2."""


class BusinessError(Exception):
    """Valid response but logical failure (task failed, 404) — exit 1."""


# ---------- Env fallback ----------

_env_loaded = False


def _env_file_paths() -> list[str]:
    """Return supported user config files in precedence order."""
    home = os.path.expanduser("~")
    configured_path = os.environ.get("LEARNFLUX_AGENT_CONFIG")
    paths = [
        configured_path,
        os.path.join(home, ".learnflux", "agent.env"),
        os.path.join(home, ".hermes", ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    ]
    return list(dict.fromkeys(path for path in paths if path))


def _load_env_files() -> None:
    """从常见配置文件补全缺失的环境变量（不覆盖已有值）。

    按优先级依次尝试：
    1. $LEARNFLUX_AGENT_CONFIG — 用户显式指定的配置文件
    2. ~/.learnflux/agent.env  — 跨 Agent 的推荐配置位置
    3. ~/.hermes/.env          — Hermes 的标准 env 存储
    4. 脚本同级目录的 .env    — 本地开发用
    5. ~/.claude/settings.json — Claude Code 的 env 字段
    """
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True

    # .env 格式：KEY=VALUE（忽略注释和空行）
    for env_path in _env_file_paths():
        if os.path.isfile(env_path):
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        if key and key not in os.environ:
                            os.environ[key] = value
            except OSError:
                pass

    # Claude Code settings.json
    home = os.path.expanduser("~")
    settings_path = os.path.join(home, ".claude", "settings.json")
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.loads(f.read())
            env_dict = settings.get("env")
            if isinstance(env_dict, dict):
                for key, value in env_dict.items():
                    if key not in os.environ and isinstance(value, str):
                        os.environ[key] = value
        except (OSError, json.JSONDecodeError):
            pass


# ---------- HTTP helpers ----------


def _require_env(name: str) -> str:
    _load_env_files()
    val = os.environ.get(name)
    if not val:
        raise ConfigError(
            f"环境变量 {name} 未设置。请写入环境变量或 ~/.learnflux/agent.env，"
            f"不要把密钥粘贴到 Agent 对话中；配置方法参见 skill/README.md。"
        )
    return val


def _validate_http_url(value: str, label: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse.urlsplit(normalized)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(f"{label} 必须是完整的 http:// 或 https:// URL。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigError(f"{label} 不能包含账号、密码、查询参数或片段。")
    return normalized


def _base_url() -> str:
    """API 调用用的地址。通常是内网/局域网/tailnet，优先保证低延迟。"""
    return _validate_http_url(
        _require_env("VIDEO_TRANSCRIPT_API_BASE_URL"),
        "VIDEO_TRANSCRIPT_API_BASE_URL",
    )


def _public_url() -> str:
    """给用户看的地址。若设置了 PUBLIC_URL 就用它（公网可访问），否则 fallback 到 BASE_URL。

    场景：服务端实际跑在内网（如 tailnet / 局域网），但用户可能从公网打开 `/view/<token>` 页面。
    这时需要两个地址分离：API 请求走内网（快），给用户的链接用公网域名。
    """
    _load_env_files()
    pub = os.environ.get("VIDEO_TRANSCRIPT_API_PUBLIC_URL")
    if pub:
        return _validate_http_url(pub, "VIDEO_TRANSCRIPT_API_PUBLIC_URL")
    return _base_url()


def _auth_headers() -> dict[str, str]:
    token = _require_env("VIDEO_TRANSCRIPT_API_TOKEN")
    return {"Authorization": f"Bearer {token}"}


def _request(
    method: str,
    path: str,
    *,
    auth: bool = True,
    json_body: dict | None = None,
    query: dict | None = None,
    accept_text: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    passthrough_statuses: tuple[int, ...] = (),
) -> tuple[int, Any]:
    """Send an HTTP request and return (status_code, parsed_body).

    parsed_body is dict/list for JSON responses, str when accept_text=True.
    Raises TransportError on network failures, 5xx, or 401/403.
    """
    url = f"{_base_url()}{path}"
    if query:
        qs = {k: v for k, v in query.items() if v is not None and v != ""}
        if qs:
            url = f"{url}?{urlparse.urlencode(qs, doseq=True)}"

    headers = {"User-Agent": "videotranscript-skill/1.0"}
    if auth:
        headers.update(_auth_headers())
    if accept_text:
        headers["Accept"] = "text/plain, */*"
    else:
        headers["Accept"] = "application/json"

    data_bytes: bytes | None = None
    if json_body is not None:
        data_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = urlrequest.Request(url=url, data=data_bytes, method=method, headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read()
    except urlerror.HTTPError as e:
        status = e.code
        raw = e.read() if e.fp else b""
    except urlerror.URLError as e:
        raise TransportError(f"网络错误: {e.reason}") from e
    except TimeoutError as e:
        raise TransportError(f"请求超时 ({timeout}s)。请检查服务地址和网络。") from e

    # Classify
    if status in (401, 403):
        raise TransportError(
            f"认证失败 (HTTP {status})。检查 VIDEO_TRANSCRIPT_API_TOKEN 是否正确。"
        )
    if status >= 500 and status not in passthrough_statuses:
        snippet = raw[:500].decode("utf-8", errors="replace")
        raise TransportError(f"服务端错误 (HTTP {status}): {snippet}")

    if accept_text:
        return status, raw.decode("utf-8", errors="replace")

    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        # Fallback: return raw text for non-JSON bodies
        return status, raw.decode("utf-8", errors="replace")


# ---------- Output helpers ----------


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_markdown_kv(title: str, kv: dict[str, Any]) -> None:
    print(f"# {title}\n")
    for k, v in kv.items():
        if v is None or v == "":
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        print(f"- **{k}**: {v}")


# ---------- Commands ----------


def _emit_doctor(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        _emit_json(payload)
        return

    print("# LearnFlux Doctor\n")
    labels = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
    for check in payload["checks"]:
        label = labels.get(check["status"], check["status"].upper())
        detail = check.get("detail") or ""
        print(f"- [{label}] {check['name']}: {detail}")
    for warning in payload["warnings"]:
        print(f"- [WARN] {warning['code']}: {warning['message']}")
    print("\nREADY" if payload["ready"] else "\nNOT READY")


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check configuration and connectivity without exposing credentials."""
    checks: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    payload: dict[str, Any] = {"ready": False, "checks": checks, "warnings": warnings}

    try:
        base_url = _base_url()
        _require_env("VIDEO_TRANSCRIPT_API_TOKEN")
        public_url = _public_url()
    except ConfigError as exc:
        checks.append({"name": "configuration", "status": "error", "detail": str(exc)})
        _emit_doctor(payload, args.format)
        return 3

    checks.extend(
        [
            {"name": "base_url", "status": "ok", "detail": base_url},
            {"name": "token", "status": "ok", "detail": "configured (value hidden)"},
            {"name": "public_url", "status": "ok", "detail": public_url},
        ]
    )

    parsed_base = urlparse.urlsplit(base_url)
    if parsed_base.scheme == "http" and parsed_base.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        warnings.append(
            {
                "code": "unencrypted_http",
                "message": "Bearer tokens are visible on plain HTTP networks; prefer HTTPS or a trusted encrypted tunnel.",
            }
        )

    if os.name != "nt":
        for env_path in _env_file_paths():
            if not os.path.isfile(env_path):
                continue
            try:
                mode = stat.S_IMODE(os.stat(env_path).st_mode)
            except OSError:
                continue
            if mode & 0o077:
                warnings.append(
                    {
                        "code": "config_file_permissions",
                        "message": f"Protect {env_path} with chmod 600.",
                    }
                )

    try:
        health_status, health_body = _request("GET", "/health", auth=False)
    except TransportError as exc:
        checks.append({"name": "health", "status": "error", "detail": str(exc)})
        _emit_doctor(payload, args.format)
        return 2
    health_value = health_body.get("status") if isinstance(health_body, dict) else None
    if health_status != 200:
        checks.append(
            {"name": "health", "status": "error", "detail": f"HTTP {health_status}"}
        )
        _emit_doctor(payload, args.format)
        return 2
    checks.append(
        {
            "name": "health",
            "status": "ok" if health_value != "degraded" else "warning",
            "detail": str(health_value or f"HTTP {health_status}"),
        }
    )

    try:
        profile_status, profile_body = _request("GET", "/api/users/profile")
    except TransportError as exc:
        checks.append({"name": "authentication", "status": "error", "detail": str(exc)})
        _emit_doctor(payload, args.format)
        return 2
    if not isinstance(profile_body, dict):
        checks.append(
            {
                "name": "authentication",
                "status": "error",
                "detail": "profile response is not JSON",
            }
        )
        _emit_doctor(payload, args.format)
        return 2
    profile_code = profile_body.get("code")
    if profile_status != 200 or profile_code not in (None, 200):
        checks.append(
            {
                "name": "authentication",
                "status": "error",
                "detail": f"HTTP {profile_status}, code={profile_code}",
            }
        )
        _emit_doctor(payload, args.format)
        return 2

    profile_data = profile_body.get("data") or {}
    if not isinstance(profile_data, dict):
        checks.append(
            {
                "name": "authentication",
                "status": "error",
                "detail": "profile data has an invalid shape",
            }
        )
        _emit_doctor(payload, args.format)
        return 2
    user_info = profile_data.get("user_info") or {}
    if not isinstance(user_info, dict):
        user_info = {}
    checks.append(
        {
            "name": "authentication",
            "status": "ok",
            "detail": f"user={user_info.get('user_id') or 'unknown'}",
        }
    )
    if (
        not profile_data.get("is_multi_user_mode")
        or user_info.get("user_id") == "legacy_user"
    ):
        warnings.append(
            {
                "code": "legacy_admin_token",
                "message": (
                    "This is the single-token admin mode. Keep the token on trusted "
                    "devices and never publish it."
                ),
            }
        )

    payload["ready"] = True
    _emit_doctor(payload, args.format)
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {"url": args.url}
    if args.speaker:
        body["use_speaker_recognition"] = True
    webhook = args.webhook or os.environ.get("VIDEO_TRANSCRIPT_API_WECHAT_WEBHOOK")
    if webhook:
        body["wechat_webhook"] = webhook
    feishu_webhook = args.feishu_webhook or os.environ.get(
        "VIDEO_TRANSCRIPT_API_FEISHU_WEBHOOK"
    )
    if feishu_webhook:
        body["feishu_webhook"] = feishu_webhook
    if args.download_url:
        body["download_url"] = args.download_url
    meta = {}
    if args.title:
        meta["title"] = args.title
    if args.author:
        meta["author"] = args.author
    if args.description:
        meta["description"] = args.description
    if meta:
        body["metadata_override"] = meta

    status, resp = _request(
        "POST",
        "/api/transcribe",
        json_body=body,
        passthrough_statuses=(503,),
    )

    if status in (400, 409, 422):
        raise BusinessError(f"请求参数有误: {resp}")
    if status == 404:
        raise BusinessError(f"资源不存在: {resp}")
    if status == 503:
        raise TransportError("任务队列已满，请稍后重试（HTTP 503）")
    if status not in (200, 202):
        raise TransportError(f"提交失败 HTTP {status}: {resp}")

    data = (resp or {}).get("data") or {}
    task_id = data.get("task_id")
    view_token = data.get("view_token")
    if not task_id:
        raise TransportError(f"响应缺少 task_id: {resp}")

    if args.format == "json":
        _emit_json(
            {
                "task_id": task_id,
                "view_token": view_token,
                "view_url": f"{_public_url()}/view/{view_token}" if view_token else None,
                "raw": resp,
            }
        )
    else:
        base = _public_url()
        view_url = f"{base}/view/{view_token}" if view_token else "(view_token 缺失)"
        print(
            textwrap.dedent(
                f"""\
            # 任务已提交

            - **预计耗时**: 5–15 分钟（取决于视频时长与队列）
            - **view_token**: `{view_token}`

            **查看链接（请单独发送给用户）**:
            [{view_url}]({view_url})

            后续调用 `result {view_token} --type summary` 查进度和拉总结。
            返回 202 = 还在处理，返回 200 = 完成。"""
            ).strip()
        )
    return 0


def _lookup_view_token_by_task_id(task_id: str) -> str | None:
    """反查 task_id 对应的 view_token。

    服务端的 `/api/task/{task_id}` 在成功时（尤其命中缓存）不带 view_token，
    agent 要拉结果必须要 view_token。这里扫一遍 `/api/audit/history` 的
    success 条目（limit=1000 覆盖最近几千条），按 task_id 精确匹配。

    出错/未找到时返回 None，由调用方兜底提示用户访问 web 页面。
    """
    try:
        status, resp = _request(
            "GET",
            "/api/audit/history",
            query={"limit": 1000, "offset": 0, "status": "success"},
        )
        if status != 200 or not isinstance(resp, dict):
            return None
        data = resp.get("data") or {}
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            return None
        for it in items:
            if isinstance(it, dict) and it.get("task_id") == task_id:
                return it.get("view_token") or None
    except Exception:
        return None
    return None


def cmd_status(args: argparse.Namespace) -> int:
    status, resp = _request("GET", f"/api/task/{urlparse.quote(args.task_id)}")

    if status == 404:
        raise BusinessError(f"任务不存在: {args.task_id}")
    if status not in (200, 202, 500):
        raise TransportError(f"查询失败 HTTP {status}: {resp}")

    data = (resp or {}).get("data") or {}
    message = (resp or {}).get("message") or ""

    # 当前服务通常以 HTTP 200 返回查询结果，任务状态以 data.status 为准。
    # 为兼容旧部署，仍保留对 HTTP 202/500 的合理回退。
    if status == 200:
        task_status = data.get("status") or "success"
    elif status == 202:
        task_status = data.get("status") or "processing"
    elif status == 500:
        task_status = data.get("status") or "failed"
    else:
        task_status = data.get("status") or "unknown"

    # success 但响应不含 view_token（常见于缓存命中）→ 反查 history 补齐。
    # 这样 agent 拿 task_id 就能闭环到 result，不必再找用户要 view_token。
    view_token = data.get("view_token")
    if task_status == "success" and not view_token:
        view_token = _lookup_view_token_by_task_id(args.task_id)

    if args.format == "json":
        _emit_json(
            {
                "http_status": status,
                "task_status": task_status,
                "view_token": view_token,
                "data": data,
                "raw": resp,
            }
        )
        return 1 if task_status == "failed" else 0

    # markdown
    kv: dict[str, Any] = {
        "task_status": task_status,
        "message": message or data.get("message"),
        "view_token": view_token,
    }
    if task_status == "success":
        kv["video_title"] = data.get("video_title")
        kv["author"] = data.get("author")
        kv["cached"] = data.get("cached")
        kv["speaker_recognition"] = data.get("speaker_recognition")
    if task_status == "failed":
        kv["error"] = data.get("error") or message
    if task_status in ("queued", "processing"):
        kv["progress"] = data.get("progress") or data.get("step")
    _emit_markdown_kv(f"任务状态: {task_status}", kv)

    if task_status == "success":
        if view_token:
            vurl = f"{_public_url()}/view/{view_token}"
            print(
                f"\n结果已就绪 —— `result {view_token} --type summary` "
                f"或访问 [{vurl}]({vurl})"
            )
        else:
            print(
                "\n结果已就绪，但没能反查到 view_token（可能任务过旧，已不在最近 1000 条历史里）。"
                f" 请使用 submit 时保存的 view_token 调 `result`，或直接访问 {_public_url()}/view/<view_token>。"
            )
    return 1 if task_status == "failed" else 0


def cmd_result(args: argparse.Namespace) -> int:
    if args.type not in RESULT_TYPES:
        raise ConfigError(f"--type 必须是 {RESULT_TYPES} 之一，得到 {args.type!r}")

    path = f"/view/{urlparse.quote(args.view_token)}"
    status, text = _request(
        "GET",
        path,
        auth=False,
        query={"raw": args.type},
        accept_text=True,
        passthrough_statuses=(500,),
    )

    if status == 404:
        raise BusinessError("view_token 无效或已过期。")
    if status == 410:
        raise BusinessError("结果已被清理 (HTTP 410)。原始文件已从服务器删除。")
    if status == 500:
        raise BusinessError("任务处理失败。请打开查看链接确认原因，修正后再重新提交。")
    if status == 202:
        # Still processing — surface to caller with exit 0 and a hint
        if args.format == "json":
            _emit_json(
                {
                    "ready": False,
                    "http_status": 202,
                    "view_url": f"{_public_url()}/view/{args.view_token}",
                    "text": text,
                }
            )
        else:
            print("任务仍在处理中 (HTTP 202)。稍后再拉一次。")
        return 0
    if status != 200:
        raise TransportError(f"获取结果失败 HTTP {status}: {text[:300] if isinstance(text, str) else text}")

    if not text or (isinstance(text, str) and not text.strip()):
        raise BusinessError(f"结果为空 (type={args.type})。可能是该类型未生成。")

    if args.format == "json":
        _emit_json(
            {
                "ready": True,
                "type": args.type,
                "view_url": f"{_public_url()}/view/{args.view_token}",
                "text": text,
            }
        )
    else:
        print(text)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    query = {
        "start_date": args.start,
        "end_date": args.end,
        "webhook": args.webhook,
        "platform": args.platform,
        "author": args.author,
        "q": args.q,
        "status": args.status,
        "limit": args.limit,
        "offset": args.offset,
    }
    http_status, resp = _request("GET", "/api/audit/history", query=query)

    if http_status != 200:
        raise TransportError(f"历史查询失败 HTTP {http_status}: {resp}")

    data = (resp or {}).get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    if items is None:
        items = []
    total = data.get("total") if isinstance(data, dict) else None

    if args.format == "json":
        _emit_json(resp)
        return 0

    header = f"# 历史任务 ({len(items)} 条"
    if total is not None:
        header += f" / 共 {total}"
    header += ")"
    print(header)
    if not items:
        print("\n_（无匹配记录）_")
        return 0
    for it in items:
        if not isinstance(it, dict):
            continue
        title = it.get("title") or "(无标题)"
        platform = it.get("platform") or "?"
        author = it.get("author") or ""
        when = it.get("request_time") or ""
        status_val = it.get("status") or ""
        vt = it.get("view_token") or ""
        print(f"\n## {title}")
        bits = [f"平台: {platform}"]
        if author:
            bits.append(f"作者: {author}")
        if status_val:
            bits.append(f"状态: {status_val}")
        print("- " + "  ".join(bits))
        if when:
            print(f"- 时间: {when}")
        if vt:
            url = f"{_public_url()}/view/{vt}"
            print(f"- 查看: [{url}]({url})")
    return 0


def cmd_filter_options(args: argparse.Namespace) -> int:
    status, resp = _request("GET", "/api/audit/filter-options")
    if status != 200:
        raise TransportError(f"获取过滤选项失败 HTTP {status}: {resp}")
    if args.format == "json":
        _emit_json(resp)
    else:
        data = (resp or {}).get("data") or resp or {}
        _emit_markdown_kv("过滤选项", data if isinstance(data, dict) else {"items": data})
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    status, resp = _request("GET", "/api/users/profile")
    if status != 200:
        raise TransportError(f"获取 profile 失败 HTTP {status}: {resp}")
    if args.format == "json":
        _emit_json(resp)
    else:
        data = (resp or {}).get("data") or resp or {}
        _emit_markdown_kv("当前用户", data if isinstance(data, dict) else {"raw": data})
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    status, resp = _request("GET", "/health", auth=False)
    if args.format == "json":
        _emit_json({"http_status": status, "body": resp})
    else:
        _emit_markdown_kv(
            f"Health (HTTP {status})",
            resp if isinstance(resp, dict) else {"body": resp},
        )
    return 0 if status == 200 else 1


# ---------- argparse wiring ----------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="videotranscript",
        description="LearnFlux client for agents.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_format(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--format",
            choices=("markdown", "json"),
            default="markdown",
            help="输出格式，默认 markdown。JSON 适合程序消费。",
        )

    # doctor
    sp = sub.add_parser("doctor", help="验证配置、连通性和鉴权（不会显示 token）")
    add_format(sp)
    sp.set_defaults(func=cmd_doctor)

    # submit
    sp = sub.add_parser("submit", help="提交转录任务")
    sp.add_argument("url", help="视频/播客 URL（YouTube/B站/抖音/小红书/小宇宙等）")
    sp.add_argument("--speaker", action="store_true", help="启用说话人识别（用 FunASR 引擎）")
    sp.add_argument("--webhook", help="企业微信 webhook URL（完成后推送）")
    sp.add_argument("--feishu-webhook", help="飞书 webhook URL（完成后推送）")
    sp.add_argument("--download-url", help="直链下载 URL，绕过平台解析")
    sp.add_argument("--title", help="覆盖自动解析的标题（最多 200 字）")
    sp.add_argument("--author", help="覆盖自动解析的作者（最多 200 字）")
    sp.add_argument("--description", help="覆盖自动解析的简介（最多 2000 字）")
    add_format(sp)
    sp.set_defaults(func=cmd_submit)

    # status
    sp = sub.add_parser("status", help="查询任务状态")
    sp.add_argument("task_id")
    add_format(sp)
    sp.set_defaults(func=cmd_status)

    # result
    sp = sub.add_parser("result", help="拉取已完成任务的文字结果")
    sp.add_argument("view_token")
    sp.add_argument(
        "--type",
        choices=RESULT_TYPES,
        default="summary",
        help="结果类型：summary(总结,默认) / calibrated(校对后全文) / transcript(原始转录)",
    )
    add_format(sp)
    sp.set_defaults(func=cmd_result)

    # history
    sp = sub.add_parser("history", help="查询历史任务")
    sp.add_argument("--platform", help="平台过滤（youtube/bilibili/...）")
    sp.add_argument("--author", help="作者/频道过滤（可多值，用逗号分隔）")
    sp.add_argument("--status", help="状态过滤（success/failed/processing）")
    sp.add_argument("--webhook", help="webhook URL 过滤")
    sp.add_argument("--q", help="关键词搜索（标题/作者/内容）")
    sp.add_argument("--start", help="起始日期 YYYY-MM-DD")
    sp.add_argument("--end", help="结束日期 YYYY-MM-DD")
    sp.add_argument("--limit", type=int, default=20, help="每页条数（默认 20，上限 10000）")
    sp.add_argument("--offset", type=int, default=0, help="偏移（分页用）")
    add_format(sp)
    sp.set_defaults(func=cmd_history)

    # filter-options
    sp = sub.add_parser("filter-options", help="获取可用的过滤选项（平台/作者/webhook 列表）")
    add_format(sp)
    sp.set_defaults(func=cmd_filter_options)

    # profile
    sp = sub.add_parser("profile", help="查询当前 token 对应的用户信息")
    add_format(sp)
    sp.set_defaults(func=cmd_profile)

    # health
    sp = sub.add_parser("health", help="服务健康检查（无需 token）")
    add_format(sp)
    sp.set_defaults(func=cmd_health)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        return 3
    except TransportError as e:
        print(f"[transport] {e}", file=sys.stderr)
        return 2
    except BusinessError as e:
        print(f"[business] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[interrupted]", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
