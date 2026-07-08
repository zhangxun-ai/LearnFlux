"""
TikHub REST client unit tests.

All console output must be in English only.
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from video_transcript_api.tikhub import (
    TikHubAuthError,
    TikHubClient,
    TikHubPaymentRequiredError,
    TikHubRateLimitError,
)


def _response(status_code: int, payload=None, text: str = ""):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "application/json"}
    response.text = text
    if payload is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = payload
        response.text = str(payload)
    return response


def test_get_uses_configured_base_url_and_bearer_token():
    client = TikHubClient(
        {
            "api_key": " primary-key ",
            "base_url": "https://api.tikhub.dev/",
            "max_retries": 1,
            "retry_delay": 0,
            "timeout": 12,
            "cache_enabled": False,
        }
    )

    with patch(
        "video_transcript_api.tikhub.requests.get",
        return_value=_response(200, {"code": 200, "data": {"ok": True}}),
    ) as mock_get:
        result = client.get("/api/v1/demo", {"url": "https://example.com/v/1"})

    assert result == {"code": 200, "data": {"ok": True}}
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args == ("https://api.tikhub.dev/api/v1/demo",)
    assert kwargs["params"] == {"url": "https://example.com/v/1"}
    assert kwargs["timeout"] == 12
    assert kwargs["headers"]["Authorization"] == "Bearer primary-key"


def test_post_sends_json_and_respects_min_timeout():
    client = TikHubClient(
        {
            "api_key": "primary-key",
            "max_retries": 1,
            "retry_delay": 0,
            "timeout": 5,
            "cache_enabled": False,
        }
    )
    payload = {"share_url": "https://weixin.qq.com/sph/AUqdQVIvFa", "raw": False}

    with patch(
        "video_transcript_api.tikhub.requests.post",
        return_value=_response(200, {"code": 200, "data": {"id": "1"}}),
    ) as mock_post:
        result = client.post(
            "/api/v1/wechat_channels/v2/fetch_video_detail",
            payload,
            min_timeout=30,
        )

    assert result == {"code": 200, "data": {"id": "1"}}
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == payload
    assert kwargs["timeout"] == 30
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_server_error_falls_back_to_alternate_api_key():
    client = TikHubClient(
        {
            "api_key": "primary-key",
            "alternate_api_key": "alternate-key",
            "max_retries": 1,
            "retry_delay": 0,
            "timeout": 10,
            "cache_enabled": False,
        }
    )

    responses = [
        _response(500, {"message": "server error"}),
        _response(200, {"code": 200, "data": {"ok": True}}),
    ]

    with patch(
        "video_transcript_api.tikhub.requests.get",
        side_effect=responses,
    ) as mock_get:
        result = client.get("/api/v1/demo", {"id": "123"})

    assert result == {"code": 200, "data": {"ok": True}}
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[0].kwargs["headers"]["Authorization"] == (
        "Bearer primary-key"
    )
    assert mock_get.call_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer alternate-key"
    )


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, TikHubAuthError),
        (402, TikHubPaymentRequiredError),
        (429, TikHubRateLimitError),
    ],
)
def test_error_status_codes_raise_specific_errors(status_code, error_type):
    client = TikHubClient(
        {
            "api_key": "primary-key",
            "max_retries": 1,
            "retry_delay": 0,
            "cache_enabled": False,
        }
    )

    with patch(
        "video_transcript_api.tikhub.requests.get",
        return_value=_response(status_code, {"message": "request failed"}),
    ):
        with pytest.raises(error_type):
            client.get("/api/v1/demo")


def test_missing_api_key_raises_auth_error():
    client = TikHubClient({"api_key": ""})

    with pytest.raises(TikHubAuthError):
        client.get("/api/v1/demo")


def test_success_response_is_reused_from_file_cache(tmp_path):
    client = TikHubClient(
        {
            "api_key": "primary-key",
            "max_retries": 1,
            "retry_delay": 0,
            "cache_dir": str(tmp_path),
            "cache_ttl_seconds": 3600,
        }
    )

    with patch(
        "video_transcript_api.tikhub.requests.get",
        return_value=_response(200, {"code": 200, "data": {"cached": True}}),
    ) as mock_get:
        first = client.get("/api/v1/demo", {"id": "123"})
        second = client.get("/api/v1/demo", {"id": "123"})

    assert first == second == {"code": 200, "data": {"cached": True}}
    mock_get.assert_called_once()


def test_expired_cache_entry_is_refetched(tmp_path):
    client = TikHubClient(
        {
            "api_key": "primary-key",
            "max_retries": 1,
            "retry_delay": 0,
            "cache_dir": str(tmp_path),
            "cache_ttl_seconds": 1,
        }
    )

    responses = [
        _response(200, {"code": 200, "data": {"version": 1}}),
        _response(200, {"code": 200, "data": {"version": 2}}),
    ]
    with patch("video_transcript_api.tikhub.requests.get", side_effect=responses):
        first = client.get("/api/v1/demo", {"id": "123"})
        cache_file = next(tmp_path.glob("*.json"))
        old = time.time() - 10
        os.utime(cache_file, (old, old))
        second = client.get("/api/v1/demo", {"id": "123"})

    assert first["data"]["version"] == 1
    assert second["data"]["version"] == 2


def test_error_response_is_not_cached(tmp_path):
    client = TikHubClient(
        {
            "api_key": "primary-key",
            "max_retries": 1,
            "retry_delay": 0,
            "cache_dir": str(tmp_path),
            "cache_ttl_seconds": 3600,
        }
    )

    with patch(
        "video_transcript_api.tikhub.requests.get",
        return_value=_response(429, {"message": "rate limited"}),
    ):
        with pytest.raises(TikHubRateLimitError):
            client.get("/api/v1/demo", {"id": "123"})

    assert list(tmp_path.glob("*.json")) == []
