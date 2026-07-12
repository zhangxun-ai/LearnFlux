"""视频转录API - 主要包初始化文件

一个基于Python的视频转录API服务，支持从多个平台下载视频并转录为文字。
"""

__version__ = "1.0.0"
__author__ = "视频转录API团队"

__all__ = ["app", "setup_logger"]


def __getattr__(name: str):
    if name == "app":
        from .api.server import app

        return app
    if name == "setup_logger":
        from .utils.logging import setup_logger

        return setup_logger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
