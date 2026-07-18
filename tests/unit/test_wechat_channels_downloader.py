"""
WeChat Channels downloader unit tests.

Covers:
- WeChat Channels URL handling
- TikHub POST response parsing
- Managed decrypt service startup/shutdown for encrypted media

All console output must be in English only.
"""

from unittest.mock import MagicMock, patch

import pytest

from video_transcript_api.downloaders.wechat_channels import (
    WeChatChannelsDownloader,
    WeChatDecryptServiceManager,
)


@pytest.fixture
def downloader():
    config = {
        "tikhub": {
            "api_key": "test-key",
            "max_retries": 1,
            "retry_delay": 0,
            "timeout": 30,
            "cache_enabled": False,
        },
        "wechat_channels": {},
    }
    with patch("video_transcript_api.downloaders.base.load_config", return_value=config):
        with patch("video_transcript_api.downloaders.base.get_temp_manager") as mock_tm:
            mock_tm.return_value = MagicMock()
            return WeChatChannelsDownloader()


def test_can_handle_wechat_channels_short_url(downloader):
    assert downloader.can_handle("https://weixin.qq.com/sph/AUqdQVIvFa")
    assert not downloader.can_handle("https://mp.weixin.qq.com/s/example")


def test_get_video_info_posts_share_url_and_parses_media(downloader):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.text = "{}"
    response.json.return_value = {
        "code": 200,
        "data": {
            "id": "14941130915890399732",
            "username": "v2_abc@finder",
            "nickname": "Finder Author",
            "title": "Finder Title",
            "description": "Finder Description",
            "media": {
                "url": "https://finder.video.example/media.mp4",
                "url_token": "?token=abc",
                "full_url": "https://finder.video.example/media.mp4?token=abc",
                "decode_key": "2136343393",
                "file_size": 123456,
            },
        },
    }

    with patch(
        "video_transcript_api.downloaders.wechat_channels.requests.post",
        return_value=response,
    ) as mock_post:
        info = downloader.get_video_info("https://weixin.qq.com/sph/AUqdQVIvFa")

    assert info["video_id"] == "14941130915890399732"
    assert info["video_title"] == "Finder Title"
    assert info["author"] == "Finder Author"
    assert info["download_url"] == "https://finder.video.example/media.mp4?token=abc"
    assert info["decode_key"] == "2136343393"
    assert info["platform"] == "wechat_channels"

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {
        "share_url": "https://weixin.qq.com/sph/AUqdQVIvFa",
        "raw": False,
    }


def test_get_video_info_normalizes_structured_title(downloader):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.text = "{}"
    response.json.return_value = {
        "code": 200,
        "data": {
            "id": "14941130915890399732",
            "nickname": "Finder Author",
            "title": [{"shortTitle": "How to build production skills?"}],
            "media": {
                "full_url": "https://finder.video.example/media.mp4?token=abc",
                "decode_key": "2136343393",
            },
        },
    }

    with patch(
        "video_transcript_api.downloaders.wechat_channels.requests.post",
        return_value=response,
    ):
        info = downloader.get_video_info("https://weixin.qq.com/sph/AUqdQVIvFa")

    assert info["video_title"] == "How to build production skills?"


def test_download_file_decrypts_encrypted_media_with_managed_service(
    downloader, tmp_path
):
    media_url = "https://finder.video.example/media.mp4?token=abc"
    filename = "wechat_channels_14941130915890399732.mp4"
    encrypted_path = tmp_path / "encrypted.mp4"
    decrypted_path = tmp_path / "decrypted.mp4"
    encrypted_path.write_bytes(b"encrypted video bytes")
    downloader.temp_manager.create_temp_file.return_value = str(decrypted_path)
    downloader._download_info_by_url[media_url] = {
        "decode_key": "2136343393",
    }

    class FakeDecryptService:
        exited = False

        def __enter__(self):
            return "http://localhost:10000"

        def __exit__(self, exc_type, exc, tb):
            self.exited = True

    response = MagicMock()
    response.iter_content.return_value = [b"decrypted video bytes"]
    service = FakeDecryptService()

    with patch.object(
        downloader,
        "_download_encrypted_file",
        return_value=str(encrypted_path),
    ), patch.object(
        downloader,
        "_decrypt_service_context",
        return_value=service,
    ), patch.object(downloader, "_validate_media_file", return_value=True), patch(
        "video_transcript_api.downloaders.wechat_channels.requests.post",
        return_value=response,
    ) as mock_post:
        result = downloader.download_file(media_url, filename)

    assert result == str(decrypted_path)
    assert decrypted_path.read_bytes() == b"decrypted video bytes"
    response.raise_for_status.assert_called_once()
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert service.exited is True
    assert args == ("http://localhost:10000/api/decrypt",)
    assert kwargs["data"] == {"decode_key": "2136343393"}
    assert kwargs["files"]["video"][0] == filename
    assert kwargs["timeout"] == (30, 600)
    assert kwargs["stream"] is True


def test_decrypt_service_manager_starts_on_port_10000_and_stops_owned_process(
    tmp_path,
):
    service_dir = tmp_path / "wechat-decrypt-api" / "api-service"
    service_dir.mkdir(parents=True)
    (service_dir / "server.js").write_text("console.log('server')", encoding="utf-8")
    (service_dir / "node_modules").mkdir()

    manager = WeChatDecryptServiceManager(
        {
            "wechat_channels": {
                "decrypt_service_dir": str(service_dir),
                "auto_install_decrypt_service": False,
                "decrypt_service_startup_timeout": 1,
            }
        }
    )
    process = MagicMock()
    process.poll.return_value = None

    health_results = iter([False, True])

    def fake_is_healthy():
        return next(health_results)

    with patch.object(manager, "_is_healthy", side_effect=fake_is_healthy), patch(
        "video_transcript_api.downloaders.wechat_channels.subprocess.Popen",
        return_value=process,
    ) as mock_popen, patch(
        "video_transcript_api.downloaders.wechat_channels.time.sleep"
    ):
        with manager as service_url:
            assert service_url == "http://localhost:10000"

    _, kwargs = mock_popen.call_args
    assert kwargs["cwd"] == str(service_dir)
    assert kwargs["env"]["PORT"] == "10000"
    assert kwargs["env"]["POOL_SIZE"] == "1"
    process.terminate.assert_called_once()
