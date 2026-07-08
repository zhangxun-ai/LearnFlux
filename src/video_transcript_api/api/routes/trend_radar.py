"""Trend radar page and manual report APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..context import get_logger, get_static_dir
from ..services.transcription import verify_token
from ...trend_radar import service as svc

logger = get_logger()
router = APIRouter()


class RunReportBody(BaseModel):
    budget_usd: float = Field(default=5.0, gt=0)
    mode: str = "standard"


@router.get("/trend-radar", include_in_schema=False)
async def trend_radar_page():
    path = get_static_dir() / "trend-radar.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="趋势雷达页面不存在")
    html = path.read_text(encoding="utf-8")
    if "<base " not in html:
        html = html.replace("<head>", '<head>\n    <base href="/static/">', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@router.get("/api/trend-radar/reports/latest")
async def get_latest_report(user_info: dict = Depends(verify_token)):
    report = await run_in_threadpool(svc.latest_report)
    if not report:
        return JSONResponse(status_code=404, content={"ok": False, "error": "暂无趋势雷达报告"})
    return report


@router.get("/api/trend-radar/reports")
async def list_reports(
    limit: int = Query(default=10, ge=1, le=30),
    user_info: dict = Depends(verify_token),
):
    return await run_in_threadpool(svc.list_reports, limit=limit)


@router.get("/api/trend-radar/reports/{report_id}")
async def get_report(report_id: str, user_info: dict = Depends(verify_token)):
    report = await run_in_threadpool(svc.read_report, report_id)
    if not report:
        return JSONResponse(status_code=404, content={"ok": False, "error": "趋势雷达报告不存在"})
    return report


@router.get("/api/trend-radar/jobs/{job_id}")
async def get_report_job(job_id: str, user_info: dict = Depends(verify_token)):
    job = svc.get_report_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"ok": False, "error": "趋势雷达任务不存在"})
    return job


@router.post("/api/trend-radar/reports/run")
async def run_report(body: RunReportBody, user_info: dict = Depends(verify_token)):
    if body.budget_usd > 5:
        raise HTTPException(status_code=400, detail="单次趋势雷达预算不能超过 $5")
    job = svc.start_report_job(budget_usd=body.budget_usd, mode=body.mode)
    return JSONResponse(status_code=202, content=job)
