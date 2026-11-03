"""Durable, independent export of completed local tasks to Feishu Wiki.

Uses the existing loopback APIs and the user's authenticated lark-cli. No
management secrets, view tokens, or local file paths are written to Feishu.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from bs4 import BeautifulSoup, NavigableString
import markdown


class FeishuRejected(RuntimeError):
    """A confirmed authorization rejection that did not create a document."""


_EXPORT_HEADER = re.compile(
    r"\A---\r?\nTitle: [\s\S]*?\r?\nPlatform: [^\n]*\r?\nType: [^\n]*\r?\n"
    r"(?:Source: [^\n]*\r?\n)?Export-Date: \d{4}-\d{2}-\d{2}\r?\n---\r?\n"
)
_EXPORT_FIELDS = re.compile(
    r"\ATitle: [\s\S]*?\nPlatform: [^\n]*\nType: [^\n]*\n"
    r"(?:Source: [^\n]*\n)?Export-Date: \d{4}-\d{2}-\d{2}\s*\Z"
)


def _without_export_header(source: str) -> str:
    """Remove only the API-generated transport header, retaining source dates."""
    return _EXPORT_HEADER.sub("", source, count=1)


def _version_text(xml: str) -> str:
    """Ignore old transport headers for revision detection, never readback checks.

    Previous archives included the raw-export header twice. Its Export-Date is
    today's date, not a content revision. Do not mark unchanged old documents
    as conflicts merely because the calendar day or export layout changed.
    """
    soup = BeautifulSoup(xml, "html.parser")
    for node in list(soup.find_all(["p", "h2", "h3", "h4", "h5", "h6"])):
        raw = node.get_text("\n")
        if _EXPORT_FIELDS.fullmatch(raw):
            node.decompose()
        elif _EXPORT_HEADER.match(raw):
            node.clear()
            node.append(_without_export_header(raw))
    text = normalized_text(str(soup))
    # Old long titles can split the generated header across several Markdown
    # blocks. Restrict this legacy comparison to the complete generated field
    # sequence; the full readback comparator above remains unchanged.
    return re.sub(r"Title:.*?Platform:.*?Type:.*?Export-Date:\d{4}-\d{2}-\d{2}", "", text)


def normalized_text(xml: str) -> str:
    """Compare complete text and link targets across native link conversion.

    Feishu converts literal ``[label](url)`` in transcript paragraphs into
    native anchors. Retain the target when comparing those representations;
    otherwise valid links look like missing text, or a changed target is missed.
    """
    soup = BeautifulSoup(xml, "html.parser")
    for anchor in soup.find_all("a"):
        href = anchor.get("href") or ""
        if href and anchor.get_text() != href:
            anchor.append("(" + href + ")")
    text = re.sub(r"\[([^\[\]\n]+)\]\((https?://[^\s)]+)\)", r"\1(\2)", soup.get_text())
    return re.sub(r"\s+", "", text)


def remote_digest(xml: str) -> str:
    """Remember remote rich content, including manual formatting and resources."""
    soup = BeautifulSoup(xml, "html.parser")
    for node in soup.find_all():
        for attribute in ("id", "block-id", "block_id"):
            node.attrs.pop(attribute, None)
    return hashlib.sha256(str(soup).encode("utf-8")).hexdigest()


def summary_xml(source: str) -> str:
    """Convert stored Markdown without allowing uploads or arbitrary XML."""
    soup = BeautifulSoup(markdown.markdown(source, extensions=["tables", "fenced_code"]), "html.parser")

    heading_stack: list[int] = []

    def render(node) -> str:
        if isinstance(node, NavigableString):
            return html.escape(str(node))
        name = node.name
        inner = "".join(render(child) for child in node.children)
        if name == "img":
            # Preserve the description without fetching arbitrary remote media.
            return html.escape(node.get("alt") or "图片")
        if name in {"script", "style"}:
            return html.escape(node.get_text())
        if name == "a":
            href = node.get("href", "")
            if urlsplit(href).scheme in {"https", "http"}:
                return f'<a href="{html.escape(href, quote=True)}">{inner}</a>'
            return inner
        if re.fullmatch(r"h[1-6]", name or ""):
            source_level = int(name[1])
            while heading_stack and heading_stack[-1] >= source_level:
                heading_stack.pop()
            heading_level = min(2 + len(heading_stack), 6)
            heading_stack.append(source_level)
            return f"<h{heading_level}>{inner}</h{heading_level}>"
        if name == "pre":
            code = node.find("code")
            language = next((value[9:] for value in (code.get("class", []) if code else [])
                             if value.startswith("language-")), "text")
            language = language if re.fullmatch(r"[\w+-]{1,30}", language) else "text"
            return f'<pre lang="{language}"><code>{html.escape(node.get_text())}</code></pre>'
        name = {"strong": "b", "code": "span"}.get(name, name)
        if name in {"br", "hr"}:
            return f"<{name}/>"
        if name in {"td", "th"}:
            return f"<{name}><p>{inner}</p></{name}>"
        if name in {"p", "b", "em", "span", "blockquote", "ul", "ol", "li",
                    "table", "thead", "tbody", "tr"}:
            return f"<{name}>{inner}</{name}>"
        return inner

    return "".join(render(node) for node in soup.children)


def build_document(task: dict, analysis: str, transcript: str, *, calibrated: bool) -> tuple[str, str]:
    """Build a mobile-readable document containing complete source content."""
    if not analysis.strip() or not transcript.strip():
        raise ValueError("Result is incomplete; export deferred")
    original_title = str(task.get("title") or "未命名学习内容").strip()
    title = original_title.split(" 本视频", 1)[0].splitlines()[0]
    if len(title) > 90:
        title = title[:89] + "…"
    raw_date = str(task.get("created_at") or "")
    date = parse_time(raw_date).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    title = f"{date} · {title}"
    source_url = str(task.get("url") or "")
    metadata = [f"作者：{task.get('author') or '未提供'}", f"来源：{task.get('platform') or '未提供'}", f"收集日期：{date}"]
    body = f"<title>{html.escape(title)}</title>"
    body += "<p>" + "<br/>".join(html.escape(line) for line in metadata) + "</p>"
    if urlsplit(source_url).scheme in {"http", "https"}:
        body += f'<p>原始链接：<a href="{html.escape(source_url, quote=True)}">{html.escape(source_url)}</a></p>'
    body += "<p>以下解读由 AI 生成，重要事实请对照原始来源核实。</p>"
    body += "<h1>AI 解读</h1>" + summary_xml(analysis)
    label = "完整逐字稿 / 正文（已校对）" if calibrated else "完整逐字稿 / 正文（原始转录）"
    body += f"<h1>{label}</h1>"
    for paragraph in re.split(r"\n\s*\n", transcript.strip()):
        body += "<p>" + html.escape(paragraph).replace("\n", "<br/>") + "</p>"
    return title, body


def parse_time(value: str) -> dt.datetime:
    """Interpret the API's legacy naive timestamps as UTC."""
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed


class LocalResults:
    """Read the existing task APIs using one configured local API credential."""

    def __init__(self, config: dict):
        self.config = config
        self.base = config.get("api_base", "http://127.0.0.1:8000").rstrip("/")
        parsed = urlsplit(self.base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Archive source must be a loopback HTTP API")
        self.opener = build_opener(ProxyHandler({}))

    def read(self, path: str) -> str:
        users = json.loads(Path(self.config["users_file"]).read_text())["users"]
        token = next((key for key, user in users.items()
                      if user.get("name") == self.config["api_user_name"] and user.get("enabled", True)), None)
        if not token:
            raise ValueError("Configured local API user is unavailable")
        request = Request(self.base + path, headers={"Authorization": "Bearer " + token,
                                                    "User-Agent": "LearnFlux-FeishuArchive/1.0"})
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError("Local result is not ready")
                return response.read().decode("utf-8")
        except HTTPError as error:
            # Never expose the private view-token URL in logs.
            raise ValueError(f"Local API returned HTTP {error.code}") from None

    def tasks(self):
        cutoff = parse_time(self.config["since"])
        samples = set(self.config.get("include_task_ids", []))
        remaining_samples = set(samples)
        offset = 0
        while True:
            data = json.loads(self.read(f"/api/tasks?limit=200&offset={offset}"))["data"]
            rows = data["items"]
            for task in rows:
                remaining_samples.discard(task["task_id"])
                if task.get("status") == "success" and task.get("view_token") and (
                    task["task_id"] in samples or parse_time(task["created_at"]) >= cutoff
                ):
                    yield task
            if not data.get("has_more"):
                break
            if rows and not remaining_samples and parse_time(rows[-1]["created_at"]) < cutoff:
                break
            offset += len(rows)
            if not rows:
                break

    def document(self, task: dict) -> tuple[str, str]:
        view = quote(task["view_token"], safe="")
        analysis = self.read(f"/view/{view}?raw=summary")
        calibrated = True
        try:
            transcript = self.read(f"/view/{view}?raw=calibrated")
        except ValueError:
            calibrated = False
            transcript = self.read(f"/view/{view}?raw=transcript")
        return build_document(task, _without_export_header(analysis),
                              _without_export_header(transcript), calibrated=calibrated)


class FeishuCLI:
    """Call lark-cli without a shell, tokens, or credential copies."""

    def __init__(self, executable: str):
        self.executable = executable

    def call(self, *args: str, content: str | None = None) -> dict:
        env = {**os.environ, "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"}
        try:
            result = subprocess.run([self.executable, *args, "--as", "user"],
                                    input=content, capture_output=True, text=True,
                                    timeout=240, env=env, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Feishu operation timed out; reconcile before any new write") from None
        if result.returncode:
            # Error bodies may contain auth URLs or private source text.
            try:
                error = json.loads(result.stderr).get("error", {})
            except (ValueError, AttributeError):
                error = {}
            if error.get("type") == "authorization":
                raise FeishuRejected("Feishu authorization rejected; retry after authorization is restored")
            raise RuntimeError(f"Feishu CLI exited with status {result.returncode}")
        payload = json.loads(result.stdout)
        if payload.get("ok") is not True:
            raise RuntimeError("Feishu did not confirm the operation")
        return payload["data"]

    def create(self, parent: str, xml: str) -> dict:
        return self.call("docs", "+create", "--parent-token", parent,
                         "--doc-format", "xml", "--content", "-", content=xml)

    def fetch(self, document_id: str) -> str:
        return self.fetch_document(document_id)["content"]

    def fetch_document(self, document_id: str) -> dict:
        return self.call("docs", "+fetch", "--doc", document_id)["document"]

    def update(self, document_id: str, xml: str, revision_id: int) -> dict:
        """Replace only a verified, unchanged generated document revision."""
        return self.call("docs", "+update", "--doc", document_id, "--command", "overwrite",
                         "--revision-id", str(revision_id), "--doc-format", "xml",
                         "--content", "-", content=xml)


class ArchiveWorker:
    """Keep export state separate from transcription, with durable deduplication."""

    def __init__(self, config: dict, *, source=None, cli=None):
        self.config = config
        self.source = source or LocalResults(config)
        self.cli = cli or FeishuCLI(config["cli_path"])
        path = Path(config["state_db"])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS exports (
            source_key TEXT PRIMARY KEY, task_id TEXT, title TEXT, content TEXT,
            status TEXT NOT NULL, document_id TEXT, document_url TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, next_retry REAL NOT NULL DEFAULT 0,
            last_error TEXT, updated_at REAL NOT NULL)""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(exports)")}
        for column in ("source_revision", "remote_digest", "pending_content", "pending_revision"):
            if column not in columns:
                self.db.execute(f"ALTER TABLE exports ADD COLUMN {column} TEXT")
        if "written_revision" not in columns:
            self.db.execute("ALTER TABLE exports ADD COLUMN written_revision INTEGER")
        self.db.commit()

    def _row(self, key: str):
        return self.db.execute("SELECT * FROM exports WHERE source_key=?", (key,)).fetchone()

    def _fetch_document(self, document_id: str) -> dict:
        if hasattr(self.cli, "fetch_document"):
            return self.cli.fetch_document(document_id)
        return {"content": self.cli.fetch(document_id), "revision_id": None}

    def _finish(self, key: str, content: str, revision: str, remote: str, *, trusted: bool):
        self.save(key, status="done", content=content, source_revision=revision,
                  remote_digest=remote_digest(remote) if trusted else None, pending_content=None,
                  pending_revision=None, last_error=None, next_retry=0)

    def _update_document(self, key: str, row) -> bool:
        """Reconcile interrupted updates and protect remote edits with a revision."""
        document = self._fetch_document(row["document_id"])
        remote, desired = document["content"], row["pending_content"]
        if normalized_text(remote) == normalized_text(desired):
            # A timed-out write may have succeeded, followed by human edits.
            # Text proves delivery, not ownership of the current rich revision.
            trusted = (row["written_revision"] is not None
                       and row["written_revision"] == document.get("revision_id"))
            self._finish(key, desired, row["pending_revision"], remote, trusted=trusted)
            return True
        revision_id = document.get("revision_id")
        unchanged = (row["remote_digest"] and remote_digest(remote) == row["remote_digest"]
                     and normalized_text(remote) == normalized_text(row["content"]))
        if not unchanged or not isinstance(revision_id, int) or revision_id < 0:
            self.save(key, status="conflict", last_error="Remote edits or unverified revision; preserved",
                      next_retry=0)
            return False
        self.save(key, status="updating", written_revision=None)
        result = self.cli.update(row["document_id"], desired, revision_id) or {}
        written_revision = (result.get("document") or {}).get("revision_id")
        self.save(key, written_revision=written_revision)
        document = self._fetch_document(row["document_id"])
        remote = document["content"]
        if normalized_text(remote) != normalized_text(desired):
            raise ValueError("Document readback differs from complete source content")
        trusted = written_revision is not None and written_revision == document.get("revision_id")
        self._finish(key, desired, row["pending_revision"], remote, trusted=trusted)
        return True

    def save(self, key: str, **values):
        values["updated_at"] = time.time()
        assignments = ",".join(f"{name}=?" for name in values)
        self.db.execute(f"UPDATE exports SET {assignments} WHERE source_key=?", [*values.values(), key])
        self.db.commit()

    def reconcile(self, row) -> dict | None:
        """Recover a possible remote success without blindly creating a duplicate."""
        # Pagination is explicit; incomplete discovery never permits recreation.
        page = ""
        while True:
            args = ["wiki", "+node-list", "--space-id", self.config["space_id"],
                    "--parent-node-token", self.config["parent_node_token"]]
            if page:
                args += ["--page-token", page]
            data = self.cli.call(*args)
            for node in data.get("nodes", []):
                if node.get("title") == row["title"] and node.get("obj_type") == "docx":
                    if normalized_text(self.cli.fetch(node["obj_token"])) == normalized_text(row["content"]):
                        return {"document_id": node["obj_token"],
                                "url": "https://my.feishu.cn/wiki/" + node["node_token"]}
            if not data.get("has_more"):
                return None
            page = data.get("page_token")
            if not page:
                raise RuntimeError("Incomplete Wiki listing; reconciliation deferred")

    def run_once(self) -> dict:
        exported = 0
        seen = set()
        for task in self.source.tasks():
            # Stable view identity also deduplicates re-submissions using the cache.
            key = self.config["parent_node_token"] + ":" + task["view_token"]
            if key in seen:
                continue
            seen.add(key)
            revision = json.dumps([task.get("task_id"), task.get("updated_at"),
                                   task.get("completed_at")], separators=(",", ":"))
            self.db.execute("INSERT OR IGNORE INTO exports(source_key,task_id,status,updated_at) VALUES(?,?,?,?)",
                            (key, task["task_id"], "pending", time.time()))
            self.db.commit()
            row = self._row(key)
            if row["status"] == "conflict" or row["next_retry"] > time.time():
                continue
            try:
                if row["status"] == "done":
                    if row["source_revision"] == revision:
                        continue
                    _, content = self.source.document(task)
                    if _version_text(content) == _version_text(row["content"]):
                        # Do not adopt legacy rich content as a machine baseline:
                        # matching text cannot rule out earlier manual formatting
                        # or images. A later content change needs manual review.
                        self.save(key, source_revision=revision)
                        continue
                    self.save(key, status="update_pending", pending_content=content,
                              pending_revision=revision, written_revision=None)
                    row = self._row(key)
                if row["status"] in {"update_pending", "updating"}:
                    exported += int(self._update_document(key, row))
                    continue
                if not row["content"]:
                    title, content = self.source.document(task)
                    self.save(key, title=title, content=content, source_revision=revision)
                    row = self._row(key)
                doc_id, url = row["document_id"], row["document_url"]
                if not doc_id:
                    if row["status"] in {"creating", "uncertain"}:
                        document = self.reconcile(row)
                        if document is None:
                            self.save(key, status="uncertain", last_error="Unconfirmed create; manual reconciliation required",
                                      next_retry=time.time() + 3600)
                            continue
                    else:
                        self.save(key, status="creating")
                        try:
                            result = self.cli.create(self.config["parent_node_token"], row["content"])
                            document = result["document"]
                        except FeishuRejected:
                            self.save(key, status="pending")
                            raise
                        except Exception:
                            # A timeout/nonzero exit may follow a successful write.
                            self.save(key, status="uncertain")
                            raise
                    doc_id, url = document["document_id"], document["url"]
                    self.save(key, document_id=doc_id, document_url=url, status="verifying",
                              written_revision=document.get("revision_id"))
                document = self._fetch_document(doc_id)
                remote = document["content"]
                if normalized_text(remote) != normalized_text(row["content"]):
                    raise ValueError("Document readback differs from complete source content")
                written_revision = self._row(key)["written_revision"]
                trusted = written_revision is not None and written_revision == document.get("revision_id")
                self._finish(key, row["content"], row["source_revision"] or revision, remote, trusted=trusted)
                exported += 1
            except Exception as error:
                current = self.db.execute("SELECT * FROM exports WHERE source_key=?", (key,)).fetchone()
                attempts = current["attempts"] + 1
                self.save(key, attempts=attempts, last_error=str(error)[:240],
                          next_retry=time.time() + min(3600, 30 * 2 ** min(attempts, 7)))
        counts = dict(self.db.execute("SELECT status,COUNT(*) FROM exports GROUP BY status").fetchall())
        return {"exported_this_run": exported, "counts": counts}
