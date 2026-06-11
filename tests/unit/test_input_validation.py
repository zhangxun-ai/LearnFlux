"""
Input validation unit tests.

Covers:
- Webhook URL SSRF protection
- Metadata field length limits (title, description, author)
- Valid inputs pass through

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys

import pytest


from pydantic import ValidationError
from video_transcript_api.api.services.transcription import (
    MetadataOverride,
    TranscribeRequest,
    RecalibrateRequest,
)


class TestWebhookURLValidation:
    """Verify webhook URL SSRF protection."""

    def test_valid_webhook_accepted(self):
        """Normal https webhook should be accepted."""
        req = TranscribeRequest(
            url="https://example.com/video",
            wechat_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        )
        assert req.wechat_webhook is not None

    def test_none_webhook_accepted(self):
        """None webhook should be accepted."""
        req = TranscribeRequest(url="https://example.com/video", wechat_webhook=None)
        assert req.wechat_webhook is None

    def test_empty_webhook_accepted(self):
        """Empty string webhook should be accepted."""
        req = TranscribeRequest(url="https://example.com/video", wechat_webhook="")
        assert req.wechat_webhook == ""

    def test_localhost_webhook_rejected(self):
        """Localhost webhook should be rejected (SSRF)."""
        with pytest.raises(ValidationError) as exc_info:
            TranscribeRequest(
                url="https://example.com/video",
                wechat_webhook="http://127.0.0.1:8080/hook",
            )
        assert "webhook URL is not allowed" in str(exc_info.value)

    def test_private_ip_webhook_rejected(self):
        """Private IP webhook should be rejected (SSRF)."""
        with pytest.raises(ValidationError) as exc_info:
            TranscribeRequest(
                url="https://example.com/video",
                wechat_webhook="http://192.168.1.1/hook",
            )
        assert "webhook URL is not allowed" in str(exc_info.value)

    def test_recalibrate_webhook_validation(self):
        """RecalibrateRequest should also validate webhook."""
        with pytest.raises(ValidationError):
            RecalibrateRequest(
                view_token="test-token",
                wechat_webhook="http://10.0.0.1/hook",
            )

    def test_recalibrate_valid_webhook(self):
        """RecalibrateRequest should accept valid webhook."""
        req = RecalibrateRequest(
            view_token="test-token",
            wechat_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        )
        assert req.wechat_webhook is not None


class TestMetadataLengthLimits:
    """Verify metadata field length limits."""

    def test_title_within_limit(self):
        """Title within 200 chars should be accepted."""
        override = MetadataOverride(title="x" * 200)
        assert len(override.title) == 200

    def test_title_exceeds_limit(self):
        """Title over 200 chars should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MetadataOverride(title="x" * 201)
        assert "title" in str(exc_info.value).lower() or "max_length" in str(exc_info.value).lower()

    def test_description_within_limit(self):
        """Description within 2000 chars should be accepted."""
        override = MetadataOverride(description="x" * 2000)
        assert len(override.description) == 2000

    def test_description_exceeds_limit(self):
        """Description over 2000 chars should be rejected."""
        with pytest.raises(ValidationError):
            MetadataOverride(description="x" * 2001)

    def test_author_within_limit(self):
        """Author within 200 chars should be accepted."""
        override = MetadataOverride(author="x" * 200)
        assert len(override.author) == 200

    def test_author_exceeds_limit(self):
        """Author over 200 chars should be rejected."""
        with pytest.raises(ValidationError):
            MetadataOverride(author="x" * 201)

    def test_all_none_fields_accepted(self):
        """All None fields should be accepted."""
        override = MetadataOverride()
        assert override.title is None
        assert override.description is None
        assert override.author is None


class TestCommentOptionValidation:
    """Verify optional comment insight request fields."""

    def test_comment_fetching_is_disabled_by_default(self):
        """TranscribeRequest should not fetch comments unless explicitly enabled."""
        req = TranscribeRequest(url="https://example.com/video")
        assert req.include_comments is False
        assert req.comment_limit == 100

    def test_comment_limit_has_upper_bound(self):
        """Large comment windows should be rejected to control cost."""
        with pytest.raises(ValidationError):
            TranscribeRequest(
                url="https://example.com/video",
                include_comments=True,
                comment_limit=500,
            )
