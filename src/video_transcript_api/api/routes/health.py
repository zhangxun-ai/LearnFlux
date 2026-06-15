"""健康检查路由

提供系统健康状态检查端点，检查 SQLite、ASR 服务、磁盘空间等组件状态。
"""

import os
import sqlite3
import asyncio
from typing import Dict, Any

from fastapi import APIRouter

from ..context import get_cache_manager, get_config, get_logger

logger = get_logger()
config = get_config()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """系统健康检查端点

    检查各核心组件的状态，返回整体健康状况。

    Returns:
        dict: 健康状态摘要
    """
    checks = {}

    checks["sqlite"] = _check_sqlite()

    local_whisper = config.get("local_whisper", {})
    if local_whisper.get("enabled", False):
        checks["local_whisper"] = _check_local_whisper(local_whisper)
        checks["local_whisper"]["required"] = True
        checks["capswriter"] = {
            "healthy": True,
            "skipped": True,
            "required": False,
            "reason": "local_whisper enabled",
        }
    else:
        capswriter_url = config.get("capswriter", {}).get("server_url")
        if capswriter_url:
            checks["capswriter"] = await _check_websocket_service(
                capswriter_url, "CapsWriter"
            )
            checks["capswriter"]["required"] = True
        else:
            checks["capswriter"] = {
                "healthy": True,
                "skipped": True,
                "required": False,
                "reason": "not configured",
            }

    funasr_cfg = config.get("funasr_spk_server", {})
    funasr_required = bool(funasr_cfg.get("required", False))
    funasr_url = funasr_cfg.get("server_url")
    if funasr_url:
        checks["funasr"] = await _check_websocket_service(funasr_url, "FunASR")
        checks["funasr"]["required"] = funasr_required
        checks["funasr"]["feature"] = "speaker_recognition"
    else:
        checks["funasr"] = {
            "healthy": True,
            "skipped": True,
            "required": False,
            "feature": "speaker_recognition",
            "reason": "not configured",
        }
    checks["disk_space"] = _check_disk_space()

    required_checks = [
        c for c in checks.values()
        if c.get("required", True)
    ]
    all_healthy = all(c.get("healthy", False) for c in required_checks)
    status = "healthy" if all_healthy else "degraded"
    optional_unhealthy = [
        name for name, check in checks.items()
        if not check.get("required", True) and not check.get("healthy", False)
    ]

    return {
        "status": status,
        "checks": checks,
        "optional_unhealthy": optional_unhealthy,
    }


def _check_sqlite() -> Dict[str, Any]:
    """检查 SQLite 数据库连通性"""
    try:
        cache_manager = get_cache_manager()
        conn = sqlite3.connect(str(cache_manager.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return {"healthy": True}
    except Exception as e:
        logger.warning(f"SQLite health check failed: {e}")
        return {"healthy": False, "error": str(e)}


def _check_local_whisper(local_whisper: Dict[str, Any]) -> Dict[str, Any]:
    """检查本地 mlx-whisper 可执行文件是否可用。"""
    try:
        binary = os.path.expanduser(
            local_whisper.get("binary", "~/.venvs/mlx-whisper/bin/mlx_whisper")
        )
        if not os.path.isfile(binary):
            return {"healthy": False, "error": f"missing binary: {binary}"}
        return {
            "healthy": True,
            "binary": binary,
            "model": local_whisper.get("model"),
        }
    except Exception as e:
        logger.warning(f"Local whisper health check failed: {e}")
        return {"healthy": False, "error": str(e)}


async def _check_websocket_service(url: str, name: str) -> Dict[str, Any]:
    """检查 WebSocket 服务连通性

    Args:
        url: WebSocket 服务地址
        name: 服务名称（用于日志）

    Returns:
        dict: 健康状态
    """
    try:
        import websockets
        async with asyncio.timeout(5):
            async with websockets.connect(url, close_timeout=3):
                pass
        return {"healthy": True}
    except ImportError:
        # websockets 未安装，尝试用 socket 检测端口
        return _check_tcp_port(url, name)
    except asyncio.TimeoutError:
        logger.warning(f"{name} health check timed out: {url}")
        return {"healthy": False, "error": "connection timed out"}
    except Exception as e:
        logger.warning(f"{name} health check failed: {url}, error: {e}")
        return {"healthy": False, "error": str(e)}


def _check_tcp_port(url: str, name: str) -> Dict[str, Any]:
    """通过 TCP 连接检查端口可达性（websockets 不可用时的后备方案）

    Args:
        url: WebSocket URL（ws://host:port 格式）
        name: 服务名称

    Returns:
        dict: 健康状态
    """
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 80

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return {"healthy": True}
        else:
            return {"healthy": False, "error": f"port {port} unreachable"}
    except Exception as e:
        logger.warning(f"{name} TCP health check failed: {e}")
        return {"healthy": False, "error": str(e)}


def _check_disk_space() -> Dict[str, Any]:
    """检查磁盘空间

    当可用空间低于 1GB 时标记为不健康。
    """
    try:
        stat = os.statvfs(".")
        free_bytes = stat.f_bavail * stat.f_frsize
        free_gb = free_bytes / (1024 ** 3)

        healthy = free_gb >= 1.0
        result = {
            "healthy": healthy,
            "free_gb": round(free_gb, 2),
        }
        if not healthy:
            result["error"] = f"low disk space: {free_gb:.2f} GB"
        return result
    except Exception as e:
        logger.warning(f"Disk space check failed: {e}")
        return {"healthy": False, "error": str(e)}
