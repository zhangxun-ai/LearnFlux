"""设置页与配置 API：前端配置后端各项密钥与服务地址（SCHEMA 驱动）。

- GET  /settings            提供设置页（含资源版本号，避免缓存旧版）
- GET  /api/settings/schema 公开的配置结构（无值），未登录也能渲染整张表单
- GET  /api/settings        读取当前生效值（密钥脱敏）+ Provider 注册表（需令牌）
- POST /api/settings        写入配置到数据库（鉴权保护，不回显完整密钥）
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..context import get_logger, get_static_dir
from ..services.settings_service import get_schema, read_settings, write_settings
from ..services.transcription import TranscribeResponse, verify_token

logger = get_logger()
static_dir = get_static_dir()

router = APIRouter(tags=["settings"])


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page():
    """提供配置页面。资源 URL 注入 mtime 版本号以破坏浏览器缓存。"""
    page = static_dir / "settings.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="settings page not found")
    version_files = [
        page,
        static_dir / "css" / "editorial.css",
        static_dir / "js" / "site-nav.js",
    ]
    version = str(int(max((f.stat().st_mtime for f in version_files if f.exists()), default=0)))
    content = page.read_text(encoding="utf-8").replace("__ASSET_VERSION__", version)
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache"})


@router.get("/api/settings/schema", response_model=TranscribeResponse)
async def get_settings_schema():
    """返回配置结构（无当前值，不含密钥），供未登录时也能渲染整张表单。"""
    return TranscribeResponse(code=200, message="ok", data=get_schema())


@router.get("/api/settings", response_model=TranscribeResponse)
async def get_settings(user_info: dict = Depends(verify_token)):
    """读取当前生效值（密钥脱敏）。需有效令牌。"""
    return TranscribeResponse(code=200, message="ok", data=read_settings())


@router.post("/api/settings", response_model=TranscribeResponse)
async def update_settings(request: Request, user_info: dict = Depends(verify_token)):
    """写入前端配置到 overrides 文件。需有效令牌。仅更新本次提交的非空字段。"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

    try:
        data = write_settings(payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("写入配置失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"写入配置失败: {exc}")

    logger.info("配置已通过设置页更新 (user=%s)", user_info.get("user_id"))
    return TranscribeResponse(code=200, message="保存成功", data=data)
