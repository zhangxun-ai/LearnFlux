#!/usr/bin/env python3
"""Render real LearnFlux pages with authored, non-private screenshot fixtures.

Run with ``uv run python scripts/readme_demo.py``. This loopback-only server
never imports application configuration, opens a database or calls a provider.
It is a documentation tool, not an application backend.
"""

from __future__ import annotations

import argparse
from collections import Counter
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape
import markdown


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from video_transcript_api.api.assets import get_static_asset_version

WEB = ROOT / "src/web"
STATIC = WEB / "static"
DATE = "2026-11-03"
STAMP = DATE + "T02:00:00+00:00"
sys.path.insert(0, str(ROOT / "scripts"))
from readme_cases import MAIN, COURSE, HISTORY, BOOKS as BOOK_CASES, DIARY, BRIEFINGS, SOURCES as CASE_SOURCES

TITLE = MAIN["title"]
TEXT = MAIN["text"]
SUMMARY = MAIN["summary"]
SUMMARY_HTML = markdown.markdown(SUMMARY, extensions=["tables", "fenced_code"])
RECORDS = [
    {
        **record, "id": f"demo-task-{i}", "task_id": f"demo-task-{i}",
        "view_token": f"demo-note-{i}",
        "status": "success", "created_at": STAMP, "completed_at": STAMP,
        "request_time": STAMP, "request_time_display": DATE + " 10:00",
        "is_marked": i == 0, "duration": 2371 if i == 0 else 360 + i * 60,
        "summary": SUMMARY, "study_available": i == 2,
        "study_url": "/study/demo-note-1" if i == 2 else None,
        "content_type": "video" if i == 0 else "post" if i == 1 else "file", "marked": i == 0,
        "summary_available": True,
    }
    for i, record in enumerate(HISTORY)
]
SOURCES = [
    {
        "id": f"demo-chapter-{i}", "title": chapter["title"],
        "filename": chapter["title"] + ".md", "source_type": "document",
        "task_status": "success", "order_index": i,
        "view_token": f"demo-note-{i}", "elapsed_seconds": 90 + i * 15,
        "duration": 360 + i * 60, "study_available": i == 0,
        "study_url": "/study/demo-note-1" if i == 0 else None,
        "summary": chapter["summary"], "transcript": chapter["text"],
        "transcription_strategy": "local",
    }
    for i, chapter in enumerate(COURSE["chapters"])
]
COLLECTION = {
    "id": "demo-course", "title": COURSE["title"], "creator": COURSE["creator"],
    "collection_type": "document_topic", "status": "completed", "created_at": STAMP,
    "updated_at": STAMP, "sources": SOURCES, "source_count": len(SOURCES),
    "total_sources": len(SOURCES), "completed_sources": len(SOURCES), "success_count": len(SOURCES),
    "summary_markdown": SOURCES[0]["summary"], "summary_status": "success",
    "transcription_strategy": "local", "transcription_concurrency": 1,
}
BOOKS = [
    {"id": f"demo-book-{i}", "title": book["title"], "author": book["author"],
     "format": "markdown", "status": "ready", "created_at": STAMP,
     "updated_at": STAMP, "last_opened_at": STAMP}
    for i, book in enumerate(BOOK_CASES)
]
PLAYER_TITLE = "咖啡店越忙，为什么反而不赚钱？（演示短片）"
PLAYER_LINES = [
    "假设街角新开了两家咖啡店，隔三差五做买一送一。",
    "顾客多了，但杯子、咖啡豆和人工都要花钱，利润不一定增加。",
    "五力模型提醒我们：竞争不只来自隔壁那家店。",
    "便利店咖啡是替代品，供应商涨价、顾客比价，也会挤压利润。",
    "先看清这些压力，再考虑门店靠价格、位置还是产品留住顾客。",
]


def ok(data: object) -> dict:
    return {"code": 200, "message": "ok", "data": data}


def book_detail(index: int) -> dict:
    chapters = [
        {"id": f"part-{i}", "title": chapter["title"], "order_index": i,
         "sanitized_html": f"<h1>{html.escape(chapter['title'])}</h1>" + "".join(
             f"<p>{html.escape(paragraph)}</p>" for paragraph in chapter["text"].split("\n") if paragraph.strip())}
        for i, chapter in enumerate(BOOK_CASES[index]["chapters"])
    ]
    return {"document": BOOKS[index], "chapters": chapters,
            "progress": {"percent": 28, "locator": {"chapter_id": "part-0", "offset": 0}}}


def api_payload(path: str, query: dict) -> object | None:
    """Return only authored fixtures; unknown APIs never reach a real backend."""
    if path == "/api/auth/session":
        return {"authenticated": True, "csrf_token": "demo-only-not-a-credential",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "user": {"user_id": "readme-demo", "name": "演示用户"}}
    if path in {"/api/audit/history", "/api/tasks"}:
        platform = query.get("platform", [""])[0]
        rows = [r for r in RECORDS if not platform or r["platform"] == platform]
        return ok({"items": rows, "total": len(rows), "api_key_masked": "demo-user"})
    if path in {"/api/audit/history/filter-options", "/api/audit/filter-options"}:
        counts = Counter(record["platform"] for record in RECORDS)
        return ok({"platforms": list(counts),
                   "platform_counts": [{"platform": platform, "count": count} for platform, count in counts.items()],
                   "authors": sorted({record["author"] for record in RECORDS}), "webhooks": []})
    if path == "/api/audit/summary":
        return ok({"summary": SUMMARY})
    if path.startswith("/api/task/demo-task-"):
        record = next((r for r in RECORDS if r["task_id"] == path.rsplit("/", 1)[-1]), RECORDS[0])
        return ok({**record, "summary": SUMMARY, "progress": {"percent": 100, "stage": "completed"}})
    if path.startswith("/api/marks/transcripts/demo-"):
        return ok({"marked": path.endswith("demo-note-0")})
    if path == "/api/collections/filter-options":
        return ok({"creators": [COURSE["creator"]], "types": ["document_topic"]})
    if path == "/api/collections":
        return ok({"items": [COLLECTION], "total": 1, "has_more": False})
    if path == "/api/collections/demo-course":
        return ok(COLLECTION)
    if path.startswith("/api/collections/demo-course/sources/"):
        source = next((x for x in SOURCES if x["id"] == path.rsplit("/", 1)[-1]), SOURCES[0])
        return ok({**source, "source_access": {"available": False, "reason": "读书案例演示"}})
    if path.endswith("/cloud-quote"):
        return ok({"state": "disabled", "items": [], "enabled": False})
    if path == "/api/reading/documents":
        return ok({"items": BOOKS})
    if path.startswith("/api/reading/documents/demo-book-"):
        index = int(path.split("demo-book-", 1)[1].split("/", 1)[0])
        return ok(book_detail(min(index, len(BOOKS) - 1)))
    if path == "/api/reading/preferences":
        return ok({"layout": "double", "theme": "paper", "font_size": 18, "font_family": "serif"})
    if path.startswith("/api/study/"):
        if path.endswith("/note-document"):
            return ok({"state": "clean", "document": {"body": "门店案例笔记\n\n便利店咖啡和办公室咖啡机，也可能是咖啡店的替代品。别只盯着街对面的同行。", "revision": 1}})
        return ok({"state": "ready", "metadata": {"title": PLAYER_TITLE, "author": "《竞争战略》读书案例", "view_token": "demo-note-1"},
                   "source": {"kind": "video", "filename": "演示视频.mp4"},
                   "playback": {"source_available": True, "source_url": "/demo-video.mp4", "duration_seconds": 45},
                   "transcript": {"lines": [{"id": f"line-{i}", "index": i, "text": text,
                                             "start_seconds": i * 8, "end_seconds": (i + 1) * 8, "seekable": True}
                                            for i, text in enumerate(PLAYER_LINES)]},
                   "ai": {"overview": SOURCES[0]["summary"], "chat_model": "演示模型"}})
    if path == "/api/journal/entry":
        return ok({"id": "demo-diary", "entry_date": DATE, "entry_type": "daily",
                   "title": "下班后的两小时", "body": DIARY, "updated_at": STAMP})
    if path == "/api/journal/entries":
        return ok({"items": []})
    if path == "/api/briefings":
        return {"items": [{"kind": "ai", "bundle": "demo-edition", "date": DATE,
                           "edition_date": DATE, "title": "AI 导游", "health": "ready"}],
                "warnings": [], "destinations": {}}
    if path == "/api/obsidian/status":
        return ok({"enabled": False, "configured": False})
    if path.startswith("/api/image-diagrams/"):
        return ok({"enabled": False, "source_ready": False, "versions": [], "active_job": None})
    if path.startswith("/api/visual-learning/"):
        return ok({"enabled": False, "document": None, "versions": []})
    if path.startswith("/api/users/profile"):
        return ok({"name": "演示用户", "user_id": "readme-demo"})
    if path.startswith("/api/asr/") or path.startswith("/api/transcription/"):
        return ok({"cloud_enabled": False, "default_strategy": "local"})
    return None


def result_html(path: str) -> str:
    env = Environment(loader=FileSystemLoader(WEB / "templates"), autoescape=select_autoescape())
    env.globals["asset_ver"] = get_static_asset_version(STATIC)
    request = SimpleNamespace(url=SimpleNamespace(path=path), query_params={})
    if path == "/briefings":
        return env.get_template("briefings.html").render(request=request, title="日报")
    return env.get_template("transcript.html").render(
        request=request, title=TITLE, author=MAIN["author"], platform=MAIN["platform"],
        view_token="demo-note-0", summary_html=SUMMARY_HTML,
        calibrated_html="".join(f"<p>{html.escape(p)}</p>" for p in TEXT.splitlines()),
        transcript=TEXT, source_transcript=TEXT, created_at=STAMP,
        created_at_display="2026-11-03 10:00", completed_at_display="2026-11-03 10:01",
        duration="39 分 31 秒", media_duration=2371, status="success", marked=True,
        source_language="zh", source_language_name="中文", url=MAIN["url"],
        summary=SUMMARY, calibrated=TEXT, is_marked=True,
    )


def briefing_html() -> str:
    # A published report is an HTML artifact loaded into the real report iframe.
    # These are authored example articles, never fetched private news or chats.
    content = "".join(
        f"<article><small>{html.escape(item['source'])} · {html.escape(item['published'])}</small>"
        f"<h2>{html.escape(item['title'])}</h2><blockquote>{html.escape(item['why'])}</blockquote>"
        f"<p>{html.escape(item['body'])}</p><a href='{html.escape(item['source_url'], quote=True)}' target='_blank' rel='noopener'>查看原文 ↗</a></article>"
        for item in BRIEFINGS
    )
    return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><style>body{margin:0;color:#33443d;background:#fdfcf8;font:17px/1.85 system-ui}article{padding:28px 32px;margin-bottom:22px;background:white;border:1px solid #e0e8e1;border-radius:16px}small{color:#536b5e}h2{color:#574179;font-size:25px;line-height:1.5;margin:16px 0}blockquote{margin:20px 0;padding:18px 22px;border-radius:12px;background:#f1edf6;color:#493c62}a{display:inline-block;color:#23634f;text-decoration:none;margin-top:10px}summary{color:#23634f;cursor:pointer}</style>" + content + "</html>"


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def send_body(self, body: str | bytes, content_type: str, status: int = 200) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data: object, status: int = 200) -> None:
        self.send_body(json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path, query = unquote(url.path), parse_qs(url.query)
        if path == "/service-worker.js":
            self.send_body("/* Documentation demo: intentionally no offline caching. */", "application/javascript")
            return
        if path == "/manifest.webmanifest":
            self.send_body((STATIC / "manifest.webmanifest").read_bytes(), "application/manifest+json")
            return
        if path == "/demo-video.mp4":
            media = ROOT / "output/playwright/readme-20261103-cases/demo-video.mp4"
            if media.is_file():
                data = media.read_bytes()
                requested = self.headers.get("Range", "")
                if requested.startswith("bytes="):
                    start_text, _, end_text = requested[6:].partition("-")
                    start = int(start_text or 0)
                    end = min(int(end_text) if end_text else len(data) - 1, len(data) - 1)
                    if start >= len(data) or start > end:
                        self.send_json({"detail": "Invalid media range"}, 416)
                        return
                    self.send_response(206)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.end_headers()
                    self.wfile.write(data[start:end + 1])
                else:
                    self.send_body(data, "video/mp4")
                return
        if path == "/api/briefings/ai/demo-edition/files/report.html":
            self.send_body(briefing_html(), "text/html; charset=utf-8")
            return
        if path.startswith("/api/"):
            payload = api_payload(path, query)
            self.send_json(payload if payload is not None else {"detail": "Unknown demo API"}, 200 if payload is not None else 404)
            return
        if path == "/briefings" or path.startswith("/view/demo-"):
            self.send_body(result_html(path), "text/html; charset=utf-8")
            return
        if path.startswith("/export/demo-"):
            self.send_body(TEXT, "text/plain; charset=utf-8")
            return
        pages = {"/": "index.html", "/add_task_by_web": "index.html", "/collections": "collections.html",
                 "/reading": "reading.html", "/study": "study.html", "/review": "review.html"}
        study = path.startswith("/study/demo-note-")
        if path in pages or path.startswith("/reading/demo-book-") or study:
            page = STATIC / ("study.html" if study else pages.get(path, "reading.html"))
            source = page.read_text(encoding="utf-8").replace("__ASSET_VERSION__", get_static_asset_version(STATIC))
            source = source.replace("__PAGE_MODE__", "single" if study else "library").replace("__VIEW_TOKEN__", path.rsplit("/", 1)[-1] if study else "").replace("__COLLECTION_ID__", "").replace("__SOURCE_ID__", "")
            self.send_body(source, "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC.resolve()) and asset.is_file():
                content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
                self.send_body(asset.read_bytes(), content_type)
                return
        self.send_json({"detail": "Not found in the documentation demo"}, 404)

    def do_POST(self) -> None:
        # Only UI auto-save is simulated. It never writes user data or settings.
        path = urlsplit(self.path).path
        if path == "/api/journal/entries":
            self.send_json(ok({"id": "demo-diary", "updated_at": STAMP}))
            return
        if path.endswith("/progress") or path == "/api/reading/preferences":
            self.send_json(ok({}))
            return
        self.send_json({"detail": "Processing is disabled in the documentation demo"}, 403)

    do_PUT = do_POST
    do_PATCH = do_POST

    def do_DELETE(self) -> None:
        self.send_json({"detail": "Deletion is disabled in the documentation demo"}, 403)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"Documentation demo: http://127.0.0.1:{server.server_port} (public-source notes and demo data only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
