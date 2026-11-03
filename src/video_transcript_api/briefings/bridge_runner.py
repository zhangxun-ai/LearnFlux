"""Run with the vault's Python to reuse its current WeChat scope validator.

Only fixed report artifacts are returned. No archive DB queries, network calls,
generation, source refresh, or logs containing report bodies are performed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

AI_BUNDLE = re.compile(r"\d{4}-\d{2}-\d{2}-(?:daily|sample)-[0-9-]+-[0-9a-f]{6}")


def edition_date(kind: str, bundle: str) -> str:
    """Legacy WeChat IDs name the content day; AI IDs name the issue day.

    Never use the wall clock or rebuild timestamp to date a historical issue.
    """
    day = date.fromisoformat(bundle[:10])
    return (day + timedelta(days=1) if kind == "wechat" else day).isoformat()


def issue_metadata(kind: str, bundle: str, manifest: dict) -> dict:
    issue = edition_date(kind, bundle)
    if manifest.get("edition_date", issue) != issue:
        raise ValueError("Edition date conflicts with report identity")
    content_day = bundle[:10] if kind == "wechat" else (
        (date.fromisoformat(issue) - timedelta(days=1)).isoformat() if "-daily-" in bundle else None
    )
    match = re.fullmatch(r"\d{4}-\d{2}-\d{2}-(?:live|daily|sample)-(\d{8}-\d{6})-[0-9a-f]{6}", bundle)
    generated = datetime.strptime(match[1], "%Y%m%d-%H%M%S").replace(tzinfo=timezone(timedelta(hours=8))).isoformat() if match else None
    return {"date": issue, "edition_date": issue, "content_date": content_day,
            "generated_at": manifest.get("generated_at", generated)}


def safe_path(root: Path, name: str) -> Path:
    parts = Path(name)
    if parts.is_absolute() or not parts.parts or any(x in ("..", ".") for x in parts.parts):
        raise ValueError("Invalid report path")
    current = root
    for part in parts.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink not allowed")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path outside report root")
    return current


class ReportBridge:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def wechat_store(self):
        # Import the existing policy authority, not a copied fingerprint rule.
        tools = self.root / "tools"
        if tools.is_symlink():
            raise ValueError("Invalid tools directory")
        sys.path.insert(0, str(tools))
        from daily_publish import DailyStore
        return DailyStore(base=self.root)

    def ai_manifest(self, bundle: str):
        if not AI_BUNDLE.fullmatch(bundle):
            raise ValueError("Invalid report identity")
        directory = safe_path(self.root, "exports/ai-guide-reports/" + bundle)
        manifest = json.loads(safe_path(directory, "manifest.json").read_text())
        if manifest.get("date") != bundle[:10] or not isinstance(manifest.get("files"), dict):
            raise ValueError("Invalid manifest")
        return directory, manifest

    def catalog(self) -> dict:
        items, warnings = [], []
        for kind in ("ai", "wechat"):
            try:
                if kind == "wechat":
                    store = self.wechat_store()
                    # Fail visibly if the current policy cannot be validated.
                    store.scope_loader(store.base)
                    rows = store.history()
                    latest = store.latest()
                else:
                    directory = safe_path(self.root, "exports/ai-guide-reports")
                    rows = []
                    for child in directory.iterdir():
                        if child.is_symlink() or not AI_BUNDLE.fullmatch(child.name):
                            continue
                        try:
                            _, manifest = self.ai_manifest(child.name)
                            # Listing does not expose the body; still reject a
                            # broken report instead of advertising it as ready.
                            self.read("ai", child.name, "report.md")
                            rows.append({"date": manifest["date"], "bundle": child.name})
                        except (OSError, ValueError, KeyError):
                            continue
                    latest = json.loads(safe_path(self.root, "state/latest-ai-guide-report.json").read_text())["bundle"]
                by_date = {}
                for row in sorted(rows, key=lambda x: (x["date"], "-sample-" not in x["bundle"], x["bundle"]), reverse=True):
                    by_date.setdefault(row["date"], row)
                for row in by_date.values():
                    _, manifest = store.manifest(row["bundle"]) if kind == "wechat" else self.ai_manifest(row["bundle"])
                    items.append({**row, **issue_metadata(kind, row["bundle"], manifest), "kind": kind, "title": "AI 导游日报" if kind == "ai" else "微信日报", "is_latest": row["bundle"] == latest})
            except (OSError, ValueError, KeyError, ImportError):
                warnings.append({"kind": kind, "message": "日报暂不可读取，请检查来源目录与当前读取范围。"})
        return {"items": items, "warnings": warnings}

    def read(self, kind: str, bundle: str, name: str) -> bytes:
        allowed = name in {"report.html", "report.md"}
        if kind == "wechat":
            allowed = allowed or name == "sources.html" or bool(re.fullmatch(r"media/[A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|gif|webp)", name))
        if not allowed:
            raise ValueError("File is not a report artifact")
        if kind == "wechat":
            store = self.wechat_store()
            directory, manifest = store.manifest(bundle)
            target = safe_path(directory, name)
            if target.stat().st_size > 20_000_000:
                raise ValueError("Report artifact too large")
            body = store.read(bundle, name)
            store.manifest(bundle)  # recheck scope after the read
            return body
        if kind != "ai":
            raise ValueError("Unknown report kind")
        directory, manifest = self.ai_manifest(bundle)
        if name not in manifest["files"]:
            raise ValueError("Missing artifact")
        target = safe_path(directory, name)
        if target.stat().st_size > 20_000_000:
            raise ValueError("Report artifact too large")
        body = target.read_bytes()
        if hashlib.sha256(body).hexdigest() != manifest["files"][name]:
            raise ValueError("Report checksum mismatch")
        return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("action", choices=("list", "read"))
    parser.add_argument("kind", nargs="?")
    parser.add_argument("bundle", nargs="?")
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    try:
        bridge = ReportBridge(args.root)
        if args.action == "list":
            sys.stdout.write(json.dumps(bridge.catalog(), ensure_ascii=False))
        else:
            sys.stdout.buffer.write(bridge.read(args.kind, args.bundle, args.name))
        return 0
    except Exception:
        # Never emit scope identities, source paths, private content or traces.
        sys.stderr.write("Report unavailable or access validation failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
