import ipaddress
import os
import json
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

from ..browser_auth import require_same_origin
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


# 首页 HTML：本地产品介绍页，帮助首次进入时理解学习流程
_HOME_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LearnFlux · 让学习，回归生活的美好</title>
    <meta name="description" content="LearnFlux 是一款个人 AI 学习工作台，可导入音视频、文档与文字，生成逐字稿和 AI 解读，并将有用的内容整理到自己的知识库。">
    <meta name="robots" content="noindex, nofollow">
    <meta name="theme-color" content="#FDFCF8">
    <meta name="application-name" content="LearnFlux">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="LearnFlux">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <link rel="manifest" href="/manifest.webmanifest">
    <link rel="icon" type="image/svg+xml" sizes="any" href="/static/icon/learnflux-leaf.svg?v=__ASSET_VERSION__">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/icon/learnflux-favicon-32.png">
    <link rel="apple-touch-icon" href="/static/icon/learnflux-apple-touch-icon.png">
    <meta property="og:title" content="LearnFlux · 让学习，回归生活的美好">
    <meta property="og:description" content="个人 AI 学习工作台：导入内容、理解重点、整理笔记。">
    <meta property="og:type" content="website">
    <meta property="og:image" content="/static/icon/learnflux-og.png">
    <meta name="twitter:card" content="summary_large_image">

    <link rel="stylesheet" href="/static/css/landing-wildwood.css?v=__ASSET_VERSION__">
</head>
<body class="page-home marketing-home">
    <!-- impeccable:contract | thesis: 让学习，回归生活的美好 | own-world: 明亮、克制的手绘田野与湖景，作为本地学习旅程的入口 | story: 导入内容 → AI 理解 → 复习整理 → 沉淀笔记 | first-viewport: LearnFlux 品牌文案、手写短句、横向工作台示意与底部三步流程 | visitor: 正在自己的 Mac 上使用 LearnFlux 的个人学习者 | primary-action: 点击工作台示意卡 → /add_task_by_web | secondary-action: none | proof: 只展示仓库已有能力，不展示客户、价格或公开服务承诺 | finish-line: 用户记住产品气质并进入真实工作台开始学习 -->
    <a class="lf-skip" href="#main-content">跳到主要内容</a>
    <main class="lf-main" id="main-content">
        <section class="lf-hero" aria-labelledby="hero-title">
            <figure class="lf-hero-art">
                <picture>
                    <source media="(min-aspect-ratio: 2.1/1)" srcset="/static/images/landing/learnflux-meadow-hero-panorama.png?v=__ASSET_VERSION__">
                    <img
                        src="/static/images/landing/learnflux-meadow-hero-v2.png?v=__ASSET_VERSION__"
                        width="1672"
                        height="941"
                        alt="湖畔小屋、花径、野花与春日树枝下的阅读小桌"
                        fetchpriority="high"
                        decoding="async"
                    >
                </picture>
            </figure>
            <header class="lf-brand-lockup">
                <a class="lf-brand" href="/" aria-label="LearnFlux 首页">
                    <img class="lf-leaf-mark" src="/static/icon/learnflux-leaf.svg?v=__ASSET_VERSION__" alt="" aria-hidden="true">
                    <span>LearnFlux</span>
                </a>
                <div class="lf-brand-copy">
                    <h1 id="hero-title">让学习，回归生活的美好</h1>
                    <p>在不确定的时代，持续成长</p>
                </div>
            </header>
            <p class="lf-hero-note">好奇，<br>让平凡的日子发光。</p>
            <a class="lf-workbench-preview" href="/add_task_by_web" aria-label="开始学习，进入 LearnFlux 工作台">
                <aside class="lf-preview-sidebar" aria-hidden="true">
                    <div class="lf-preview-brand"><img class="lf-leaf-mark" src="/static/icon/learnflux-leaf.svg?v=__ASSET_VERSION__" alt="" aria-hidden="true"><strong>LearnFlux</strong></div>
                    <span class="lf-preview-group">学习功能</span>
                    <span class="lf-preview-nav-item is-current">单次学习</span>
                    <span class="lf-preview-nav-item">合集学习</span>
                    <span class="lf-preview-nav-item">学习播放器</span>
                    <span class="lf-preview-nav-item">复习</span>
                </aside>
                <div class="lf-preview-content" aria-hidden="true">
                    <div class="lf-preview-media">
                        <div class="lf-preview-visual">
                            <img src="/static/images/landing/learnflux-reading-nook-cover.webp?v=__ASSET_VERSION__" alt="" loading="lazy" decoding="async">
                            <span class="lf-preview-play" aria-hidden="true">
                                <svg viewBox="0 0 24 24" focusable="false"><path d="M8.1 5.6a.8.8 0 0 1 1.2-.7l10.1 6.3a.9.9 0 0 1 0 1.6L9.3 19a.8.8 0 0 1-1.2-.7z"/></svg>
                            </span>
                        </div>
                        <strong>如何在不确定的时代保持学习力</strong>
                        <div class="lf-preview-progress"><span></span></div>
                    </div>
                    <div class="lf-preview-transcript">
                        <div class="lf-preview-heading"><strong>如何在不确定的时代保持学习力</strong><span>示例内容 · 学习方法</span></div>
                        <div class="lf-preview-tabs"><span class="is-active">逐字稿</span><span>AI 解读</span><span>笔记</span></div>
                        <p><time>00:32</time> 在变化很快的时候，持续学习让我们更从容。</p>
                        <p><time>01:15</time> 把输入转成自己的理解，知识才会留下来。</p>
                    </div>
                    <div class="lf-preview-note">
                        <strong>我的笔记</strong>
                        <span>记录一个想法</span>
                        <p>先理解，再整理。留下真正有用的内容。</p>
                    </div>
                </div>
            </a>
            <section class="lf-flow-strip" id="workflow" aria-label="学习流程">
                <ol class="lf-steps">
                <li>
                    <span class="lf-step-number">01</span>
                    <div><h3>导入内容</h3><p>视频、音频、文档或文字</p></div>
                </li>
                <li>
                    <span class="lf-step-number">02</span>
                    <div><h3>AI 解读</h3><p>逐字稿、摘要与内容解释</p></div>
                </li>
                <li>
                    <span class="lf-step-number">03</span>
                    <div><h3>复习与沉淀</h3><p>整理笔记，保存到 Obsidian</p></div>
                </li>
                </ol>
            </section>
        </section>

    </main>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home():
    """Local product introduction page for first-time orientation."""
    static_dir = get_static_dir()
    version_files = [
        static_dir / "icon" / "learnflux-icon-256.png",
        static_dir / "icon" / "learnflux-leaf.svg",
        static_dir / "images" / "landing" / "01-single-study.png",
        static_dir / "images" / "landing" / "02-collections.png",
        static_dir / "images" / "landing" / "03-study-player.png",
        static_dir / "images" / "landing" / "04-visual-learning.png",
        static_dir / "images" / "landing" / "learnflux-reading-nook-cover.webp",
        static_dir / "images" / "landing" / "learnflux-meadow-hero-v2.png",
        static_dir / "images" / "landing" / "learnflux-meadow-hero-panorama.png",
        static_dir / "css" / "landing-wildwood.css",
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


def _export_content_from_view(
    view_data: Dict[str, Any], export_type: str
) -> Optional[str]:
    """Read an export section from PostgreSQL-backed data or legacy files."""

    field_map = {
        "calibrated": "llm_calibrated",
        "summary": "summary",
        "comment_insight": "comment_insight",
    }
    if export_type in field_map:
        value = view_data.get(field_map[export_type])
        if isinstance(value, str) and value:
            return value
    elif export_type == "transcript":
        value = view_data.get("source_transcript")
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
    else:
        return None

    cache_dir = view_data.get("cache_dir")
    if not cache_dir or not os.path.exists(cache_dir):
        return None
    file_path = resolve_export_file_path(cache_dir, export_type)
    if not file_path or not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8")


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

    supported_types = {"calibrated", "summary", "comment_insight", "transcript"}
    if export_type not in supported_types:
        return HTMLResponse(
            content="<html><body><p>不支持的导出类型</p></body></html>",
            status_code=400,
        )
    try:
        content = _export_content_from_view(view_data, export_type)
    except Exception as exc:
        logger.error(f"读取导出内容失败: type={export_type} error={exc}")
        return HTMLResponse(
            content="<html><body><p>读取文件失败</p></body></html>",
            status_code=500,
        )
    if content is None:
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

    # 将内容渲染为 HTML（Markdown -> HTML）
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
    sections = []
    for export_type in get_export_scope_sections(scope):
        try:
            content = _export_content_from_view(view_data, export_type)
        except Exception as exc:
            logger.error(f"读取导出分段失败: {exc}")
            continue
        if content is None:
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

    supported_types = {"calibrated", "summary", "comment_insight", "transcript"}
    if export_type not in supported_types:
        return Response(
            content=f"❌ 不支持的导出类型: {export_type}\n\n支持的类型: calibrated, summary, comment_insight, transcript",
            media_type="text/plain; charset=utf-8",
            status_code=400,
        )

    try:
        content = _export_content_from_view(view_data, export_type)
    except Exception as exc:
        logger.error(f"读取导出内容失败: type={export_type} error={exc}")
        return Response(
            content="❌ 读取文件失败，请稍后重试",
            media_type="text/plain; charset=utf-8",
            status_code=500,
        )
    if content is None:
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

    content = _normalize_export_content(export_type, content)

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
                static_dir / "css" / "learning-history-meadow.css",
                static_dir / "css" / "workbench-wildwood.css",
                static_dir / "css" / "single-study-improvements.css",
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

        supported_types = {
            "calibrated", "summary", "comment_insight", "transcript"
        }
        if export_type not in supported_types:
            return Response(
                content=f"❌ 不支持的导出类型: {export_type}\n\n支持的类型: calibrated, summary, comment_insight, transcript",
                media_type="text/plain; charset=utf-8",
                status_code=400,
            )

        try:
            content = _export_content_from_view(view_data, export_type)
        except Exception as exc:
            logger.error(
                "读取导出内容失败: type=%s error=%s", export_type, exc
            )
            return Response(
                content="❌ 读取文件失败，请稍后重试",
                media_type="text/plain; charset=utf-8",
                status_code=500,
            )
        if content is None:
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

        content = _normalize_export_content(export_type, content)

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
    require_same_origin(request)
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
    def is_loopback(value: str | None, *, allow_test_value: bool = False) -> bool:
        normalized = (value or "").strip().strip("[]").lower()
        if normalized == "localhost" or (allow_test_value and normalized in {"testclient", "testserver"}):
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    client_host = request.client.host if request.client else ""
    return is_loopback(client_host, allow_test_value=True) and is_loopback(
        request.url.hostname,
        allow_test_value=True,
    )


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

            source_transcript = view_data.get("source_transcript")
            if isinstance(source_transcript, str):
                stats["original_length"] = len(source_transcript)
            elif isinstance(source_transcript, dict):
                try:
                    from ...transcriber import FunASRSpeakerClient

                    stats["original_length"] = len(
                        FunASRSpeakerClient().format_transcript_with_speakers(
                            source_transcript
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        f"Unable to measure PostgreSQL transcript: {exc}"
                    )
            calibrated_value = view_data.get("llm_calibrated")
            if isinstance(calibrated_value, str):
                stats["calibrated_length"] = len(calibrated_value)
            summary_value = view_data.get("summary")
            if isinstance(summary_value, str):
                stats["summary_length"] = len(summary_value)

            cache_dir_path = Path(cache_dir) if cache_dir else None
            if cache_dir_path is not None and cache_dir_path.exists():

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
            processed_data = view_data.get("llm_processed")
            if isinstance(processed_data, dict):
                cal_stats = processed_data.get("calibration_stats")
                if cal_stats:
                    stats["calibration_stats"] = cal_stats
            processed_file = (
                cache_dir_path / "llm_processed.json"
                if cache_dir_path is not None
                else None
            )
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

            fallback_text = (
                view_data.get("llm_calibrated")
                or view_data.get("transcript", "")
            )
            transcript_path = (
                Path(cache_dir) / "llm_calibrated.txt" if cache_dir else None
            )
            if transcript_path is not None and transcript_path.exists():
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
