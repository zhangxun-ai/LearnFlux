from datetime import datetime, timezone, timedelta
from typing import Optional
from ..logging import setup_logger

logger = setup_logger("timezone_helper")

def parse_timezone_offset(timezone_str: str) -> Optional[timezone]:
    """
    解析时区字符串并返回timezone对象
    
    支持格式：
    - UTC+8, UTC-5 (小时偏移)
    - UTC+08:30, UTC-05:30 (小时:分钟偏移)
    - UTC (UTC时间)
    
    Args:
        timezone_str: 时区字符串
        
    Returns:
        timezone对象，解析失败返回None
    """
    try:
        timezone_str = timezone_str.strip().upper()
        
        if timezone_str == "UTC":
            return timezone.utc
            
        if not timezone_str.startswith("UTC"):
            logger.warning(f"不支持的时区格式: {timezone_str}")
            return None
            
        # 移除UTC前缀
        offset_str = timezone_str[3:]
        
        if not offset_str:
            return timezone.utc
            
        # 判断正负号
        if offset_str[0] not in ['+', '-']:
            logger.warning(f"时区偏移格式错误: {timezone_str}")
            return None
            
        sign = 1 if offset_str[0] == '+' else -1
        offset_str = offset_str[1:]
        
        # 解析时间偏移
        if ':' in offset_str:
            # 格式：HH:MM
            parts = offset_str.split(':')
            if len(parts) != 2:
                logger.warning(f"时区偏移格式错误: {timezone_str}")
                return None
            hours = int(parts[0])
            minutes = int(parts[1])
        else:
            # 格式：H 或 HH
            hours = int(offset_str)
            minutes = 0
        
        # 创建timedelta对象
        total_minutes = sign * (hours * 60 + minutes)
        offset = timedelta(minutes=total_minutes)
        
        return timezone(offset)
        
    except (ValueError, IndexError) as e:
        logger.error(f"解析时区失败 {timezone_str}: {e}")
        return None

BEIJING_TIMEZONE = timezone(timedelta(hours=8))


def get_configured_timezone() -> timezone:
    """Return Beijing time for all user-facing dates (legacy public name)."""
    return BEIJING_TIMEZONE


def parse_utc_datetime(value: str | datetime) -> datetime:
    """Parse a persisted instant; legacy timestamps without an offset are UTC."""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.strip().replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_for_api(value: str | datetime | None) -> str | None:
    """Serialize a timestamp with an explicit Beijing offset; never guess on error."""
    if not value:
        return None
    try:
        return parse_utc_datetime(value).astimezone(BEIJING_TIMEZONE).isoformat()
    except (ValueError, TypeError, AttributeError):
        logger.warning("Invalid persisted timestamp")
        return None


def format_datetime_with_timezone(
    dt_str: str | datetime,
    output_format: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """Format UTC or offset-aware database timestamps in Beijing time."""
    if not dt_str:
        return ""
    try:
        return parse_utc_datetime(dt_str).astimezone(BEIJING_TIMEZONE).strftime(output_format)
    except (ValueError, TypeError, AttributeError):
        logger.warning("Invalid timestamp for display")
        return str(dt_str)


def format_datetime_for_display(dt_str: str) -> str:
    """
    为web页面显示格式化时间
    
    Args:
        dt_str: 数据库中的时间字符串
        
    Returns:
        用户友好的时间显示格式
    """
    try:
        formatted_time = format_datetime_with_timezone(dt_str, "%Y年%m月%d日 %H:%M")
        
        # 获取时区信息用于显示
        target_tz = get_configured_timezone()
        
        # 计算时区偏移用于显示
        offset_seconds = target_tz.utcoffset(datetime.now()).total_seconds()
        offset_hours = int(offset_seconds / 3600)
        offset_minutes = int((abs(offset_seconds) % 3600) / 60)
        
        if offset_minutes == 0:
            tz_display = f"UTC{offset_hours:+d}"
        else:
            sign = "+" if offset_hours >= 0 else "-"
            tz_display = f"UTC{sign}{abs(offset_hours):02d}:{offset_minutes:02d}"
        
        return f"{formatted_time} ({tz_display})"
        
    except Exception as e:
        logger.error(f"格式化显示时间失败 {dt_str}: {e}")
        return dt_str

def get_current_time_display() -> str:
    """
    获取当前时间的显示格式
    
    Returns:
        当前时间的格式化字符串
    """
    try:
        target_tz = get_configured_timezone()
        current_time = datetime.now(target_tz)
        return current_time.strftime("%Y年%m月%d日 %H:%M")
    except Exception as e:
        logger.error(f"获取当前时间失败: {e}")
        return datetime.now(BEIJING_TIMEZONE).strftime("%Y年%m月%d日 %H:%M")
