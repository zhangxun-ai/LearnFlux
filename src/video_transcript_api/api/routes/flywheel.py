"""Web routes for the creation flywheel.

A page (`GET /flywheel`) plus JSON endpoints for quick-analyze, content listing,
blogger management and usage. Analysis runs in a worker thread (video transcribe
is slow). Auth reuses the same bearer-token dependency as transcription.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..context import get_llm_coordinator, get_logger, get_templates
from ..services import flywheel_service as svc
from ..services.transcription import verify_token
from ...flywheel.analyzer import ContentAnalyzer
from ...flywheel.draft_generator import DraftGenerator

logger = get_logger()
templates = get_templates()
router = APIRouter()


def _build_analyzer() -> ContentAnalyzer:
    coord = get_llm_coordinator()
    return ContentAnalyzer(
        llm_client=coord.llm_client,
        model=coord.config.summary_model,
        reasoning_effort=getattr(coord.config, "flywheel_reasoning_effort", None),
    )


def _build_draft_generator() -> DraftGenerator:
    coord = get_llm_coordinator()
    return DraftGenerator(
        llm_client=coord.llm_client,
        model="deepseek-v4-pro",
        reasoning_effort="high",
    )


class UrlBody(BaseModel):
    url: str


class PromptBody(BaseModel):
    body: str


@router.get("/flywheel", response_class=HTMLResponse, include_in_schema=False)
async def flywheel_page(request: Request):
    return templates.TemplateResponse(
        "flywheel.html",
        {"request": request, "title": "IP 对标工作台"},
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/api/flywheel/analyze")
async def analyze(body: UrlBody, user_info: dict = Depends(verify_token)):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="链接不能为空")
    try:
        analyzer = _build_analyzer()
        result = await run_in_threadpool(svc.analyze_url, url, analyzer)
    except ValueError as exc:
        logger.warning(f"flywheel analyze rejected: url={url}, reason={exc}")
        return JSONResponse(status_code=422, content={"ok": False, "error": str(exc)})
    except Exception:
        logger.exception(f"flywheel analyze failed: url={url}")
        return JSONResponse(status_code=502,
                            content={"ok": False, "error": "抓取或解析失败，请稍后重试"})
    return result


@router.get("/api/flywheel/contents")
async def contents(request: Request, user_info: dict = Depends(verify_token)):
    q = request.query_params

    def _csv(name):
        raw = q.get(name, "")
        return [x for x in raw.split(",") if x] if raw else []

    try:
        result = await run_in_threadpool(
            svc.list_contents,
            subscribe=q.get("subscribe") or None,
            blogger_ids=[int(x) for x in _csv("blogger_ids")],
            statuses=_csv("statuses"),
            media_type=q.get("media_type") or None,
            date_preset=q.get("date") or None,
            sort=q.get("sort") or "published_at",
            page=int(q.get("page", 1)),
            page_size=int(q.get("page_size", 20)),
        )
    except Exception:
        logger.exception("flywheel contents list failed")
        return JSONResponse(status_code=500, content={"error": "列表查询失败"})
    return result


@router.get("/api/flywheel/content/{content_id}")
async def get_content(content_id: int, user_info: dict = Depends(verify_token)):
    try:
        return await run_in_threadpool(svc.get_analysis, content_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(exc)})


@router.post("/api/flywheel/content/{content_id}/draft")
async def generate_draft(content_id: int, user_info: dict = Depends(verify_token)):
    try:
        generator = _build_draft_generator()
        return await run_in_threadpool(svc.generate_draft, content_id, generator)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(exc)})
    except Exception:
        logger.exception(f"flywheel draft generation failed: content_id={content_id}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "新帖生成失败，请稍后重试"})


@router.get("/api/flywheel/prompts")
async def prompts(user_info: dict = Depends(verify_token)):
    return await run_in_threadpool(svc.get_prompts)


@router.put("/api/flywheel/prompts/{media_type}")
async def update_prompt(media_type: str, body: PromptBody, user_info: dict = Depends(verify_token)):
    try:
        return await run_in_threadpool(svc.update_prompt, media_type, body.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/flywheel/prompts/{media_type}/reset")
async def reset_prompt(media_type: str, user_info: dict = Depends(verify_token)):
    try:
        return await run_in_threadpool(svc.reset_prompt, media_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/flywheel/bloggers")
async def bloggers(user_info: dict = Depends(verify_token)):
    return {"items": await run_in_threadpool(svc.list_bloggers)}


@router.post("/api/flywheel/subscribe")
async def subscribe(body: UrlBody, user_info: dict = Depends(verify_token)):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="链接不能为空")
    try:
        return await run_in_threadpool(svc.subscribe, url)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(exc)})
    except Exception:
        logger.exception(f"flywheel subscribe failed: url={url}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "订阅失败"})


@router.get("/api/flywheel/usage")
async def usage(user_info: dict = Depends(verify_token)):
    return await run_in_threadpool(svc.usage)
