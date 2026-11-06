"""The historical WeCom entry points must remain offline compatibility shims."""

from video_transcript_api.utils.notifications import (
    WechatNotifier,
    WeComChannel,
    send_markdown_wechat,
    send_wechat_notification,
)


def test_retired_wecom_flow_never_accepts_a_send(monkeypatch):
    def unexpected_network(*args, **kwargs):
        raise AssertionError("Retired WeCom flow attempted a network request")

    monkeypatch.setattr("requests.sessions.Session.request", unexpected_network)
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=retired-example"
    source = "https://example.com/source"
    assert WechatNotifier(webhook).send_text("example") is False
    assert WeComChannel(webhook).send_text("example") is False
    assert send_markdown_wechat("example", webhook=webhook) is False
    assert send_wechat_notification(source, "completed", webhook=webhook) is False
