import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from ..services.longcut import (
    build_analysis_url,
    build_longcut_action,
    ensure_longcut_ready,
    get_longcut_settings,
)
from ..context import (
    get_cache_manager,
    get_config,
    get_logger,
    get_static_dir,
    get_templates,
    get_usage_repository,
)
from ...utils.rendering import (
    get_base_url,
    normalize_markdown_text,
    render_calibrated_content_smart,
    render_markdown_to_html,
    render_transcript_content,
)
from ...utils.timeutil import format_datetime_for_display, get_configured_timezone
from ...collections.titles import source_display_title

logger = get_logger()
cache_manager = get_cache_manager()
templates = get_templates()
static_dir = get_static_dir()


router = APIRouter()

_EXPORT_TYPE_LABELS = {
    "calibrated": "校对文本",
    "summary": "总结文本",
    "comment_insight": "高赞评论洞察",
    "transcript": "原始转录",
}

_EXPORT_SECTION_LABELS = {
    "calibrated": "校对文本",
    "summary": "内容总结",
    "comment_insight": "高赞评论洞察",
    "transcript": "原始转录",
}

_EXPORT_SCOPE_LABELS = {
    "analysis": "AI解析",
    "calibrated": "校对文本",
    "full": "全内容",
}

_EXPORT_SCOPE_SECTIONS = {
    "analysis": ("summary", "comment_insight"),
    "calibrated": ("calibrated",),
    "full": ("summary", "comment_insight", "calibrated", "transcript"),
}

_LOCAL_DOCUMENT_EXTS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".log",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
}


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _build_asr_usage_display(event: Any | None) -> Dict[str, str]:
    """Build the small, user-facing ASR cost summary for a result page."""
    if event is None:
        return {
            "label": "云端 ASR 未调用（¥0）",
            "detail": "本次未产生云端 ASR 用量",
        }
    if event.billed_cost is not None:
        return {
            "label": f"云端 ASR 账单 ¥{event.billed_cost}",
            "detail": "供应商返回的账单费用",
        }
    if event.calculated_cost is not None:
        return {
            "label": f"云端 ASR 费用约 ¥{event.calculated_cost}",
            "detail": "按云端返回用量计算；最终以供应商账单为准",
        }
    return {
        "label": f"云端 ASR 费用上限 ¥{event.estimated_cost}",
        "detail": "提交前按可信时长计算的费用上限",
    }


def _is_local_document_view(view_data: Dict[str, Any]) -> bool:
    url = str(view_data.get("url") or "")
    if not url.startswith("local://"):
        return False
    ext = os.path.splitext(url.split("?", 1)[0])[1].lower()
    return ext in _LOCAL_DOCUMENT_EXTS


def _local_url_filename(view_data: Dict[str, Any]) -> str:
    url = str(view_data.get("url") or "")
    if not url.startswith("local://"):
        return ""
    path = url.split("?", 1)[0].rstrip("/")
    filename = path.rsplit("/", 1)[-1]
    return unquote(filename) if filename else ""


# robots.txt：允许首页和分享页面被收录，禁止 API 和静态资源
_ROBOTS_TXT_TEMPLATE = """\
User-agent: *
Allow: /
Disallow: /api/
Disallow: /static/
Sitemap: {base_url}/sitemap.xml
"""

# sitemap.xml：仅包含首页，引导搜索引擎只收录首页
_SITEMAP_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{base_url}/</loc>
  </url>
</urlset>
"""


def _source_files_dir() -> Path:
    storage_cfg = get_config().get("storage", {}) or {}
    source_dir = storage_cfg.get("source_files_dir") or "./data/source_files/collection_uploads"
    return Path(source_dir)


def _is_browser_source_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _media_id_from_local_url(url: str) -> str:
    if not url.startswith("local://"):
        return ""
    parts = url.replace("local://", "", 1).split("/")
    if len(parts) >= 2 and parts[0] == "collection-source":
        return parts[1]
    if len(parts) >= 3 and parts[0] == "collection":
        return parts[2]
    return ""


def _local_source_file_path(view_data: Dict[str, Any]) -> Optional[Path]:
    explicit_path = str(view_data.get("source_file_path") or "").strip()
    if explicit_path:
        path = Path(explicit_path)
        if path.exists() and path.is_file():
            return path

    url = str(view_data.get("url") or "")
    if not url.startswith("local://"):
        return None
    media_id = str(view_data.get("media_id") or _media_id_from_local_url(url)).strip()
    if not media_id:
        return None
    title = str(view_data.get("title") or url)
    ext = os.path.splitext(title)[1][:10] or ".bin"
    path = _source_files_dir() / f"{media_id}{ext}"
    return path if path.exists() else None


def _decorate_source_link(view_data: Dict[str, Any]) -> None:
    url = str(view_data.get("url") or "").strip()
    if _local_source_file_path(view_data) and view_data.get("view_token"):
        view_data["source_link_url"] = f"/view/{view_data['view_token']}/source-file"
        view_data["source_link_label"] = "下载源文件"
        view_data["source_reveal_url"] = f"/view/{view_data['view_token']}/source-file/reveal"
        view_data["source_reveal_label"] = "在本机显示"
        return
    if _is_browser_source_url(url):
        view_data["source_link_url"] = url
        view_data["source_link_label"] = "查看原视频"
        return
    if not url.startswith("local://"):
        return


def _build_collection_navigation(view_token: str) -> Optional[Dict[str, Any]]:
    try:
        from .collections import get_collection_service

        return get_collection_service().get_source_navigation_by_view_token(view_token)
    except Exception as exc:
        logger.debug(f"collection navigation unavailable: {exc}")
        return None


def _decorate_collection_display_title(view_data: Dict[str, Any]) -> None:
    url = str(view_data.get("url") or "")
    if not url.startswith("local://collection-source/"):
        return
    display_title = source_display_title(
        view_data.get("title") or _local_url_filename(view_data)
    )
    if display_title:
        view_data["title"] = display_title


def _parse_task_datetime(value) -> Optional[datetime]:
    """Parse DB/ISO task timestamps as UTC-aware datetimes."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    total_seconds = max(0, int(round(seconds)))
    if total_seconds < 60:
        return f"{total_seconds} 秒"
    minutes, rest = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {rest} 秒" if rest else f"{minutes} 分"
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{hours} 小时 {minutes} 分"
    return f"{hours} 小时"


def _format_local_datetime(value, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    parsed = _parse_task_datetime(value)
    if not parsed:
        return value or ""
    return parsed.astimezone(get_configured_timezone()).strftime(fmt)


def _decorate_title_and_tags(view_data: Dict[str, Any]):
    """Extract hashtags from title and clean it up."""
    import re
    title = view_data.get("title", "")
    if not title or not isinstance(title, str):
        return
    
    tags = re.findall(r'#([^\s#]+)', title)
    if tags:
        clean_title = re.sub(r'#([^\s#]+)', '', title).strip()
        clean_title = re.sub(r'[\s\-]+$', '', clean_title)
        view_data["title"] = clean_title
        existing_tags = view_data.get("tags") or []
        view_data["tags"] = list(dict.fromkeys(existing_tags + tags))

def _decorate_view_timing(view_data: Dict[str, Any], now: Optional[datetime] = None):
    """Add user-facing elapsed/duration/progress time fields in-place."""
    current_time = now or datetime.now(timezone.utc)
    created_at = _parse_task_datetime(view_data.get("created_at"))
    completed_at = _parse_task_datetime(view_data.get("completed_at"))

    if view_data.get("created_at"):
        view_data["created_at_display"] = format_datetime_for_display(
            view_data["created_at"]
        )

    if view_data.get("completed_at"):
        view_data["completed_at_display"] = _format_local_datetime(
            view_data["completed_at"]
        )

    if created_at:
        end_time = completed_at or current_time
        elapsed_seconds = max(0, int(round((end_time - created_at).total_seconds())))
        view_data["elapsed_seconds"] = elapsed_seconds
        view_data["elapsed_display"] = _format_duration(elapsed_seconds)
        if completed_at:
            view_data["duration_seconds"] = elapsed_seconds
            view_data["duration_display"] = view_data["elapsed_display"]

    progress = view_data.get("progress")
    if isinstance(progress, dict) and progress.get("updated_at"):
        progress["updated_at_display"] = _format_local_datetime(
            progress["updated_at"]
        )


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    """返回 robots.txt，允许首页被搜索引擎收录以建立域名信任."""
    base_url = get_base_url()
    content = _ROBOTS_TXT_TEMPLATE.format(base_url=base_url)
    return Response(content=content, media_type="text/plain")


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    """返回 sitemap.xml，仅包含首页以引导搜索引擎收录."""
    base_url = get_base_url()
    content = _SITEMAP_XML_TEMPLATE.format(base_url=base_url)
    return Response(content=content, media_type="application/xml")


@router.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    """返回 PWA manifest，供手机端添加到主屏幕。"""
    manifest_path = static_dir / "manifest.webmanifest"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="manifest not found")
    return FileResponse(
        path=str(manifest_path),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/service-worker.js", include_in_schema=False)
async def service_worker():
    """从根路径提供 service worker，保证 scope 覆盖整个站点。"""
    sw_path = static_dir / "service-worker.js"
    if not sw_path.exists():
        raise HTTPException(status_code=404, detail="service worker not found")
    return FileResponse(
        path=str(sw_path),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


# 首页 HTML：简洁的服务介绍页，供搜索引擎收录以建立域名信任
_HOME_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LearnFlux · 把音视频变成可复习的学习资产</title>
    <meta name="description" content="粘贴链接或上传本地文件，完成精准转写、AI 深度解读与边播边学。支持系列专题、图解生成与 Obsidian 同步。">
    <meta name="theme-color" content="#F9FAFB">
    <meta name="application-name" content="LearnFlux">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="LearnFlux">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <link rel="manifest" href="/manifest.webmanifest">
    <link rel="icon" type="image/png" href="/static/icon/learnflux-favicon-32.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/icon/learnflux-favicon-32.png">
    <link rel="apple-touch-icon" href="/static/icon/learnflux-apple-touch-icon.png">
    <meta property="og:title" content="LearnFlux · 深度学习工作台">
    <meta property="og:description" content="把海量音视频与文档，变成可复习的学习资产。">
    <meta property="og:type" content="website">
    <meta property="og:image" content="/static/icon/learnflux-og.png">
    <meta name="twitter:card" content="summary_large_image">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        html{-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;scroll-behavior:smooth}
        body{
            font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            color: #111827;
            background: #F9FAFB;
            line-height: 1.6;
            min-height: 100vh;
            overflow-x: hidden;
        }
        a{color:inherit;text-decoration:none}
        img{max-width:100%;height:auto;display:block}
        ::selection{background:#2563EB;color:#fff}

        .nav{
            max-width:1120px;margin:0 auto;padding:20px 24px;
            display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:20;
            background:rgba(249,250,251,0.88);backdrop-filter:blur(12px);
        }
        .brand a{display:flex;align-items:center;gap:10px;font-weight:600;font-size:1.05rem;color:#111827}
        .brand img{
            width:32px;height:32px;border-radius:8px;object-fit:cover;
            box-shadow:0 1px 2px rgba(15,23,42,0.08);
        }
        .links{margin-left:auto;display:flex;gap:4px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
        .links a{
            font-size:.9rem;color:#4B5563;padding:8px 12px;border-radius:8px;
            transition:all .15s ease;font-weight:500;white-space:nowrap;
        }
        .links a:hover{background:rgba(0,0,0,0.04);color:#111827}
        .links a.cta{
            background:#2563EB;color:#fff;padding:8px 16px;margin-left:4px;
        }
        .links a.cta:hover{background:#1D4ED8;box-shadow:0 4px 12px rgba(37,99,235,0.2)}

        .hero{
            max-width:880px;margin:0 auto;text-align:center;
            padding:56px 24px 40px;position:relative;z-index:10;
        }
        .eyebrow{
            display:inline-block;
            font-size:0.82rem;letter-spacing:0.04em;color:#2563EB;font-weight:600;
            background:rgba(37,99,235,0.08);padding:6px 14px;border-radius:999px;
            margin-bottom:20px;
        }
        .hero h1{
            font-weight:700;
            font-size:clamp(1.75rem, 5.2vw, 3.25rem);
            line-height:1.22;
            letter-spacing:-0.02em;
            color:#111827;
            overflow-wrap:anywhere;
            word-break:break-word;
            max-width:100%;
        }
        .hero h1 em{font-style:normal;color:#2563EB}
        .hero .sub{
            margin:20px auto 0;max-width:620px;color:#4B5563;
            font-size:clamp(0.98rem, 2.4vw, 1.12rem);line-height:1.7;
            overflow-wrap:anywhere;
        }
        .cta-row{margin-top:32px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
        .btn{
            display:inline-flex;align-items:center;justify-content:center;
            padding:12px 24px;border-radius:10px;font-weight:600;font-size:1rem;
            transition:all .15s ease;cursor:pointer;min-height:48px;
        }
        .btn-primary{background:#2563EB;color:#fff;box-shadow:0 4px 14px rgba(37,99,235,0.22)}
        .btn-primary:hover{background:#1D4ED8;transform:translateY(-1px);box-shadow:0 6px 18px rgba(37,99,235,0.28)}
        .btn-ghost{background:#fff;color:#111827;border:1px solid #E5E7EB;box-shadow:0 1px 2px rgba(0,0,0,0.03)}
        .btn-ghost:hover{border-color:#D1D5DB;background:#F9FAFB}

        .demo-container{max-width:1120px;margin:0 auto 72px;padding:0 24px}
        .demo-mockup{
            width:100%;border-radius:16px;overflow:hidden;
            border:1px solid rgba(0,0,0,0.08);
            box-shadow:0 24px 60px -16px rgba(15,23,42,0.14), 0 8px 20px -12px rgba(15,23,42,0.08);
            background:#fff;
        }
        .mockup-header{
            height:40px;background:#fff;border-bottom:1px solid #F3F4F6;
            display:flex;align-items:center;padding:0 16px;gap:8px;
        }
        .mockup-dot{width:10px;height:10px;border-radius:50%;background:#E5E7EB}
        .mockup-dot.red{background:#FECACA}
        .mockup-dot.yellow{background:#FEF08A}
        .mockup-dot.green{background:#BBF7D0}
        .demo-caption{
            text-align:center;margin-top:14px;color:#6B7280;font-size:0.9rem;
        }
        .shot-grid{
            display:grid;grid-template-columns:repeat(3,1fr);gap:16px;
            max-width:1120px;margin:0 auto 96px;padding:0 24px;
        }
        .shot-card{
            background:#fff;border:1px solid #E5E7EB;border-radius:14px;overflow:hidden;
            transition:border-color .15s ease, box-shadow .15s ease;
        }
        .shot-card:hover{border-color:#CBD5E1;box-shadow:0 10px 24px -12px rgba(15,23,42,0.12)}
        .shot-card img{width:100%;aspect-ratio:16/10;object-fit:cover;object-position:top;background:#F3F4F6}
        .shot-card p{padding:12px 14px;font-size:0.88rem;color:#4B5563;font-weight:500}

        .section-title{
            text-align:center;font-size:clamp(1.5rem, 3.5vw, 2rem);
            font-weight:700;margin-bottom:12px;color:#111827;letter-spacing:-0.01em;
            overflow-wrap:anywhere;
        }
        .section-sub{
            text-align:center;color:#6B7280;font-size:1.05rem;
            max-width:560px;margin:0 auto 40px;padding:0 8px;
        }

        .workflow-section,.features-section{max-width:1120px;margin:0 auto 80px;padding:0 24px}
        .workflow-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
        .step-card{
            background:#fff;border:1px solid #E5E7EB;border-radius:16px;padding:28px;
            box-shadow:0 2px 4px rgba(0,0,0,0.02);transition:all .15s ease;
        }
        .step-card:hover{border-color:#93C5FD;transform:translateY(-2px);box-shadow:0 10px 20px -8px rgba(37,99,235,0.12)}
        .step-num{font-size:0.8rem;font-weight:700;color:#2563EB;margin-bottom:12px;letter-spacing:0.04em}
        .step-card h3{font-size:1.15rem;font-weight:600;margin-bottom:10px;color:#111827}
        .step-card p{color:#4B5563;font-size:0.95rem;line-height:1.65}

        .features-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
        .feature-card{
            background:#fff;border:1px solid #E5E7EB;border-radius:16px;
            padding:28px;display:flex;flex-direction:column;transition:all .15s ease;
            min-height:100%;
        }
        .feature-card:hover{border-color:#CBD5E1;box-shadow:0 12px 24px -12px rgba(15,23,42,0.1)}
        .feat-icon{
            width:44px;height:44px;border-radius:12px;background:#EFF6FF;color:#2563EB;
            display:flex;align-items:center;justify-content:center;font-size:0.95rem;
            margin-bottom:16px;font-weight:700;
        }
        .feature-card h3{font-size:1.2rem;font-weight:600;margin-bottom:10px;color:#111827}
        .feature-card p{color:#4B5563;font-size:0.98rem;line-height:1.65}

        /* Soft closing band — light wash, no hard dark cut (NotebookLM-inspired) */
        .trust-section{
            position:relative;
            color:#0F172A;
            text-align:center;
            padding:88px 24px 72px;
            overflow:hidden;
            background:
                radial-gradient(ellipse 70% 55% at 50% 0%, rgba(37,99,235,0.10), transparent 68%),
                radial-gradient(ellipse 42% 48% at 12% 88%, rgba(99,102,241,0.07), transparent 62%),
                radial-gradient(ellipse 40% 46% at 88% 78%, rgba(56,189,248,0.07), transparent 60%),
                linear-gradient(180deg, #F9FAFB 0%, #F4F7FC 28%, #EEF3FB 72%, #E9EFF8 100%);
        }
        .trust-section::before{
            content:"";
            position:absolute;left:50%;top:18%;
            width:min(720px, 92vw);height:280px;
            transform:translateX(-50%);
            background:radial-gradient(ellipse at center, rgba(255,255,255,0.72), transparent 70%);
            pointer-events:none;
        }
        .trust-inner{position:relative;z-index:1;max-width:760px;margin:0 auto}
        .trust-inner h2{
            font-size:clamp(1.6rem, 4vw, 2.25rem);font-weight:700;
            margin-bottom:16px;letter-spacing:-0.02em;overflow-wrap:anywhere;color:#0F172A;
        }
        .trust-inner > p{color:#64748B;font-size:1.05rem;margin-bottom:32px;line-height:1.7}
        .tags-row{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:36px}
        .tag{
            background:rgba(255,255,255,0.78);
            border:1px solid rgba(148,163,184,0.28);
            box-shadow:0 1px 2px rgba(15,23,42,0.04);
            backdrop-filter:blur(8px);
            padding:8px 14px;border-radius:999px;
            font-size:0.9rem;color:#334155;display:inline-flex;align-items:center;gap:8px;
        }
        .tag span{color:#2563EB;font-weight:700}
        .trust-section .btn-primary{
            box-shadow:0 8px 22px rgba(37,99,235,0.18);
        }

        .footer{
            text-align:center;padding:28px 20px;color:#94A3B8;font-size:0.88rem;
            background:#E9EFF8;
            border-top:1px solid rgba(15,23,42,0.05);
        }
        .footer a{color:#64748B}
        .footer a:hover{color:#2563EB}

        @media (max-width:900px){
            .shot-grid{grid-template-columns:1fr;max-width:520px}
            .workflow-grid,.features-grid{grid-template-columns:1fr}
        }
        @media (max-width:768px){
            .nav{padding:12px 16px}
            .links a:not(.cta){display:none}
            .hero{padding:36px 16px 28px}
            .demo-container,.workflow-section,.features-section,.shot-grid{padding-left:16px;padding-right:16px}
            .demo-container{margin-bottom:48px}
            .workflow-section,.features-section{margin-bottom:56px}
            .feature-card,.step-card{padding:22px}
            .trust-section{padding:64px 16px 56px}
            .btn{width:100%;max-width:320px}
            .cta-row{flex-direction:column;align-items:center}
        }
    </style>
</head>
<body class="page-home marketing-home">
    <nav class="nav" aria-label="页面导航">
        <div class="brand">
            <a href="/" aria-label="LearnFlux 首页">
                <img src="/static/icon/learnflux-icon-256.png" width="32" height="32" alt="">
                <span class="brand-text">LearnFlux</span>
            </a>
        </div>
        <div class="links">
            <a href="#workflow">工作流</a>
            <a href="#features">产品功能</a>
            <a href="#trust">隐私与部署</a>
            <a href="https://github.com/zhangxun-ai/LearnFlux" target="_blank" rel="noopener">GitHub</a>
            <a class="cta" href="/add_task_by_web">开始深度学习</a>
        </div>
    </nav>

    <header class="hero">
        <div class="eyebrow">专为深度学习者与研究员打造</div>
        <h1>把海量音视频与文档，<br>变成可复习的<em>学习资产</em>。</h1>
        <p class="sub">支持本地文件与网页链接。精准转写、AI 深度解读、时间轴联动与边播边学，帮你把碎片信息沉淀成可检索、可复习的私人知识库。</p>
        <div class="cta-row">
            <a class="btn btn-primary" href="/add_task_by_web">开始深度学习</a>
            <a class="btn btn-ghost" href="/add_task_by_web#local-video-study">本地视频学习</a>
        </div>
    </header>

    <div class="demo-container">
        <div class="demo-mockup">
            <div class="mockup-header" aria-hidden="true">
                <div class="mockup-dot red"></div>
                <div class="mockup-dot yellow"></div>
                <div class="mockup-dot green"></div>
            </div>
            <img
                src="/static/images/landing/01-single-study.png"
                width="1440"
                height="900"
                alt="LearnFlux 单篇深度学习工作台：粘贴链接、本地文件或粘贴文字即可开始解析"
                loading="eager"
                decoding="async"
            >
        </div>
        <p class="demo-caption">单篇深度学习工作台 · 链接 / 本地文件 / 粘贴文字一站导入</p>
    </div>

    <div class="shot-grid" aria-label="产品界面预览">
        <a class="shot-card" href="/collections">
            <img src="/static/images/landing/02-collections.png" width="960" height="600" alt="系列深度学习专题合集界面" loading="lazy" decoding="async">
            <p>系列专题 · 按课程结构系统掌握</p>
        </a>
        <a class="shot-card" href="/study">
            <img src="/static/images/landing/03-study-player.png" width="960" height="600" alt="边播边学本地视频学习入口" loading="lazy" decoding="async">
            <p>边播边学 · 本地音视频即选即播</p>
        </a>
        <a class="shot-card" href="/visual-learning">
            <img src="/static/images/landing/04-visual-learning.png" width="960" height="600" alt="可视化图解生成界面" loading="lazy" decoding="async">
            <p>图解生成 · 把抽象逻辑变成可视卡片</p>
        </a>
    </div>

    <section class="workflow-section" id="workflow">
        <h2 class="section-title">核心工作流</h2>
        <p class="section-sub">三步，把信息洪流变成结构化知识</p>
        <div class="workflow-grid">
            <div class="step-card">
                <div class="step-num">STEP 1</div>
                <h3>汇集与精准转写</h3>
                <p>粘贴链接或上传本地音视频，生成高准确度逐字稿。支持 Bilibili、YouTube、播客、本地文件与图文文档。</p>
            </div>
            <div class="step-card">
                <div class="step-num">STEP 2</div>
                <h3>深度解读与边播边学</h3>
                <p>AI 提取框架与核心观点。播放器与文稿分屏同步，点击任意一句即可跳回上下文，边看边记不丢焦。</p>
            </div>
            <div class="step-card">
                <div class="step-num">STEP 3</div>
                <h3>知识沉淀与连接</h3>
                <p>按专题组织学习资产，把高价值内容同步到 Obsidian，形成可长期复用的本地知识库。</p>
            </div>
        </div>
    </section>

    <section class="features-section" id="features">
        <h2 class="section-title">高价值特性</h2>
        <p class="section-sub">不止转录，而是完整的学习与洞察闭环</p>
        <div class="features-grid">
            <a class="feature-card" href="/add_task_by_web">
                <div class="feat-icon">单</div>
                <h3>单篇深度学习</h3>
                <p>链接、本地文件、粘贴文字都能入口统一处理。转写、校准、摘要与阅读视图一次完成。</p>
            </a>
            <a class="feature-card" href="/add_task_by_web#local-video-study">
                <div class="feat-icon">播</div>
                <h3>边播边学 / 本地视频学习</h3>
                <p>本地音视频选中即播，解析在后台继续。时间轴与文稿联动，适合长课、播客与会议回放。</p>
            </a>
            <a class="feature-card" href="/collections">
                <div class="feat-icon">系</div>
                <h3>系列深度学习</h3>
                <p>按合集顺序解析完整课程与专题，生成全局方法论，把碎片学习升级为系统掌握。</p>
            </a>
            <a class="feature-card" href="/visual-learning">
                <div class="feat-icon">图</div>
                <h3>可视化图解生成</h3>
                <p>把冗长逻辑关系转成直观图文卡片，降低认知负荷，方便复习与分享。</p>
            </a>
            <a class="feature-card" href="/reading">
                <div class="feat-icon">流</div>
                <h3>沉浸式心流空间</h3>
                <p>免打扰阅读与写作环境，配合 AI 润色，让你从信息噪音里回到思考本身。</p>
            </a>
            <a class="feature-card" href="/flywheel">
                <div class="feat-icon">IP</div>
                <h3>内容趋势与选题机会</h3>
                <p>拆解社媒高赞图文与对标账号逻辑，辅助创作者在 IP 对标工作流内发现选题机会。</p>
            </a>
        </div>
    </section>

    <section class="trust-section" id="trust">
        <div class="trust-inner">
            <h2>本地优先，数据由你掌控。</h2>
            <p>LearnFlux 按本地优先架构设计：学习资产可落在你自己的环境里，也支持自托管部署与 Obsidian 同步。云端转写仅在你主动选择时发生。</p>
            <div class="tags-row">
                <div class="tag"><span>✓</span> 本地优先存储</div>
                <div class="tag"><span>✓</span> 支持自托管部署</div>
                <div class="tag"><span>✓</span> 同步至 Obsidian</div>
                <div class="tag"><span>✓</span> 云端转写按需启用</div>
            </div>
            <a class="btn btn-primary" href="/add_task_by_web">开始深度学习</a>
        </div>
    </section>

    <footer class="footer">
        Powered by <a href="https://github.com/zhangxun-ai/LearnFlux" target="_blank" rel="noopener">LearnFlux</a> · Open Source
    </footer>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home():
    """Marketing landing page for SEO and first-time product orientation."""
    static_dir = get_static_dir()
    version_files = [
        static_dir / "icon" / "learnflux-icon-256.png",
        static_dir / "images" / "landing" / "01-single-study.png",
        static_dir / "images" / "landing" / "02-collections.png",
        static_dir / "images" / "landing" / "03-study-player.png",
        static_dir / "images" / "landing" / "04-visual-learning.png",
        # Keep ui-features.js in the version set so shell-route asset contracts
        # that scan views.py still observe the shared feature-config digest.
        static_dir / "js" / "ui-features.js",
    ]
    version = str(max(
        (path.stat().st_mtime_ns for path in version_files if path.exists()),
        default=0,
    ))
    return HTMLResponse(
        content=_HOME_HTML.replace("__ASSET_VERSION__", version),
        headers={"Cache-Control": "no-cache"},
    )


def resolve_export_file_path(cache_dir: str, export_type: str) -> Optional[Path]:
    """根据导出类型解析缓存文件路径.

    统一三个导出入口(raw / page / export)的文件定位逻辑,避免重复。
    transcript 类型优先 FunASR JSON,缺失时降级到 CapsWriter TXT。

    Args:
        cache_dir: 缓存目录
        export_type: 导出类型(calibrated / summary / transcript)

    Returns:
        Path: 对应的文件路径;若 export_type 不支持则返回 None
        （注意:返回的 Path 不保证存在,调用方需自行 .exists() 判断）
    """
    base = Path(cache_dir)
    if export_type == "calibrated":
        return base / "llm_calibrated.txt"
    if export_type == "summary":
        return base / "llm_summary.txt"
    if export_type == "comment_insight":
        return base / "comment_insight.txt"
    if export_type == "transcript":
        funasr_file = base / "transcript_funasr.json"
        capswriter_file = base / "transcript_capswriter.txt"
        return funasr_file if funasr_file.exists() else capswriter_file
    return None


def get_export_scope_sections(scope: str) -> tuple[str, ...]:
    """Return export section types for a user-facing export scope."""
    return _EXPORT_SCOPE_SECTIONS.get(scope, _EXPORT_SCOPE_SECTIONS["full"])


def _build_text_metadata_header(view_data: Dict[str, Any], export_type: str) -> str:
    """生成纯文本导出的 YAML front matter 风格元数据头.

    Args:
        view_data: 页面数据字典
        export_type: 导出类型（calibrated/summary/transcript）

    Returns:
        包含元数据的字符串，以 '---' 分隔
    """
    title = view_data.get("title", "未命名")
    platform = view_data.get("platform", "unknown")
    source_url = view_data.get("url", "")
    content_type_cn = _EXPORT_TYPE_LABELS.get(
        export_type, _EXPORT_SCOPE_LABELS.get(export_type, export_type)
    )
    from ...utils.timeutil.timezone_helper import get_configured_timezone
    export_date = datetime.now(get_configured_timezone()).strftime("%Y-%m-%d")

    lines = [
        "---",
        f"Title: {title}",
        f"Platform: {platform}",
        f"Type: {content_type_cn}",
    ]
    if source_url:
        lines.append(f"Source: {source_url}")
    lines.append(f"Export-Date: {export_date}")
    lines.append("---")
    lines.append("")  # 元数据与正文之间的空行

    return "\n".join(lines)


def _build_metadata_headers(view_data: Dict[str, Any], export_type: str) -> dict:
    """生成纯文本导出的 HTTP 自定义响应头.

    HTTP 响应头仅支持 Latin-1 编码，因此对包含非 ASCII 字符的值
    使用 RFC 5987 的 UTF-8'' 编码格式。

    Args:
        view_data: 页面数据字典
        export_type: 导出类型（calibrated/summary/transcript）

    Returns:
        包含自定义响应头的字典
    """
    from urllib.parse import quote

    type_map = {
        "calibrated": "calibrated",
        "summary": "summary",
        "comment_insight": "comment_insight",
        "transcript": "transcript",
    }

    title = view_data.get("title", "未命名")
    platform = view_data.get("platform", "unknown")
    source_url = view_data.get("url", "")
    content_type = type_map.get(export_type, export_type)

    def _safe_header_value(value: str) -> str:
        """将非 ASCII 值进行 URL 编码，确保 HTTP 头兼容性."""
        try:
            value.encode("latin-1")
            return value
        except UnicodeEncodeError:
            return quote(value, safe="")

    headers = {
        "X-Document-Title": _safe_header_value(title),
        "X-Platform": _safe_header_value(platform),
        "X-Content-Type": content_type,
    }
    if source_url:
        headers["X-Source-URL"] = _safe_header_value(source_url)

    return headers


def _build_page_html(
    view_data: Dict[str, Any], export_type: str, body_html: str
) -> str:
    """生成用于 ?page= 导出的极简 HTML 页面.

    页面包含完整的 meta 标签（Open Graph 等），适合爬虫抓取，
    同时提供干净的阅读体验。

    Args:
        view_data: 页面数据字典
        export_type: 导出类型（calibrated/summary/transcript）
        body_html: 已渲染的 HTML 正文内容

    Returns:
        完整的 HTML 字符串
    """
    import html as html_module

    title = view_data.get("title", "未命名")
    platform = view_data.get("platform", "unknown")
    content_type_cn = _EXPORT_SECTION_LABELS.get(export_type, export_type)
    source_url = view_data.get("url", "")

    # HTML 转义防止 XSS
    safe_title = html_module.escape(title)
    safe_platform = html_module.escape(platform)
    safe_content_type = html_module.escape(content_type_cn)
    safe_source_url = html_module.escape(source_url)

    page_title = f"{safe_title} - {safe_content_type}"
    og_desc = f"{safe_title} 的{safe_content_type}（{safe_platform}）"

    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <meta name="description" content="{og_desc}">
    <meta name="robots" content="noindex">
    <meta name="theme-color" content="#667eea">
    <meta property="og:title" content="{page_title}">
    <meta property="og:description" content="{og_desc}">
    <meta property="og:type" content="article">
    <meta property="og:locale" content="zh_CN">
    <meta property="og:site_name" content="LearnFlux">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
            line-height: 1.8;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 32px 20px;
            background: #fafafa;
        }}
        article {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 8px rgba(0,0,0,0.06);
            padding: 40px;
        }}
        h1 {{
            font-size: 1.5rem;
            margin: 0 0 8px 0;
            line-height: 1.4;
        }}
        .meta {{
            color: #6b7280;
            font-size: 0.875rem;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid #e5e7eb;
        }}
        .meta a {{ color: #667eea; text-decoration: none; }}
        .meta a:hover {{ text-decoration: underline; }}
        .content {{ font-size: 1rem; }}
        .content h1 {{ font-size: 1.3rem; }}
        .content h2 {{ font-size: 1.15rem; }}
        .content h3 {{ font-size: 1.05rem; }}
        .content p {{ margin: 0.8em 0; }}
        .content blockquote {{
            border-left: 3px solid #667eea;
            margin: 1em 0;
            padding: 0.5em 1em;
            color: #555;
            background: #f8f9ff;
        }}
        .content pre {{
            background: #f3f4f6;
            padding: 12px 16px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.9rem;
        }}
        .content table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        .content th, .content td {{
            border: 1px solid #e5e7eb;
            padding: 8px 12px;
            text-align: left;
        }}
        .content th {{ background: #f9fafb; }}
    </style>
</head>
<body>
    <article>
        <h1>{safe_title}</h1>
        <div class="meta">
            <span>{safe_content_type}</span>
            {f' · <span>{safe_platform}</span>' if platform != 'unknown' else ''}
            {f' · <a href="{safe_source_url}" rel="noopener">原始链接</a>' if source_url else ''}
        </div>
        <div class="content">
            {body_html}
        </div>
    </article>
</body>
</html>"""


def handle_page_export(view_data: Dict[str, Any], export_type: str) -> Response:
    """处理 ?page= 模式导出请求，返回完整 HTML 页面.

    与 ?raw= 返回纯文本不同，此模式返回包含完整 meta 标签的 HTML 页面，
    正文经过 Markdown 渲染，适合爬虫抓取和浏览器阅读。

    Args:
        view_data: 页面数据字典
        export_type: 导出类型（calibrated/summary/transcript）

    Returns:
        HTMLResponse 包含完整 HTML 页面
    """
    # 1. 检查任务状态（复用 raw export 的状态检查逻辑）
    status = view_data.get("status")

    if status in ["queued", "processing"]:
        return HTMLResponse(
            content="<html><body><p>校对文本正在生成中，请稍后再试...</p></body></html>",
            status_code=202,
        )
    if status == "file_cleaned":
        return HTMLResponse(
            content="<html><body><p>该文件已被清理</p></body></html>",
            status_code=410,
        )
    if status == "failed":
        return HTMLResponse(
            content="<html><body><p>任务处理失败</p></body></html>",
            status_code=500,
        )
    if status != "success":
        return HTMLResponse(
            content=f"<html><body><p>任务状态异常: {status}</p></body></html>",
            status_code=400,
        )

    # 2. 获取缓存目录
    cache_dir = view_data.get("cache_dir")
    if not cache_dir or not os.path.exists(cache_dir):
        return HTMLResponse(
            content="<html><body><p>缓存文件不存在</p></body></html>",
            status_code=404,
        )

    # 3. 根据导出类型确定文件路径
    file_path = resolve_export_file_path(cache_dir, export_type)
    if file_path is None:
        return HTMLResponse(
            content="<html><body><p>不支持的导出类型</p></body></html>",
            status_code=400,
        )

    # 4. 检查文件存在
    if not file_path or not file_path.exists():
        content_type_cn = {
            "calibrated": "校对文本",
            "summary": "总结文本",
            "comment_insight": "高赞评论洞察",
            "transcript": "原始转录",
        }.get(export_type, export_type)
        return HTMLResponse(
            content=f"<html><body><p>{content_type_cn}文件不存在</p></body></html>",
            status_code=404,
        )

    # 5. 读取文件并渲染
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("读取文件失败: %s, 错误: %s", file_path, exc)
        return HTMLResponse(
            content="<html><body><p>读取文件失败</p></body></html>",
            status_code=500,
        )

    # 6. 将内容渲染为 HTML（Markdown -> HTML）
    body_html = render_markdown_to_html(content)

    # 7. 构建完整 HTML 页面
    vt = view_data.get("view_token", "unknown")[:20]
    logger.info(f"Page export: type={export_type}, view_token={vt}")

    page_html = _build_page_html(view_data, export_type, body_html)

    # 构建 HTTP 自定义响应头
    custom_headers = _build_metadata_headers(view_data, export_type)

    return HTMLResponse(
        content=page_html,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Robots-Tag": "noindex",
            **custom_headers,
        },
    )


def sanitize_filename(filename: str) -> str:
    """
    清理文件名中的非法字符

    Args:
        filename: 原始文件名

    Returns:
        str: 清理后的安全文件名
    """
    # 移除或替换 Windows 和 Linux 中的非法字符
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")

    # 移除控制字符
    filename = "".join(char for char in filename if ord(char) >= 32)

    # 移除首尾空格和点
    filename = filename.strip(". ")

    # 如果文件名为空，返回默认值
    if not filename:
        filename = "未命名"

    return filename


def generate_download_filename(
    title: str, platform: str, content_type: str, extension: str = "txt"
) -> str:
    """
    生成下载文件名：视频标题-校对文本-平台.txt

    Args:
        title: 视频标题
        platform: 平台名称（youtube/bilibili/douyin等）
        content_type: 内容类型（calibrated/summary/transcript/analysis/full）
        extension: 文件扩展名，不带点

    Returns:
        str: 格式化的文件名
    """
    # 清理标题中的非法字符
    safe_title = sanitize_filename(title)

    # 内容类型映射
    type_map = {
        **_EXPORT_TYPE_LABELS,
        **_EXPORT_SCOPE_LABELS,
    }

    # 平台名称映射
    platform_map = {
        "youtube": "YouTube",
        "bilibili": "哔哩哔哩",
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "xiaoyuzhou": "小宇宙",
        "generic": "自定义",
    }

    content_name = type_map.get(content_type, content_type)
    platform_name = platform_map.get(platform, platform)

    # 限制标题长度，避免文件名过长
    max_title_length = 50
    if len(safe_title) > max_title_length:
        safe_title = safe_title[:max_title_length] + "..."

    safe_extension = sanitize_filename(extension).lstrip(".") or "txt"
    return f"{safe_title}-{content_name}-{platform_name}.{safe_extension}"


def _normalize_export_content(export_type: str, content: str) -> str:
    if export_type in {"summary", "comment_insight"}:
        return normalize_markdown_text(content)
    return content


def build_export_bundle_markdown(view_data: Dict[str, Any], scope: str) -> str:
    """Build a scoped Markdown export from cached section files."""
    cache_dir = view_data.get("cache_dir")
    if not cache_dir or not os.path.exists(cache_dir):
        return ""

    sections = []
    for export_type in get_export_scope_sections(scope):
        file_path = resolve_export_file_path(cache_dir, export_type)
        if not file_path or not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("读取导出分段失败: %s, 错误: %s", file_path, exc)
            continue

        content = _normalize_export_content(export_type, content).strip()
        if not content:
            continue

        label = _EXPORT_SECTION_LABELS.get(export_type, export_type)
        sections.append((label, content))

    if not sections:
        return ""

    title = str(view_data.get("title") or "未命名").strip() or "未命名"
    lines = [f"# {title}", ""]
    for label, content in sections:
        lines.extend([f"## {label}", "", content, ""])
    return "\n".join(lines).rstrip() + "\n"


def handle_raw_export(view_data: Dict[str, Any], export_type: str) -> Response:
    """
    处理 Raw 模式导出请求（GitHub Raw 模式）

    Args:
        view_data: 页面数据
        export_type: 导出类型（calibrated/summary/transcript）

    Returns:
        Response: 纯文本响应
    """
    # 1. 检查任务状态
    status = view_data.get("status")

    if status in ["queued", "processing"]:
        return Response(
            content="⏳ 校对文本正在生成中，请稍后再试...\n\n请刷新页面或稍后访问此链接。",
            media_type="text/plain; charset=utf-8",
            status_code=202,
        )

    if status == "file_cleaned":
        return Response(
            content="❌ 该文件已被清理\n\n如需重新获取，请重新提交转录任务。",
            media_type="text/plain; charset=utf-8",
            status_code=410,
        )

    if status == "failed":
        return Response(
            content="❌ 任务处理失败\n\n请重新提交转录任务。",
            media_type="text/plain; charset=utf-8",
            status_code=500,
        )

    if status != "success":
        return Response(
            content=f"❌ 任务状态异常: {status}",
            media_type="text/plain; charset=utf-8",
            status_code=400,
        )

    # 2. 获取缓存目录
    cache_dir = view_data.get("cache_dir")
    if not cache_dir or not os.path.exists(cache_dir):
        return Response(
            content="❌ 缓存文件不存在\n\n该文件可能已被清理。",
            media_type="text/plain; charset=utf-8",
            status_code=404,
        )

    # 3. 根据导出类型确定文件路径（优先 FunASR JSON，降级 CapsWriter TXT）
    file_path = resolve_export_file_path(cache_dir, export_type)
    if file_path is None:
        return Response(
            content=f"❌ 不支持的导出类型: {export_type}\n\n支持的类型: calibrated, summary, comment_insight, transcript",
            media_type="text/plain; charset=utf-8",
            status_code=400,
        )

    # 4. 检查文件是否存在
    if not file_path or not file_path.exists():
        content_type_cn = {
            "calibrated": "校对文本",
            "summary": "总结文本",
            "comment_insight": "高赞评论洞察",
            "transcript": "原始转录",
        }.get(export_type, export_type)

        return Response(
            content=f"❌ {content_type_cn}文件不存在\n\n该任务可能未启用相关功能。",
            media_type="text/plain; charset=utf-8",
            status_code=404,
        )

    # 5. 读取文件内容
    try:
        content = file_path.read_text(encoding="utf-8")
        content = _normalize_export_content(export_type, content)
    except Exception as exc:
        logger.error("读取文件失败: %s, 错误: %s", file_path, exc)
        return Response(
            content="❌ 读取文件失败，请稍后重试",
            media_type="text/plain; charset=utf-8",
            status_code=500,
        )

    # 6. 返回纯文本响应，附带元数据头
    vt = view_data.get("view_token", "unknown")[:20]
    logger.info(f"Raw export: type={export_type}, view_token={vt}")

    # 在正文顶部添加 YAML front matter 元数据
    metadata_header = _build_text_metadata_header(view_data, export_type)
    content_with_metadata = metadata_header + content

    # 构建 HTTP 自定义响应头
    custom_headers = _build_metadata_headers(view_data, export_type)

    # 明确设置响应头，提高外部 AI 工具 (Gemini 等) URL fetcher 的兼容性
    content_bytes = content_with_metadata.encode("utf-8")
    return Response(
        content=content_bytes,
        media_type="text/plain",
        headers={
            "Content-Length": str(len(content_bytes)),
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex",
            **custom_headers,
        },
    )


@router.get("/add_task_by_web", response_class=HTMLResponse)
async def add_task_by_web(request: Request):
    """Web任务添加页面"""
    try:
        index_file = static_dir / "index.html"
        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            # 资源版本号：取关键静态文件的最新修改时间。文件一变版本即变，
            # 浏览器据此强制拉取新的 app.js / css，避免缓存旧前端导致的 UI 错乱。
            asset_files = [
                index_file,
                static_dir / "js" / "app.js",
                static_dir / "css" / "styles.css",
                static_dir / "css" / "workbench.css",
                static_dir / "css" / "app-shell.css",
                static_dir / "css" / "product-linear.css",
                static_dir / "css" / "home-linear.css",
                static_dir / "css" / "editorial.css",
                static_dir / "js" / "app-shell.js",
                static_dir / "js" / "ui-features.js",
                static_dir / "js" / "pwa-register.js",
            ]
            version = str(int(max(
                (f.stat().st_mtime for f in asset_files if f.exists()),
                default=0,
            )))
            content = content.replace("__ASSET_VERSION__", version)
            # HTML 本身不缓存，确保每次都拿到最新的资源版本号
            return HTMLResponse(content=content, headers={"Cache-Control": "no-cache"})
        else:
            logger.error("Web任务添加页面文件不存在: %s", index_file)
            return HTMLResponse(
                content="<h1>页面未找到</h1><p>请确保 index.html 文件存在于 static 目录中。</p>",
                status_code=404,
            )
    except Exception as exc:
        logger.exception("访问Web任务添加页面异常: %s", exc)
        raise HTTPException(status_code=500, detail="访问页面失败，请稍后重试")


def _render_study_page(
    *,
    page_mode: str,
    view_token: str = "",
    collection_id: str = "",
    source_id: str = "",
) -> HTMLResponse:
    page = static_dir / "study.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="study page not found")

    asset_files = [
        page,
        static_dir / "css" / "study.css",
        static_dir / "css" / "visual-learning.css",
        static_dir / "js" / "study.js",
        static_dir / "js" / "study-player-runtime.js",
        static_dir / "js" / "visual-learning.js",
        static_dir / "css" / "editorial.css",
        static_dir / "css" / "app-shell.css",
        static_dir / "css" / "product-linear.css",
        static_dir / "css" / "product-linear-core.css",
        static_dir / "js" / "app-shell.js",
        static_dir / "js" / "ui-features.js",
        static_dir / "js" / "pwa-register.js",
    ]
    version = str(max(
        (f.stat().st_mtime_ns for f in asset_files if f.exists()),
        default=0,
    ))
    content = (
        page.read_text(encoding="utf-8")
        .replace("__VIEW_TOKEN__", view_token)
        .replace("__COLLECTION_ID__", collection_id)
        .replace("__SOURCE_ID__", source_id)
        .replace("__PAGE_MODE__", page_mode)
        .replace("__ASSET_VERSION__", version)
    )
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache"})


@router.get("/study", response_class=HTMLResponse, include_in_schema=False)
async def study_library_page():
    """统一音视频学习内容选择页。"""
    return _render_study_page(page_mode="library")


@router.get("/study/collections/{collection_id}/sources/{source_id}", response_class=HTMLResponse, include_in_schema=False)
async def study_collection_page(collection_id: str, source_id: str):
    """带明确合集与分集上下文的统一学习播放器。"""
    return _render_study_page(
        page_mode="collection",
        collection_id=collection_id,
        source_id=source_id,
    )


@router.get("/study/{view_token}", response_class=HTMLResponse, include_in_schema=False)
async def study_page(view_token: str):
    """单篇音视频学习页面。"""
    view_data = cache_manager.get_view_data_by_token(view_token)
    if not view_data:
        raise HTTPException(status_code=404, detail="study page not found")
    return _render_study_page(page_mode="single", view_token=view_token)


@router.get("/export/{view_token}/{export_type}")
async def export_content(view_token: str, export_type: str, request: Request):
    """
    导出文件内容

    Args:
        view_token: 查看token
        export_type: 导出类型 (calibrated/summary/transcript)

    Returns:
        FileResponse: 文件响应
    """
    try:
        # 获取查看页面数据
        view_data = cache_manager.get_view_data_by_token(view_token)
        if not view_data:
            return Response(
                content="❌ 页面不存在\n\nview_token 无效或已过期。",
                media_type="text/plain; charset=utf-8",
                status_code=404,
            )

        cache_dir = view_data.get("cache_dir")
        if not cache_dir or not os.path.exists(cache_dir):
            return Response(
                content="❌ 缓存文件不存在\n\n该文件可能已被清理。",
                media_type="text/plain; charset=utf-8",
                status_code=404,
            )

        if export_type == "bundle":
            scope = request.query_params.get("scope", "full")
            content = build_export_bundle_markdown(view_data, scope)
            if not content:
                return Response(
                    content="❌ 没有可导出的内容\n\n该任务可能未生成所选内容。",
                    media_type="text/plain; charset=utf-8",
                    status_code=404,
                )

            title = view_data.get("title", "未命名")
            platform = view_data.get("platform", "unknown")
            content_type = scope if scope in _EXPORT_SCOPE_LABELS else "full"
            filename = generate_download_filename(title, platform, content_type, "md")
            from urllib.parse import quote

            encoded_filename = quote(filename)
            custom_headers = _build_metadata_headers(view_data, content_type)
            logger.info(
                "导出组合文件: scope=%s, 文件名: %s, view_token: %s",
                content_type,
                filename,
                view_data.get("view_token", "unknown")[:20],
            )

            return Response(
                content=content,
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                    "X-Content-Type-Options": "nosniff",
                    **custom_headers,
                },
            )

        file_path = resolve_export_file_path(cache_dir, export_type)
        if file_path is None:
            return Response(
                content=f"❌ 不支持的导出类型: {export_type}\n\n支持的类型: calibrated, summary, comment_insight, transcript",
                media_type="text/plain; charset=utf-8",
                status_code=400,
            )

        if not file_path or not file_path.exists():
            content_type_cn = {
                "calibrated": "校对文本",
                "summary": "总结文本",
                "comment_insight": "高赞评论洞察",
                "transcript": "原始转录",
            }.get(export_type, export_type)
            return Response(
                content=f"❌ {content_type_cn}文件不存在\n\n该任务可能未启用相关功能。",
                media_type="text/plain; charset=utf-8",
                status_code=404,
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            content = _normalize_export_content(export_type, content)
        except Exception as exc:
            logger.error("读取文件失败: %s, 错误: %s", file_path, exc)
            return Response(
                content="❌ 读取文件失败，请稍后重试",
                media_type="text/plain; charset=utf-8",
                status_code=500,
            )

        title = view_data.get("title", "未命名")
        platform = view_data.get("platform", "unknown")
        filename = generate_download_filename(title, platform, export_type)
        from urllib.parse import quote

        encoded_filename = quote(filename)

        # 在正文顶部添加 YAML front matter 元数据
        metadata_header = _build_text_metadata_header(view_data, export_type)
        content_with_metadata = metadata_header + content

        # 构建 HTTP 自定义响应头
        custom_headers = _build_metadata_headers(view_data, export_type)

        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
            "X-Content-Type-Options": "nosniff",
            **custom_headers,
        }

        logger.info(
            "导出文件: %s, 文件名: %s, view_token: %s",
            export_type,
            filename,
            view_data.get("view_token", "unknown")[:20],
        )

        return Response(
            content=content_with_metadata,
            media_type="text/plain; charset=utf-8",
            headers=headers,
        )

    except Exception as exc:
        logger.exception("导出文件异常: %s", exc)
        return Response(
            content="❌ 导出失败，请稍后重试",
            media_type="text/plain; charset=utf-8",
            status_code=500,
        )


@router.get("/view/{view_token}/source-file")
async def view_source_file(view_token: str):
    view_data = cache_manager.get_view_data_by_token(view_token)
    if not view_data:
        raise HTTPException(status_code=404, detail="view_token 无效或已过期")
    file_path = _local_source_file_path(view_data)
    if not file_path:
        raise HTTPException(status_code=404, detail="源视频未保存或已清理")
    filename = os.path.basename(str(view_data.get("title") or file_path.name))
    if not os.path.splitext(filename)[1]:
        filename = file_path.name
    return FileResponse(path=str(file_path), filename=filename or file_path.name)


@router.post("/view/{view_token}/source-file/reveal")
async def reveal_view_source_file(view_token: str, request: Request):
    if not _is_local_reveal_request(request):
        raise HTTPException(status_code=403, detail="仅允许从本机打开本地源文件")
    view_data = cache_manager.get_view_data_by_token(view_token)
    if not view_data:
        raise HTTPException(status_code=404, detail="view_token 无效或已过期")
    file_path = _local_source_file_path(view_data)
    if not file_path:
        raise HTTPException(status_code=404, detail="源视频未保存或已清理")
    try:
        await run_in_threadpool(_reveal_path_in_file_manager, str(file_path))
    except OSError as exc:
        logger.warning(f"reveal view source failed: {exc}")
        raise HTTPException(status_code=500, detail="打开本地目录失败")
    return {
        "code": 200,
        "message": "已打开源文件所在目录",
        "data": {"filename": file_path.name},
    }


def _is_local_reveal_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _reveal_path_in_file_manager(file_path: str) -> None:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
        return
    if os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{path}"])
        return
    target = path.parent if path.is_file() else path
    subprocess.Popen(["xdg-open", str(target)])


@router.get("/view/{view_token}", response_class=HTMLResponse)
async def view_transcript(
    view_token: str,
    request: Request,
    raw: Optional[str] = None,
    page: Optional[str] = None,
):
    try:
        view_data = cache_manager.get_view_data_by_token(view_token)
        if not view_data:
            if raw:
                return Response(
                    content="❌ 页面不存在\n\nview_token 无效或已过期。",
                    media_type="text/plain; charset=utf-8",
                    status_code=404,
                )
            elif page:
                return HTMLResponse(
                    content="<html><body><p>页面不存在</p></body></html>",
                    status_code=404,
                )
            else:
                return _no_store(
                    templates.TemplateResponse(
                        "error.html",
                        {
                            "request": request,
                            "message": "view_token 无效或已过期",
                        },
                    )
                )

        # 如果请求导出原始文件（GitHub Raw 模式）
        if raw:
            return handle_raw_export(view_data, raw)

        # 如果请求 HTML 页面导出（爬虫友好模式）
        if page:
            return handle_page_export(view_data, page)

        _decorate_view_timing(view_data)
        _decorate_source_link(view_data)
        _decorate_collection_display_title(view_data)
        _decorate_title_and_tags(view_data)

        if view_data["status"] == "processing":
            is_document = _is_local_document_view(view_data)
            if is_document and not view_data.get("title"):
                view_data["title"] = _local_url_filename(view_data) or "本地文档"
            return _no_store(
                templates.TemplateResponse(
                    "processing.html",
                    {
                        "request": request,
                        **view_data,
                        "page_title": view_data.get("title") or (
                            "文档解析处理中" if is_document else "转录处理中"
                        ),
                        "processing_heading": (
                            "文档解析处理中" if is_document else "转录处理中"
                        ),
                        "processing_subtitle": (
                            "完成后会自动打开文档解读结果页，无需手动刷新。"
                            if is_document
                            else "完成后会自动打开结果页，无需手动刷新。"
                        ),
                    },
                )
            )
        if view_data["status"] == "failed":
            return _no_store(
                templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "message": view_data.get("error_message", "任务处理失败"),
                        **view_data,
                    },
                )
            )
        if view_data["status"] == "canceled":
            return _no_store(
                templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "error_heading": "解析已取消",
                        "message": view_data.get("error_message", "用户已取消任务"),
                        **view_data,
                    },
                )
            )
        if view_data["status"] == "file_cleaned":
            return _no_store(
                templates.TemplateResponse(
                    "cleaned.html",
                    {"request": request, **view_data},
                )
            )
        if view_data["status"] == "success":
            task_id = view_data.get("task_id")
            if task_id:
                try:
                    usage_event = get_usage_repository().find_latest_event_by_task_id(
                        task_id
                    )
                    view_data["asr_usage"] = _build_asr_usage_display(usage_event)
                except Exception as exc:
                    logger.warning(
                        "Unable to load ASR usage for result page: "
                        f"{type(exc).__name__}"
                    )
            if view_data.get("summary"):
                view_data["summary_html"] = render_markdown_to_html(
                    view_data["summary"]
                )
            if view_data.get("comment_insight"):
                view_data["comment_insight_html"] = render_markdown_to_html(
                    view_data["comment_insight"]
                )

            cache_dir = view_data.get("cache_dir")

            # 计算字数统计
            stats = {
                "original_length": 0,
                "calibrated_length": 0,
                "summary_length": 0,
                "duration_display": view_data.get("duration_display"),
            }

            if cache_dir and os.path.exists(cache_dir):
                cache_dir_path = Path(cache_dir)

                # 1. 计算原始转录字数
                funasr_file = cache_dir_path / "transcript_funasr.json"
                capswriter_file = cache_dir_path / "transcript_capswriter.txt"

                if funasr_file.exists():
                    # FunASR JSON 格式：提取 text 字段
                    try:
                        import json

                        with open(funasr_file, "r", encoding="utf-8") as f:
                            funasr_data = json.load(f)
                        # 复用现有的格式化方法
                        from ...transcriber import FunASRSpeakerClient

                        funasr_client = FunASRSpeakerClient()
                        transcript_text = funasr_client.format_transcript_with_speakers(
                            funasr_data
                        )
                        stats["original_length"] = len(transcript_text)
                        logger.debug(
                            f"原始转录字数(FunASR): {stats['original_length']}"
                        )
                    except Exception as exc:
                        logger.error(f"计算FunASR转录字数失败: {exc}")
                elif capswriter_file.exists():
                    # CapsWriter 纯文本格式
                    try:
                        with open(capswriter_file, "r", encoding="utf-8") as f:
                            stats["original_length"] = len(f.read())
                        logger.debug(
                            f"原始转录字数(CapsWriter): {stats['original_length']}"
                        )
                    except Exception as exc:
                        logger.error(f"计算CapsWriter转录字数失败: {exc}")

                # 2. 计算校对文本字数
                calibrated_file = cache_dir_path / "llm_calibrated.txt"
                if calibrated_file.exists():
                    try:
                        with open(calibrated_file, "r", encoding="utf-8") as f:
                            stats["calibrated_length"] = len(f.read())
                        logger.debug(f"校对文本字数: {stats['calibrated_length']}")
                    except Exception as exc:
                        logger.error(f"计算校对文本字数失败: {exc}")

                # 3. 计算总结文本字数
                summary_file = cache_dir_path / "llm_summary.txt"
                if summary_file.exists():
                    try:
                        with open(summary_file, "r", encoding="utf-8") as f:
                            stats["summary_length"] = len(f.read())
                        logger.debug(f"总结文本字数: {stats['summary_length']}")
                    except Exception as exc:
                        logger.error(f"计算总结文本字数失败: {exc}")

            # 4. 读取校准质量统计
            processed_file = cache_dir_path / "llm_processed.json" if cache_dir else None
            if processed_file and processed_file.exists():
                try:
                    import json
                    with open(processed_file, "r", encoding="utf-8") as f:
                        processed_data = json.load(f)
                    cal_stats = processed_data.get("calibration_stats")
                    if cal_stats:
                        stats["calibration_stats"] = cal_stats
                except Exception as exc:
                    logger.error(f"读取校准统计失败: {exc}")

            fallback_text = view_data.get("transcript", "")
            transcript_path = Path(cache_dir) / "llm_calibrated.txt"
            if transcript_path.exists():
                fallback_text = transcript_path.read_text(encoding="utf-8")

            # 简化渲染逻辑：直接调用 render_with_cache_analysis
            view_data["calibrated_html"] = render_calibrated_content_smart(
                cache_dir, fallback_text
            )
            view_data["collection_navigation"] = _build_collection_navigation(
                view_token
            )

        return _no_store(
            templates.TemplateResponse(
                "transcript.html",
                {
                    "request": request,
                    **view_data,
                    "view_token": view_token,
                    "stats": stats,
                },
            )
        )

    except Exception as exc:
        logger.exception("查看转录页面异常: %s", exc)
        return _no_store(
            templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "message": "查看页面失败，请稍后重试",
                },
            )
        )


@router.get("/view/{view_token}/longcut")
def open_in_longcut(view_token: str, request: Request):
    """Start LongCut if needed and redirect a YouTube result into it."""
    view_data = cache_manager.get_view_data_by_token(view_token)
    if not view_data:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "view_token 无效或已过期",
            },
            status_code=404,
        )

    settings = get_longcut_settings(get_config())
    action = build_longcut_action(view_data, settings)
    if not action:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "当前任务不是可在 LongCut 中打开的 YouTube 视频",
            },
            status_code=400,
        )

    result = ensure_longcut_ready(settings)
    if not result.ready:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": f"LongCut 启动失败：{result.message}",
            },
            status_code=503,
        )

    return RedirectResponse(
        build_analysis_url(settings.base_url, str(view_data["media_id"])),
        status_code=303,
    )


@router.get("/view/{view_token}/progress")
async def view_progress(view_token: str):
    """Return minimal task progress for a public view token."""
    view_data = cache_manager.get_view_data_by_token(view_token)
    if not view_data:
        raise HTTPException(status_code=404, detail="view_token 无效或已过期")
    _decorate_view_timing(view_data)

    progress = view_data.get("progress")
    if isinstance(progress, dict):
        progress = dict(progress)
        evidence = progress.get("evidence")
        if isinstance(evidence, dict):
            evidence = dict(evidence)
            quote = evidence.get("cloud_quote")
            if isinstance(quote, dict):
                quote = dict(quote)
                quote.pop("quote_token", None)
                evidence["cloud_quote"] = quote
            progress["evidence"] = evidence
    payload = {
        "status": view_data.get("status"),
        "task_id": view_data.get("task_id"),
        "view_token": view_token,
        "title": view_data.get("title"),
        "created_at": view_data.get("created_at"),
        "elapsed_seconds": view_data.get("elapsed_seconds"),
        "elapsed_display": view_data.get("elapsed_display"),
        "duration_seconds": view_data.get("duration_seconds"),
        "duration_display": view_data.get("duration_display"),
        "progress": progress,
    }
    message = view_data.get("message") or view_data.get("error_message")
    if message:
        payload["message"] = message

    return payload
