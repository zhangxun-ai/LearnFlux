"""Read published reports and export only the user's explicitly chosen version."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..exports.feishu import ArchiveWorker, summary_xml
from ..obsidian.paths import ensure_vault_directory_tree, resolve_vault_path
from .bridge_runner import edition_date

PROJECT = Path(__file__).resolve().parents[3]
KINDS = {"ai": "AI 导游日报", "wechat": "微信日报"}
BUNDLE = re.compile(r"\d{4}-\d{2}-\d{2}-(?:live|daily|sample)-(\d{8}-\d{6})-[0-9a-f]{6}")


class BriefingError(ValueError):
    pass


def load_settings() -> dict:
    path = Path(os.environ.get("LEARNFLUX_BRIEFINGS_CONFIG", str(PROJECT / "data/briefings/integration.json"))).expanduser()
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text())
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def export_markdown(source: str) -> str:
    """Keep provenance labels, but do not export broken private local URLs."""
    def link(match):
        label, url = match.group(1), match.group(2)
        parsed = urlsplit(url)
        if parsed.scheme in {"https", "http"} and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return match.group(0)
        return label + "（原文仅在本机日报中查看）"
    return re.sub(r"!?\[([^\]\n]+)\]\(([^)]+)\)", link, source)


def reading_html(body: bytes, kind: str) -> bytes:
    """Keep report layout, with active code removed and local links preserved."""
    soup = BeautifulSoup(body.decode("utf-8"), "html.parser")
    for node in list(soup.find_all(["script", "iframe", "object", "embed", "base", "form"])):
        node.decompose()
    for node in soup.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith("on") or attr in {"srcdoc", "srcset"}:
                del node.attrs[attr]
        for attr in ("href", "src"):
            url = node.get(attr)
            if not url: continue
            parsed = urlsplit(url)
            if parsed.scheme and parsed.scheme not in {"http", "https"}:
                del node.attrs[attr]
            elif attr == "src" and (parsed.scheme or parsed.netloc or not url.startswith("media/")):
                del node.attrs[attr]
            elif attr == "href" and (parsed.hostname in {"127.0.0.1", "localhost", "::1"} or url == "/history"):
                switch = "ai" if parsed.port == 52635 else kind
                node[attr] = "/briefings?kind=" + switch
                node["target"] = "_top"
            if node.name == "a": node["rel"] = "noopener noreferrer"
    # Keep one copy of coverage/limitations when removing standalone navigation.
    main = soup.select_one("main#report")
    if main:
        evidence = soup.select_one(".sidebar .system-status")
        if evidence:
            main.append(evidence.extract())
        if kind == "wechat":
            nav = soup.new_tag("nav", attrs={"class": "report-sections", "aria-label": "本期内容"})
            for anchor, label in (("highlights", "今日概览"), ("groups", "群聊"), ("private", "私聊")):
                if main.find(id=anchor):
                    link = soup.new_tag("a", href="#" + anchor)
                    link.string = label
                    nav.append(link)
            main.insert(0, nav)
    # The workbench owns navigation and actions; report facts and sources stay intact.
    for node in soup.select(".sidebar, .topbar, .mobile-utilities, #feedback, .skip"):
        node.decompose()
    style = soup.new_tag("style")
    style.string = Path(__file__).with_name("reading.css").read_text()
    (soup.head or soup).append(style)
    return str(soup).encode()


class BriefingService:
    def __init__(self, settings: dict, *, obsidian: dict | None = None, feishu: dict | None = None):
        self.settings = settings
        self.obsidian = obsidian or {}
        self.feishu = feishu
        self.state = Path(settings.get("state_dir") or PROJECT / "data/briefings")

    def _bridge(self, *arguments: str) -> bytes:
        root = Path(self.settings["source_root"]).expanduser()
        python = root / "runtime/bin/python"
        runner = Path(__file__).with_name("bridge_runner.py")
        try:
            result = subprocess.run([str(python), "-I", str(runner), "--root", str(root), *arguments], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise BriefingError("日报来源暂不可用，请稍后重试。") from None
        if result.returncode:
            raise BriefingError("日报不可读取：文件校验或当前会话范围检查未通过。")
        return result.stdout

    def destinations(self) -> dict:
        return {
            "obsidian": {"available": bool(self.obsidian.get("enabled") and self.obsidian.get("vault_path") and Path(self.obsidian["vault_path"]).expanduser().is_dir()), "label": "现有 Obsidian 笔记库 · 日报"},
            "feishu": {"available": bool(self.feishu), "label": "工作台现有飞书归档位置"},
        }

    def catalog(self) -> dict:
        return {**json.loads(self._bridge("list")), "destinations": self.destinations()}

    def read(self, kind: str, bundle: str, name: str) -> bytes:
        if kind not in KINDS or not BUNDLE.fullmatch(bundle):
            raise BriefingError("日报编号无效。")
        if (kind == "wechat") != ("-live-" in bundle):
            raise BriefingError("日报类型不匹配。")
        body = self._bridge("read", kind, bundle, name)
        if kind == "wechat" and name == "report.md":
            source = body.decode()
            old_heading = "# 微信日报 · " + bundle[:10]
            if source.startswith(old_heading + "\n"):
                source = "# 微信日报 · " + edition_date(kind, bundle) + "\n\n内容日期：" + bundle[:10] + source[len(old_heading):]
            body = source.encode()
        return body

    def preview(self, kind: str, bundle: str, destination: str) -> dict:
        targets = self.destinations()
        if destination not in targets or not targets[destination]["available"]:
            raise BriefingError("该同步目标尚未配置。")
        raw = self.read(kind, bundle, "report.md")
        return {"title": f"{KINDS[kind]} · {edition_date(kind, bundle)}", "markdown": export_markdown(raw.decode()), "content_sha256": hashlib.sha256(raw).hexdigest(), "destination_label": targets[destination]["label"], "private_notice": "包含私人聊天摘要，不附带完整原文和图片。" if kind == "wechat" else "保存这份日报的文字与来源链接。"}

    @contextmanager
    def _lock(self):
        import fcntl
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.state / "sync.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BriefingError("已有日报正在同步，请稍后查看结果。") from None
            try: yield
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def sync(self, kind: str, bundle: str, destination: str, digest: str, *, confirm: bool, confirm_private: bool) -> dict:
        if not confirm or (kind == "wechat" and not confirm_private):
            raise BriefingError("请先预览并确认这份日报的同步范围。")
        with self._lock():
            preview = self.preview(kind, bundle, destination)
            if preview["content_sha256"] != digest:
                raise BriefingError("日报内容已变化，请重新预览后同步。")
            if destination == "obsidian": return self._obsidian_sync(kind, bundle, preview)
            if destination == "feishu": return self._feishu_sync(kind, bundle, preview)
            raise BriefingError("未知同步目标。")

    def _obsidian_sync(self, kind: str, bundle: str, preview: dict) -> dict:
        vault = Path(self.obsidian["vault_path"]).expanduser()
        # Immutable source revision: never overwrite a user-edited note.
        directory = "日报/" + KINDS[kind]
        ensure_vault_directory_tree(vault, directory)
        relative = directory + "/" + edition_date(kind, bundle) + "-" + preview["content_sha256"][:12] + ".md"
        target = resolve_vault_path(vault, relative)
        content = preview["markdown"].encode()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".briefing-", dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            # Link a complete file atomically; an existing note always wins.
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != content:
                return {"status": "conflict", "label": "笔记已有修改，已保留原文，未覆盖。"}
            return {"status": "unchanged", "label": "这份日报已在 Obsidian 中，无需重复保存。"}
        finally:
            if temporary is not None and not temporary.is_symlink() and temporary.is_file() and temporary.parent == target.parent:
                temporary.unlink()  # only this call's disposable staging file
        if target.read_bytes() != content:
            raise BriefingError("笔记写入校验未通过，请检查本机笔记库。")
        return {"status": "done", "label": "已保存到 Obsidian 的“日报”目录。"}

    def _feishu_sync(self, kind: str, bundle: str, preview: dict) -> dict:
        config = {**self.feishu, "state_db": str(self.state / "feishu.db")}
        stable = "briefing:" + kind + ":" + bundle[:10]
        class Source:
            def tasks(self):
                yield {"task_id": bundle, "view_token": stable, "updated_at": preview["content_sha256"]}
            def document(self, _task):
                return preview["title"], "<title>" + html.escape(preview["title"]) + "</title>" + summary_xml(preview["markdown"])
        worker = ArchiveWorker(config, source=Source())
        try:
            key = config["parent_node_token"] + ":" + stable
            previous = worker.db.execute("SELECT * FROM exports WHERE source_key=?", (key,)).fetchone()
            old_version = BUNDLE.fullmatch(previous["task_id"] or "") if previous else None
            new_version = BUNDLE.fullmatch(bundle)
            if previous and (not old_version or not new_version or old_version[1] > new_version[1]):
                return {"status": "conflict", "label": "飞书已有更新的日报版本，未用旧版覆盖。"}
            # Preserve unknown-create and conflict states; only the existing
            # export worker may reconcile or update a verified remote document.
            worker.run_once()
            row = worker.db.execute("SELECT * FROM exports WHERE source_key=?", (key,)).fetchone()
            if row and row["status"] == "done":
                expected_revision = json.dumps([bundle, preview["content_sha256"], None], separators=(",", ":"))
                if row["source_revision"] != expected_revision or row["content"] != Source().document({})[1]:
                    return {"status": "pending", "label": "已核对先前版本，本次预览的新版尚未同步；请重新预览后继续。"}
                worker.db.execute("UPDATE exports SET task_id=? WHERE source_key=?", (bundle, key)); worker.db.commit()
                url = row["document_url"] or ""
                result = {"status": "done", "label": "已同步到飞书并核对正文。"}
                if urlsplit(url).scheme == "https": result["url"] = url
                return result
            state = row["status"] if row else "failed"
            return {"status": state, "label": "同步尚未确认完成，已保留记录；再次操作会核对已有文档，不盲目新建。"}
        finally:
            worker.db.close()
