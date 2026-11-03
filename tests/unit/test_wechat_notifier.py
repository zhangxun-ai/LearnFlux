"""Regression checks for disabled WeCom compatibility and pure format helpers."""

from unittest.mock import MagicMock, patch

import pytest

from src.video_transcript_api.utils.notifications import wechat
from src.video_transcript_api.utils.notifications.wechat import WechatNotifier, format_llm_config_markdown


@pytest.fixture
def notifier():
    return WechatNotifier(webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=legacy")


class TestCleanURL:
    """Tests for WechatNotifier._clean_url."""

    def test_generic_url_strips_query(self, notifier):
        """Generic URLs should have query parameters removed."""
        url = "https://example.com/page?utm_source=twitter&ref=123"
        assert notifier._clean_url(url) == "https://example.com/page"

    def test_generic_url_without_query_unchanged(self, notifier):
        """Generic URLs without query params are returned as-is."""
        url = "https://example.com/page"
        assert notifier._clean_url(url) == url

    def test_youtube_preserves_v_param(self, notifier):
        """YouTube URLs should keep v= parameter only."""
        url = "https://www.youtube.com/watch?v=abc123&list=PLx&t=42"
        assert notifier._clean_url(url) == "https://www.youtube.com/watch?v=abc123"

    def test_youtube_no_v_param(self, notifier):
        """YouTube URL without v= should strip all params."""
        url = "https://www.youtube.com/channel?sub=1"
        assert notifier._clean_url(url) == "https://www.youtube.com/channel"

    def test_youtu_be_preserved(self, notifier):
        """youtu.be short URLs with v= should preserve it."""
        url = "https://youtu.be/watch?v=xyz"
        assert notifier._clean_url(url) == "https://youtu.be/watch?v=xyz"

    def test_xiaohongshu_preserves_xsec_token(self, notifier):
        """Xiaohongshu URLs should keep xsec_token only."""
        url = "https://www.xiaohongshu.com/explore/abc?xsec_token=tok123&xsec_source=pc"
        assert notifier._clean_url(url) == "https://www.xiaohongshu.com/explore/abc?xsec_token=tok123"

    def test_xiaohongshu_no_xsec_token(self, notifier):
        """Xiaohongshu URL without xsec_token should strip all params."""
        url = "https://www.xiaohongshu.com/explore/abc?source=pc"
        assert notifier._clean_url(url) == "https://www.xiaohongshu.com/explore/abc"

    def test_xhslink_preserves_xsec_token(self, notifier):
        """xhslink.com URLs should also preserve xsec_token."""
        url = "https://xhslink.com/a/abc?xsec_token=tok456&ref=share"
        assert notifier._clean_url(url) == "https://xhslink.com/a/abc?xsec_token=tok456"

    def test_xiaohongshu_without_query(self, notifier):
        """Xiaohongshu URL without query should be returned as-is."""
        url = "https://www.xiaohongshu.com/explore/abc"
        assert notifier._clean_url(url) == url


# ============================================================
# URL Protection Tests
# ============================================================

class TestURLProtection:
    """Tests for _protect_urls and _restore_urls."""

    def test_protect_single_url(self, notifier):
        """Single URL should be replaced with placeholder."""
        text = "Visit https://example.com for details"
        protected, url_map = notifier._protect_urls(text)

        assert "https://example.com" not in protected
        assert "__URL_PLACEHOLDER_0__" in protected
        assert url_map["__URL_PLACEHOLDER_0__"] == "https://example.com"

    def test_protect_multiple_urls(self, notifier):
        """Multiple URLs should each get unique placeholders."""
        text = "See https://a.com and https://b.com here"
        protected, url_map = notifier._protect_urls(text)

        assert len(url_map) == 2
        assert "__URL_PLACEHOLDER_0__" in protected
        assert "__URL_PLACEHOLDER_1__" in protected

    def test_protect_no_urls(self, notifier):
        """Text without URLs returns empty url_map."""
        text = "No URLs here at all"
        protected, url_map = notifier._protect_urls(text)

        assert protected == text
        assert url_map == {}

    def test_protect_empty_text(self, notifier):
        """Empty text returns empty text and empty map."""
        protected, url_map = notifier._protect_urls("")
        assert protected == ""
        assert url_map == {}

    def test_protect_none_text(self, notifier):
        """None text returns None and empty map."""
        protected, url_map = notifier._protect_urls(None)
        assert protected is None
        assert url_map == {}

    def test_restore_urls(self, notifier):
        """Restored text should have original URLs back."""
        url_map = {
            "__URL_PLACEHOLDER_0__": "https://example.com",
            "__URL_PLACEHOLDER_1__": "https://other.com",
        }
        protected = "Visit __URL_PLACEHOLDER_0__ and __URL_PLACEHOLDER_1__"
        restored = notifier._restore_urls(protected, url_map)

        assert restored == "Visit https://example.com and https://other.com"

    def test_restore_empty_map(self, notifier):
        """Restoring with empty map returns text unchanged."""
        text = "no placeholders"
        assert notifier._restore_urls(text, {}) == text

    def test_roundtrip(self, notifier):
        """Protect then restore should return original text."""
        original = "Check https://example.com/path?q=1 for more"
        protected, url_map = notifier._protect_urls(original)
        restored = notifier._restore_urls(protected, url_map)
        assert restored == original


# ============================================================
class TestFormatLLMConfigMarkdown:
    """Tests for format_llm_config_markdown helper."""

    def test_empty_input(self):
        """Empty or None input returns empty string."""
        assert format_llm_config_markdown({}) == ""
        assert format_llm_config_markdown(None) == ""

    def test_calibrate_model_only(self):
        """Only calibrate model should be shown."""
        result = format_llm_config_markdown({"calibrate_model": "gpt-4"})
        assert "gpt-4" in result
        assert "calibrate" in result.lower() or "\u6821\u5bf9" in result

    def test_summary_model_only(self):
        """Only summary model should be shown."""
        result = format_llm_config_markdown({"summary_model": "claude-3"})
        assert "claude-3" in result

    def test_both_models(self):
        """Both models should appear in output."""
        result = format_llm_config_markdown({
            "calibrate_model": "gpt-4",
            "summary_model": "claude-3",
        })
        assert "gpt-4" in result
        assert "claude-3" in result

    def test_reasoning_effort_shown(self):
        """Reasoning effort should appear when set."""
        result = format_llm_config_markdown({
            "calibrate_model": "gpt-4",
            "calibrate_reasoning_effort": "high",
        })
        assert "high" in result

    def test_no_risk_flag_in_output(self):
        """Models dict without has_risk should not show risk marker."""
        result = format_llm_config_markdown({
            "calibrate_model": "gpt-4",
        })
        assert "\u964d\u7ea7" not in result


# ============================================================

@pytest.mark.parametrize("webhook", [None, "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=legacy"])
def test_legacy_adapter_never_constructs_sdk_or_reads_configuration(webhook):
    with patch("wecom_notifier.WeComNotifier", side_effect=AssertionError("SDK must stay unused")), \
         patch("src.video_transcript_api.utils.logging.load_config", side_effect=AssertionError("Config must stay unread")), \
         patch("requests.sessions.Session.request", side_effect=AssertionError("No network")):
        instance = WechatNotifier(webhook)
        assert instance.webhook is None
        assert instance.notifier is None
        assert instance.is_enabled is False
        assert instance.send_text("hello") is False
        assert instance.send_markdown_v2("## hello") is False
        assert instance.notify_task_status("https://example.com", "done") is False
        assert wechat.wechat_notify("hello", webhook, {"wechat": {"webhook": webhook}}) is False
        assert wechat.send_long_text_wechat("title", "https://example.com", "text", webhook=webhook) is False
        assert wechat.send_markdown_wechat("text", webhook=webhook) is False
        assert wechat.send_view_link_wechat("title", "private-token", webhook=webhook) is False
        assert wechat.send_wechat_notification("https://example.com", "done", webhook=webhook) is False
        assert wechat.init_global_notifier() is None
        assert wechat._get_global_notifier() is None
        wechat.shutdown_global_notifier()
        assert wechat._global_wecom_notifier is None


def test_assigned_sdk_cannot_reactivate_disabled_notifier(notifier):
    notifier.webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=legacy"
    notifier.notifier = MagicMock()
    assert notifier.send_text("hello") is False
    assert notifier.send_markdown_v2("## hello") is False
    assert notifier.notify_task_status("https://example.com", "done") is False
    assert notifier.is_enabled is False
    assert notifier.notifier.mock_calls == []
