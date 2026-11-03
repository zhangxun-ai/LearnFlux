"""Disabled compatibility API for removed WeCom notifications.

Legacy imports and request fields remain readable, but no function in this
module reads notification configuration, constructs an SDK, or submits a message.
"""

from .channel import (
    _apply_risk_control_safe,
    _clean_url,
    _get_status_emoji,
    _protect_urls,
    _restore_urls,
)


_global_wecom_notifier = None


def init_global_notifier():
    """Compatibility no-op: WeCom notifications have been removed."""
    return None


def shutdown_global_notifier():
    """Clear the obsolete singleton reference without creating any resources."""
    global _global_wecom_notifier
    _global_wecom_notifier = None


def _get_global_notifier():
    """Compatibility no-op; never lazily construct a WeCom SDK."""
    return None


class WechatNotifier:
    """Inert legacy adapter; explicit webhooks cannot enable sending."""

    def __init__(self, webhook=None):
        self.webhook = None
        self.notifier = None

    @property
    def is_enabled(self) -> bool:
        return False

    _clean_url = staticmethod(_clean_url)
    _protect_urls = staticmethod(_protect_urls)
    _restore_urls = staticmethod(_restore_urls)
    _get_status_emoji = staticmethod(_get_status_emoji)
    _apply_risk_control_safe = staticmethod(_apply_risk_control_safe)

    def send_text(self, content, skip_risk_control=False):
        """Return False without formatting, queuing, or sending content."""
        return False

    def send_markdown_v2(self, content, skip_risk_control=False):
        """Return False without formatting, queuing, or sending content."""
        return False

    def notify_task_status(self, url, status, error=None, title=None, author=None, transcript=None):
        """Return False for all historical task notification calls."""
        return False


def wechat_notify(message, webhook=None, config=None):
    """Compatibility no-op, including when old configuration is supplied."""
    return False


def send_long_text_wechat(
    title, url, text, is_summary=False, webhook=None,
    has_speaker_recognition=False, use_rate_limit=True,
    skip_content_type_header=False,
):
    """Compatibility no-op for historical long-text notification callers."""
    return False


def send_view_link_wechat(title, view_token, webhook=None, original_url=None):
    """Compatibility no-op; never resolve or submit private result links."""
    return False


def send_markdown_wechat(content, webhook=None, skip_risk_control=False):
    """Compatibility no-op for historical Markdown notification callers."""
    return False


def send_wechat_notification(
    url, status, error=None, title=None, author=None, transcript=None, webhook=None,
):
    """Compatibility no-op for historical task notification callers."""
    return False


def format_llm_config_markdown(models_used: dict) -> str:
    """
    将 LLM 模型配置格式化为 Markdown 文本（仅展示校对和总结模型）

    Args:
        models_used: 模型配置字典

    Returns:
        str: 格式化后的 Markdown 文本
    """
    if not models_used:
        return ""

    lines = ["**模型配置：**"]

    # 校对模型
    calibrate_model = models_used.get('calibrate_model', '')
    calibrate_effort = models_used.get('calibrate_reasoning_effort')
    if calibrate_model:
        effort_str = f" (reasoning: {calibrate_effort})" if calibrate_effort else ""
        lines.append(f"> 校对: {calibrate_model}{effort_str}")

    # 总结模型
    summary_model = models_used.get('summary_model', '')
    summary_effort = models_used.get('summary_reasoning_effort')
    if summary_model:
        effort_str = f" (reasoning: {summary_effort})" if summary_effort else ""
        lines.append(f"> 总结: {summary_model}{effort_str}")

    return "\n".join(lines)
