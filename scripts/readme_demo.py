#!/usr/bin/env python3
"""Render real LearnFlux pages with authored, non-private screenshot fixtures.

Run with ``uv run python scripts/readme_demo.py``. This loopback-only server
never imports application configuration, opens a database or calls a provider.
It is a documentation tool, not an application backend.
"""

from __future__ import annotations

import argparse
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
TITLE = "把阅读变成可以复用的笔记"
TEXT = """读完一篇文章后，先合上原文，写下你最想回答的一个问题。
把作者的结论和支撑结论的例子分开记录；遇到不确定的地方，保留来源，方便回来核对。
笔记不必复述所有内容。用自己的话解释一个观点，再记录它适用的条件和一个反例。
最后，为这个观点设计一个很小的行动：明天用十五分钟试一次，再写下实际发生了什么。
理解不是把资料存起来，而是在下一次需要时，能够找到、判断并使用它。"""
SUMMARY = """## 先用一个问题组织阅读

把“我要读完这份资料”换成一个具体问题：**这段内容能帮助我做什么决定？** 问题越具体，越容易区分需要保留的依据和可以略过的细节。

### 从原文到自己的理解

1. **找结论**：作者希望读者相信什么？
2. **找依据**：结论依赖哪些事实、例子或假设？
3. **写解释**：合上原文，用自己的话讲一遍。
4. **做验证**：选一个小行动，记录实际结果。

> 笔记的价值，在于下次需要时能够找到、判断并使用它。

## 区分适用条件与行动

一个方法有用，并不代表它适合所有情况。记录“什么时候用”和“什么时候不用”，比只记一句结论更容易迁移。

### 一个可以马上尝试的练习

明天阅读一份短资料，用十五分钟写出：一个问题、一条依据、自己的解释，以及下一步行动。回看原文，补上遗漏的条件。

## 回到来源核对

摘要帮助建立结构，原文保留细节。遇到关键数字、观点冲突或准备引用时，回到正文核对，再决定是否采用。
"""
SUMMARY_HTML = markdown.markdown(SUMMARY, extensions=["tables", "fenced_code"])
CHAPTER_TITLES = ["用问题开始阅读", "区分结论与依据", "建立可检索的笔记", "用行动验证理解"]
RECORD_TITLES = [TITLE, "一门课程，怎样整理成一条主线", "用问题开始一次深度阅读", "从资料收藏到真正理解", "在安静的时间里写下想法", "复盘一次小小的行动"]
RECORDS = [
    {
        "id": f"demo-task-{i}", "task_id": f"demo-task-{i}",
        "view_token": f"demo-note-{i}", "title": title,
        "author": "LearnFlux 示例", "platform": ["local", "youtube", "bilibili", "xiaohongshu", "douyin", "weixin"][i],
        "status": "success", "created_at": STAMP, "completed_at": STAMP,
        "request_time": STAMP, "request_time_display": DATE + " 10:00",
        "description": "原创演示资料 · 保留原文与学习笔记", "is_marked": i == 0,
        "duration": 360 + i * 60, "summary": SUMMARY,
        "study_available": True, "study_url": f"/study/demo-note-{i}",
        "content_type": "text" if i == 0 else "video", "marked": i == 0,
        "url": "https://example.com/learnflux-demo", "summary_available": True,
    }
    for i, title in enumerate(RECORD_TITLES)
]
SOURCES = [
    {
        "id": f"demo-chapter-{i}", "title": title, "filename": title + ".mp4",
        "source_type": "video", "task_status": "success", "order_index": i,
        "view_token": f"demo-note-{i}", "elapsed_seconds": 90 + i * 15,
        "duration": 360 + i * 60, "study_available": True,
        "study_url": f"/study/collections/demo-course/sources/demo-chapter-{i}",
        "summary": SUMMARY, "transcription_strategy": "local",
    }
    for i, title in enumerate(CHAPTER_TITLES)
]
COLLECTION = {
    "id": "demo-course", "title": "建立自己的学习系统", "creator": "LearnFlux 示例",
    "collection_type": "video_course", "status": "completed", "created_at": STAMP,
    "updated_at": STAMP, "sources": SOURCES, "source_count": 4,
    "total_sources": 4, "completed_sources": 4, "success_count": 4,
    "summary_markdown": SUMMARY, "summary_status": "success",
    "transcription_strategy": "local", "transcription_concurrency": 1,
}
BOOK_TITLES = ["把阅读变成可以复用的笔记", "一份关于专注的练习手册", "观察、提问与理解", "留一点时间给自己的想法"]
BOOKS = [
    {"id": f"demo-book-{i}", "title": title, "author": "LearnFlux 示例",
     "format": "markdown", "status": "ready", "created_at": STAMP,
     "updated_at": STAMP, "last_opened_at": STAMP}
    for i, title in enumerate(BOOK_TITLES)
]
PARAGRAPHS = [
    "清晨翻开一份资料之前，不妨先问自己：今天最想弄清楚的是什么？一个真实的问题，会让注意力从漫无目的的浏览，转向有方向的寻找。",
    "阅读不必是一场赶路。停下来，把一段话放回它的上下文，看看作者在回答谁的问题、依赖什么条件，也看看自己是否遗漏了另一种解释。",
    "读到一个有启发的观点，可以暂时合上原文，用最熟悉的话讲给自己听。如果讲不清楚，就把卡住的地方写成一个问题，再回去寻找依据。",
    "笔记可以很短：一个问题、一条依据、一段自己的解释。保留原文位置，不是为了收集更多材料，而是让未来的自己能够重新检查当时的判断。",
    "理解还需要与生活相遇。为一个想法安排一次小小的尝试，观察它在具体情境里如何起作用；如果结果不同，也把这个差异写下来。",
    "下次打开笔记时，先找那个尚未解决的问题。沿着问题继续读，比从头再看一遍更容易把零散的资料连接起来。",
    "试着区分三件事：资料原本说了什么、你怎样理解、你准备做什么。把它们分别写清楚，下次回看时就不会把自己的推测误当成作者的结论。",
    "如果两份资料说法不同，先不要急着选边。比较它们讨论的对象、时间和前提，分歧有时来自条件不同，而不是谁完全正确。",
    "遇到一句很想引用的话，回到原文多读一段。查看上下文，记录来源位置，并把自己尚不确定的地方保留下来。清楚地知道不知道什么，也是一种进步。",
    "行动可以小到十分钟内完成。比如用今天学到的方法整理一份笔记，或者向同伴解释一个概念，再问问对方哪里还不明白。",
    "定期回看，不必把每一页重新读一遍。先看最初的问题，再检查行动记录，最后决定哪些资料需要继续深入，哪些可以暂时放下。",
    "慢慢地，这些短小的记录会形成一条自己的线索。它不追求收藏数量，而是帮助你在具体时刻，做出更清楚的判断。",
]
READING_CHAPTERS = [
    {"id": f"part-{i}", "title": title, "order_index": i,
     "sanitized_html": f"<h1>{title}</h1>" + "".join(f"<p>{p}</p>" for p in PARAGRAPHS)}
    for i, title in enumerate(CHAPTER_TITLES)
]
DIARY = """今天，给一个问题留一点时间

傍晚把刚读完的资料重新打开，没有急着收藏更多内容，而是先写下那个还没想明白的问题。

作者的结论很有启发，但真正让我停下来的，是支撑结论的那一个例子。我试着用自己的话重新解释，才发现自己原来省略了一个重要条件。

明天的计划很简单：花十五分钟做一次小练习，记录结果，再回来看看今天的理解有没有改变。

窗外在下雨。先把这些想法写下来。"""


def ok(data: object) -> dict:
    return {"code": 200, "message": "ok", "data": data}


def book_detail(index: int) -> dict:
    return {"document": BOOKS[index], "chapters": READING_CHAPTERS,
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
        return ok({"platforms": [r["platform"] for r in RECORDS],
                   "platform_counts": [{"platform": r["platform"], "count": 1} for r in RECORDS],
                   "authors": ["LearnFlux 示例"], "webhooks": []})
    if path == "/api/audit/summary":
        return ok({"summary": SUMMARY})
    if path.startswith("/api/task/demo-task-"):
        record = next((r for r in RECORDS if r["task_id"] == path.rsplit("/", 1)[-1]), RECORDS[0])
        return ok({**record, "summary": SUMMARY, "progress": {"percent": 100, "stage": "completed"}})
    if path.startswith("/api/marks/transcripts/demo-"):
        return ok({"marked": path.endswith("demo-note-0")})
    if path == "/api/collections/filter-options":
        return ok({"creators": ["LearnFlux 示例"], "types": ["video_course"]})
    if path == "/api/collections":
        return ok({"items": [COLLECTION], "total": 1, "has_more": False})
    if path == "/api/collections/demo-course":
        return ok(COLLECTION)
    if path.startswith("/api/collections/demo-course/sources/"):
        source = next((x for x in SOURCES if x["id"] == path.rsplit("/", 1)[-1]), SOURCES[0])
        return ok({**source, "summary": SUMMARY, "transcript": TEXT,
                   "source_access": {"available": False, "reason": "演示内容"}})
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
            return ok({"state": "clean", "document": {"body": "问题：怎样把理解变成行动？\n\n先记录依据，再安排一次十五分钟的尝试。", "revision": 1}})
        return ok({"state": "ready", "metadata": {"title": "用问题开始阅读（演示视频）", "author": "LearnFlux 示例", "view_token": "demo-note-1"},
                   "source": {"kind": "video", "filename": "演示视频.mp4"},
                   "playback": {"source_available": True, "source_url": "/demo-video.mp4", "duration_seconds": 8},
                   "transcript": {"lines": [{"id": f"line-{i}", "index": i, "text": text,
                                             "start_seconds": i * 1.5, "end_seconds": (i + 1) * 1.5, "seekable": True}
                                            for i, text in enumerate(TEXT.splitlines())]},
                   "ai": {"overview": SUMMARY, "chat_model": "演示模型"}})
    if path == "/api/journal/entry":
        return ok({"id": "demo-diary", "entry_date": DATE, "entry_type": "daily",
                   "title": "给一个问题留一点时间", "body": DIARY, "updated_at": STAMP})
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
        request=request, title=TITLE, author="LearnFlux 示例", platform="text",
        view_token="demo-note-0", summary_html=SUMMARY_HTML,
        calibrated_html="".join(f"<p>{p}</p>" for p in TEXT.splitlines()),
        transcript=TEXT, source_transcript=TEXT, created_at=STAMP,
        created_at_display="2026-11-03 10:00", completed_at_display="2026-11-03 10:01",
        duration="6 分钟", media_duration=360, status="success", marked=True,
        source_language="zh", source_language_name="中文", url="https://example.com/learnflux-demo",
        summary=SUMMARY, calibrated=TEXT, is_marked=True,
    )


def briefing_html() -> str:
    # A published report is an HTML artifact loaded into the real report iframe.
    # These are authored example articles, never fetched private news or chats.
    cards = [("把一次阅读变成可复用的笔记", "先问一个具体问题，保留结论与依据，再用一次小行动检验理解。", TEXT),
             ("给 AI 任务写下验收方式", "把完成标准写成能够观察的行为：输入什么，得到什么，如何回到来源核对。",
              "把一个大任务拆成几个有明确结果的小步骤。开始前写下输入和预期，完成后用具体例子检查结果，并保留来源。遇到不确定的判断，先记录疑问，再补充依据。自动化应该让重复工作更轻松，也应该让人容易发现哪里出了问题。")]
    content = "".join(f"<article><small>LearnFlux 示例 · {DATE}</small><h2>{t}</h2><blockquote>值得尝试：{p}</blockquote><p>{body}</p><details><summary>展开解读</summary><p>{p}</p></details></article>" for t, p, body in cards)
    return "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><style>body{margin:0;color:#33443d;background:#fdfcf8;font:17px/1.85 system-ui}article{padding:28px 32px;margin-bottom:22px;background:white;border:1px solid #e0e8e1;border-radius:16px}small{color:#536b5e}h2{color:#574179;font-size:25px;line-height:1.5;margin:16px 0}blockquote{margin:20px 0;padding:18px 22px;border-radius:12px;background:#f1edf6;color:#493c62}summary{color:#23634f;cursor:pointer}</style>" + content + "</html>"


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
            media = ROOT / "output/playwright/readme-20261103/demo-video.mp4"
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
    print(f"Documentation demo: http://127.0.0.1:{server.server_port} (authored data only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
