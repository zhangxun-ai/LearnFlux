import logging
import os
import sys
from pathlib import Path
from loguru import logger

try:
    import commentjson as json  # 支持 JSONC 格式（带注释的 JSON）
except ImportError:
    import json  # 降级使用标准 json（不支持注释）

# 全局变量，标记logger是否已经配置
_logger_configured = False
# 全局配置缓存
_config_cache = None


class _InterceptHandler(logging.Handler):
    """把 stdlib logging record 转发到 loguru，保留级别/异常信息。"""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            level = logger.level(record.levelname).name
        except (ValueError, AttributeError):
            level = record.levelno

        # 跳过 logging 内部的帧，尽量定位到真实调用点
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def _config_dir() -> Path:
    """返回 config 目录路径（项目根 / config）。"""
    return Path(__file__).resolve().parents[4] / "config"


def _config_db_path() -> Path:
    """前端配置覆盖的 SQLite 路径（项目根 / data / config.db）。

    用固定路径而非依赖 config 里的 storage 配置，避免“读配置先得有配置”的循环依赖。
    """
    return Path(__file__).resolve().parents[4] / "data" / "config.db"


def _deep_merge(base: dict, override: dict) -> dict:
    """递归深合并 override 到 base 之上，返回新字典（不修改入参）。

    - 两边同 key 且都是 dict 时递归合并；
    - 否则 override 的值覆盖 base 的值；
    - base/override 任一非 dict 时直接返回 override。
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _flatten(data: dict, prefix: str = "") -> dict:
    """嵌套 dict 拍平成点号路径键；list/标量作为叶子值。
    {"llm": {"api_key": "x"}} -> {"llm.api_key": "x"}
    """
    flat: dict = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _unflatten(flat: dict) -> dict:
    """点号路径键还原成嵌套 dict。"""
    nested: dict = {}
    for path, value in flat.items():
        parts = str(path).split(".")
        node = nested
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value
    return nested


def _ensure_config_table(conn) -> None:
    """确保 config_overrides 表存在（键值：点号路径 -> JSON 值）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS config_overrides ("
        "config_key TEXT PRIMARY KEY, config_value TEXT NOT NULL, updated_at TEXT)"
    )


def load_config_overrides() -> dict:
    """从 data/config.db 读取前端配置覆盖；无库/损坏时返回空字典（绝不拖垮主流程）。"""
    import json as _stdjson
    import sqlite3

    db_path = _config_db_path()
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_config_table(conn)
            rows = conn.execute(
                "SELECT config_key, config_value FROM config_overrides"
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - 配置库异常不应拖垮配置加载
        return {}

    flat: dict = {}
    for key, raw in rows:
        try:
            flat[key] = _stdjson.loads(raw)
        except Exception:  # noqa: BLE001 - 单条损坏按原始字符串处理
            flat[key] = raw
    return _unflatten(flat)


def save_config_overrides(overrides: dict) -> None:
    """把（嵌套）覆盖配置拍平后逐项 UPSERT 进 data/config.db，并失效配置缓存。

    每个叶子变量对应一行（config_key 为点号路径），符合“界面改 → 库里对应变量变 → 重启生效”。
    """
    import json as _stdjson
    import sqlite3
    from datetime import datetime, timezone

    db_path = _config_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_config_table(conn)
        for key, value in _flatten(overrides).items():
            conn.execute(
                "INSERT INTO config_overrides (config_key, config_value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(config_key) DO UPDATE SET "
                "config_value=excluded.config_value, updated_at=excluded.updated_at",
                (key, _stdjson.dumps(value, ensure_ascii=False), now),
            )
        conn.commit()
    finally:
        conn.close()

    reset_config_cache()


def reset_config_cache() -> None:
    """清空配置缓存，使下次 load_config 重新读取并合并数据库覆盖。"""
    global _config_cache
    _config_cache = None


# 加载配置文件
def load_config():
    """
    加载配置文件。

    读取 config.jsonc（带注释，单一事实来源），再把 data/config.db 里前端写入的
    覆盖项（密钥、服务地址等）深合并到其上。结果缓存到 _config_cache；改库后重启即生效。
    """
    global _config_cache

    # 如果已经加载过配置，直接返回缓存
    if _config_cache is not None:
        return _config_cache

    # 获取项目根目录下的配置文件路径
    config_path = _config_dir() / "config.jsonc"

    with config_path.open("r", encoding="utf-8") as f:
        base_config = json.load(f)

    # 合并前端写入数据库的覆盖配置（无覆盖时行为与原来完全一致）
    overrides = load_config_overrides()
    _config_cache = _deep_merge(base_config, overrides) if overrides else base_config

    return _config_cache

# 创建日志目录
def ensure_dir(directory):
    """
    确保目录存在
    """
    if not os.path.exists(directory):
        os.makedirs(directory)

# 创建日志对象
def setup_logger(name=None, config=None):
    """
    设置日志记录器（使用 loguru）

    参数:
        name: 日志记录器名称（为了兼容性保留，loguru使用全局logger）
        config: 配置信息，如果为None则从配置文件加载

    返回:
        logger: loguru 日志记录器对象
    """
    global _logger_configured

    # 如果已经配置过，直接返回 logger
    if _logger_configured:
        return logger

    if config is None:
        config = load_config()

    log_config = config.get("log", {})
    log_level = log_config.get("level", "INFO").upper()
    log_file = log_config.get("file", "./logs/app.log")
    max_size = log_config.get("max_size", 10 * 1024 * 1024)  # 默认10MB
    backup_count = log_config.get("backup_count", 5)

    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    ensure_dir(log_dir)

    # 移除默认的 handler
    logger.remove()

    # 把 stdlib logging 的 record 转发到 loguru sink
    # （让第三方模块或本项目内用 logging.getLogger() 的代码也能被统一格式化）
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # 添加控制台处理程序
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
        diagnose=False,
    )

    # 添加文件处理程序
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=log_level,
        rotation=max_size,
        retention=backup_count,
        encoding="utf-8",
        enqueue=True,  # 异步写入，提高性能
        diagnose=False,
    )

    _logger_configured = True
    return logger 
