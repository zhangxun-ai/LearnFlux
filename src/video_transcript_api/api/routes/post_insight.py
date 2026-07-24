"""Web routes for X / Twitter post insight.

Independent of the video pipeline: a lightweight page (`GET /post`) plus a single
analysis endpoint (`POST /api/post-insight`) that runs the post-insight service in
a worker thread and returns structured, render-ready sections. Auth reuses the
same bearer-token dependency as transcription.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..context import get_llm_coordinator, get_logger, get_templates
from ..services.post_insight import generate_post_insight
from ..services.transcription import verify_token
from ...comments.post_analyzer import PostInsightAnalyzer
from ...utils.rendering import render_markdown_to_html

logger = get_logger()
templates = get_templates()
router = APIRouter()

# Map an analyzer section heading to a stable key + canonical title. The key
# drives per-section styling on the page (the credibility card is emphasized).
_SECTION_MAP = [
    ("positioning", "内容定位", ("内容定位", "类型定位")),
    ("claims", "正文核心主张", ("核心主张", "正文核心")),
    ("credibility", "证据与可信度", ("可信度", "存疑", "证据")),
    ("demand_mine", "评论需求矿场", ("评论需求矿场", "需求矿场", "需求信号")),
    ("opportunity", "机会判断", ("机会判断", "机会")),
    ("comments", "评论区：共识 vs 争议", ("评论区", "共识")),
    ("representative", "代表性高赞回复", ("代表性", "高赞回复")),
    ("actions", "对你的可行动启发", ("可行动", "启发")),
]

# Turn the analyzer's bracketed credibility labels into scannable colored chips.
_CHIP_REPLACEMENTS = [
    ("[共识/可信]", '<span class="cred-chip cred-ok">✓ 共识/可信</span>'),
    ("[单方面断言]", '<span class="cred-chip cred-claim">⚠ 单方面断言</span>'),
    ("[需外部核实]", '<span class="cred-chip cred-verify">❗ 需外部核实</span>'),
    ("[回复区有反驳]", '<span class="cred-chip cred-rebut">🔁 回复区有反驳</span>'),
]


def _classify_heading(heading: str) -> tuple[str, str]:
    for key, title, keywords in _SECTION_MAP:
        if any(kw in heading for kw in keywords):
            return key, title
    return "other", heading


def _apply_credibility_chips(html: str) -> str:
    for token, chip in _CHIP_REPLACEMENTS:
        html = html.replace(token, chip)
    return html


def build_insight_sections(markdown: str) -> list[dict]:
    """Split insight markdown by ``##`` headers into render-ready sections.

    Returns a list of ``{key, title, html}``. The credibility section's labels
    are converted to colored chips. Markdown with no headers becomes one block.
    """
    parts = re.split(r"(?m)^\s*##\s+(.+?)\s*$", markdown or "")
    preamble = (parts[0] or "").strip()

    pairs: list[tuple[str, str]] = []
    index = 1
    while index < len(parts):
        heading = parts[index].strip()
        body = parts[index + 1] if index + 1 < len(parts) else ""
        pairs.append((heading, body))
        index += 2

    if not pairs:
        if not preamble:
            return []
        return [{"key": "other", "title": "洞察", "html": render_markdown_to_html(preamble)}]

    sections: list[dict] = []
    for heading, body in pairs:
        key, title = _classify_heading(heading)
        html = render_markdown_to_html(body.strip())
        if key == "credibility":
            html = _apply_credibility_chips(html)
        sections.append({"key": key, "title": title, "html": html})
    return sections


class PostInsightRequest(BaseModel):
    url: str


@router.get("/post", response_class=HTMLResponse, include_in_schema=False)
async def post_insight_page(request: Request, url: str = ""):
    """Render the X post insight page (entry form + result container)."""
    return templates.TemplateResponse(
        "post_insight.html",
        {"request": request, "title": "帖子精华提炼", "prefill_url": url},
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/api/post-insight")
async def create_post_insight(
    body: PostInsightRequest,
    user_info: dict = Depends(verify_token),
):
    """Fetch + analyze an X post and return structured insight sections."""
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="链接不能为空")

    coordinator = get_llm_coordinator()
    analyzer = PostInsightAnalyzer(
        llm_client=coordinator.llm_client,
        model=coordinator.config.summary_model,
        reasoning_effort=getattr(coordinator.config, "summary_reasoning_effort", None),
    )

    try:
        result = await run_in_threadpool(generate_post_insight, url, analyzer=analyzer)
    except ValueError as exc:
        # Unsupported platform / empty insight / surfaced fetch validation error.
        logger.warning(f"Post insight rejected: url={url}, reason={exc}")
        return JSONResponse(status_code=422, content={"ok": False, "error": str(exc)})
    except Exception:
        logger.exception(f"Post insight failed: url={url}")
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "抓取或分析失败，请稍后重试"},
        )

    return {
        "ok": True,
        "title": result.title,
        "author": result.author,
        "source_url": result.source_url,
        "fetched_comment_count": result.fetched_comment_count,
        "analyzed_comment_count": len(result.comment_samples),
        "thread_text": result.thread_text,
        "demand_signals": result.demand_signals,
        "raw_markdown": result.insight_markdown,
        "sections": build_insight_sections(result.insight_markdown),
    }
