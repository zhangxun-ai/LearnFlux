"""Read full Feishu documents through the locally authorized official CLI."""

from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit


class FeishuDocumentError(ValueError):
    """A safe, actionable acquisition error without credentials or CLI output."""


@dataclass(frozen=True)
class FeishuURL:
    url: str
    media_id: str


@dataclass(frozen=True)
class FeishuDocument:
    url: str
    media_id: str
    title: str
    text: str
    warnings: tuple[str, ...]
    snapshot_path: str


def parse_feishu_url(value: str) -> FeishuURL | None:
    """Accept only native Wiki/Docx URLs on Feishu or Lark tenant hosts."""
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        trusted = any(host == domain or host.endswith('.' + domain)
                      for domain in ("feishu.cn", "larksuite.com"))
        if (not trusted or parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            return None
        match = re.fullmatch(r"/(wiki|docx)/([A-Za-z0-9_-]{10,128})/?", parsed.path)
        if not match:
            return None
        # Query/share anchors do not define a new document or a partial read.
        canonical = urlunsplit(("https", host, '/' + '/'.join(match.groups()), '', ''))
        return FeishuURL(canonical, hashlib.sha256(canonical.encode()).hexdigest())
    except (ValueError, AttributeError):
        return None


def require_feishu_access(settings: dict, task: dict) -> None:
    """A local CLI identity must never become every API user's document access."""
    if settings.get("enabled") is not True:
        raise FeishuDocumentError("飞书文档读取未启用，请在本机配置中启用 feishu_documents")
    owner = settings.get("owner_user_id")
    if not owner or task.get("owner_user_id") != owner:
        raise FeishuDocumentError("当前任务身份未获准使用本机飞书账号读取文档")


def _reading_text(content: str) -> tuple[str, str, tuple[str, ...]]:
    """Keep Markdown text and image references; disclose unexpanded visuals."""
    title_match = re.match(r"\s*<title(?:\s[^>]*)?>(.*?)</title>\s*", content, re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", title_match[1])).strip() if title_match else "飞书文档"
    body = content[title_match.end():] if title_match else content
    counts = {"图片": 0, "画板": 0, "嵌入内容": 0}
    lines = []
    fence = None
    for line in body.splitlines():
        marker = re.match(r"\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            lines.append(line)
            continue
        if fence is not None:
            lines.append(line)
            continue
        counts["图片"] += len(re.findall(r"!\[[^\]]*\]\(", line)) + len(re.findall(r"<img\b", line))
        for tag, label in (("whiteboard", "画板"), ("sheet", "嵌入内容"),
                           ("bitable", "嵌入内容"), ("synced_reference", "嵌入内容")):
            pattern = rf"<{tag}\b[^>]*(?:/>|>.*?</{tag}>)"
            line, count = re.subn(pattern, f"[飞书{label}：请在原文中查看]", line)
            counts[label] += count
        # Layout containers wrap Markdown, not text to discard or execute.
        line = re.sub(r"</?(?:grid|column|callout)\b[^>]*>", "\n", line)
        lines.append(line)
    text = '\n'.join(lines).strip()
    readable = re.sub(r"\[飞书(?:画板|嵌入内容)：请在原文中查看\]", "", text)
    if not readable or not re.sub(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>|\s|[#>*_-]", "", readable):
        raise FeishuDocumentError("飞书文档没有可读取的正文，请检查文档内容和访问权限")
    warnings = tuple(f"包含 {count} 个{label}，已保留引用，尚未识别其中的视觉内容"
                     for label, count in counts.items() if count)
    if warnings:
        text = '> 读取范围：' + '；'.join(warnings) + '。AI 解读仅依据可读取的文字。\n\n' + text
    return title or "飞书文档", text, warnings


def fetch_feishu_document(url: str, *, settings: dict, snapshot_dir: Path) -> FeishuDocument:
    """Read the whole source, preserve its response, and return text for learning."""
    source = parse_feishu_url(url)
    if source is None:
        raise FeishuDocumentError("不是受支持的飞书 Wiki 或 Docx 文档链接")
    executable = shutil.which(os.path.expanduser(settings.get("cli_path") or "lark-cli"))
    if not executable:
        raise FeishuDocumentError("未找到飞书 CLI，请配置 feishu_documents.cli_path 并完成本机登录")
    env = {**os.environ, "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"}
    try:
        result = subprocess.run(
            [executable, "docs", "+fetch", "--doc", source.url, "--as", "user",
             "--scope", "full", "--doc-format", "markdown"],
            capture_output=True, text=True, env=env,
            timeout=max(5, min(120, int(settings.get("timeout_seconds", 60)))), check=False,
        )
    except subprocess.TimeoutExpired:
        raise FeishuDocumentError("读取飞书文档超时，请检查网络后重试") from None
    except OSError:
        raise FeishuDocumentError("无法启动飞书 CLI，请检查本机安装与执行权限") from None
    if result.returncode:
        raise FeishuDocumentError("飞书文档读取失败，请确认本机飞书 CLI 已登录且该账号有文档读取权限")
    try:
        payload = json.loads(result.stdout)
        document = payload["data"]["document"]
        content = document["content"]
        if payload.get("ok") is not True or not isinstance(content, str):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise FeishuDocumentError("飞书 CLI 未返回有效文档正文，请检查安装版本后重试") from None
    if re.search(r"<(?:fragment|excerpt)\b", content):
        raise FeishuDocumentError("飞书仅返回了文档片段，已停止解析以避免遗漏正文")
    # Keep the complete source response, including reference_map and diagnostics.
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode()
    folder = Path(snapshot_dir) / source.media_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot = folder / (hashlib.sha256(raw).hexdigest() + '.json')
    try:
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
    title, text, warnings = _reading_text(content)
    if document.get("tips"):
        warnings += ("飞书返回了读取提示；原始提示已随源文档快照保存",)
        text = "> 读取提示：飞书返回了内容降级或依赖提示，请对照原文核实。\n\n" + text
    return FeishuDocument(source.url, source.media_id, title, text, warnings, str(snapshot))
