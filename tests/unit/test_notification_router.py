"""Offline routing regressions after removing WeCom notifications."""

from unittest.mock import MagicMock, patch

import pytest

from src.video_transcript_api.utils import notifications
from src.video_transcript_api.utils.notifications.router import NotificationRouter


MODULE = "src.video_transcript_api.utils.notifications.router"


def _make_channel(name="feishu", send_ok=True):
    channel = MagicMock()
    channel.name = name
    channel.is_enabled = True
    channel.send_text.return_value = send_ok
    channel.send_rich.return_value = send_ok
    channel.notify_task_status.return_value = send_ok
    return channel


@pytest.fixture
def router():
    with patch(f"{MODULE}.load_config", return_value={}):
        return NotificationRouter()


@pytest.mark.parametrize("config", [
    {}, {"wechat": {"webhook": "https://qyapi.weixin.qq.com/legacy"}},
])
def test_old_configuration_does_not_register_any_channel(config):
    with patch(f"{MODULE}.load_config", return_value=config), \
         patch("wecom_notifier.WeComNotifier", side_effect=AssertionError("No WeCom SDK")), \
         patch(f"{MODULE}.FeishuChannel") as feishu:
        router = NotificationRouter()
    assert router.channels == []
    assert router.is_enabled is False
    assert router.send_text("hello") == {}
    feishu.assert_not_called()


def test_feishu_is_preserved_while_legacy_wechat_configuration_is_ignored():
    feishu = _make_channel()
    with patch(f"{MODULE}.load_config", return_value={
        "wechat": {"webhook": "https://qyapi.weixin.qq.com/legacy"},
        "feishu": {"webhook": "https://open.feishu.cn/current"},
    }), patch(f"{MODULE}.FeishuChannel", return_value=feishu):
        router = NotificationRouter()
    assert router.channels == [feishu]
    assert router.is_enabled is True
    assert router.send_text("hello") == {"feishu": True}
    feishu.send_text.assert_called_once_with("hello", webhook=None)


@pytest.mark.parametrize("method,args", [
    ("send_text", ("hello",)),
    ("send_rich", ("## hello",)),
    ("notify_task_status", ("https://example.com", "done")),
])
@pytest.mark.parametrize("retired_name", ["wechat", "wecom"])
def test_retired_channel_requests_never_send_or_fallback(router, method, args, retired_name):
    feishu = _make_channel()
    retired = _make_channel(retired_name)
    router.channels = [retired, feishu]
    result = getattr(router, method)(
        *args, channel_name=retired_name,
        webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=legacy",
        webhooks={retired_name: "https://qyapi.weixin.qq.com/legacy"},
    )
    assert result == {}
    assert retired.mock_calls == []
    assert feishu.mock_calls == []


@pytest.mark.parametrize("method,args", [
    ("send_text", ("hello",)),
    ("send_rich", ("## hello",)),
    ("notify_task_status", ("https://example.com", "done")),
])
def test_broadcast_and_failures_cannot_reactivate_retired_channel(router, method, args):
    feishu = _make_channel(send_ok=False)
    retired = _make_channel("wechat")
    router.channels = [retired, feishu]
    assert getattr(router, method)(*args) == {"feishu": False}
    assert getattr(router, method)(*args, channel_name="feishu") == {"feishu": False}
    assert retired.mock_calls == []


@pytest.mark.parametrize("method,args", [
    ("send_text", ("hello",)),
    ("send_rich", ("## hello",)),
    ("notify_task_status", ("https://example.com", "done")),
])
def test_per_channel_feishu_webhook_is_preserved(router, method, args):
    feishu = _make_channel()
    router.channels = [feishu]
    current = "https://open.feishu.cn/current"
    result = getattr(router, method)(
        *args, channel_name="feishu", webhook="https://unused.invalid",
        webhooks={"wechat": "https://qyapi.weixin.qq.com/legacy", "feishu": current},
    )
    assert result == {"feishu": True}
    assert getattr(feishu, method).call_args.kwargs["webhook"] == current


def test_feishu_exception_returns_failure_without_wechat_fallback(router):
    feishu = _make_channel()
    feishu.send_text.side_effect = RuntimeError("offline send failure")
    retired = _make_channel("wechat")
    router.channels = [feishu, retired]
    assert router.send_text("hello", channel_name="feishu") == {"feishu": False}
    assert retired.mock_calls == []


def test_lifecycle_initializes_only_feishu_and_keeps_router_available():
    with patch.object(notifications, "init_global_notifier") as legacy_init, \
         patch.object(notifications, "init_global_feishu_notifier") as feishu_init, \
         patch.object(notifications, "shutdown_global_feishu_notifier") as feishu_stop, \
         patch.object(notifications, "NotificationRouter") as router_class:
        try:
            notifications.init_all_notifiers()
            legacy_init.assert_not_called()
            feishu_init.assert_called_once()
            assert notifications.get_notification_router() is router_class.return_value
        finally:
            notifications.shutdown_all_notifiers()
        feishu_stop.assert_called_once()
        assert notifications._global_router is None
