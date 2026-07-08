import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from .base import BaseDownloader
from .models import VideoMetadata, DownloadInfo
from ..tikhub import TikHubClient, TikHubError
from ..utils.logging import setup_logger

logger = setup_logger("wechat_channels_downloader")

_VIDEO_DETAIL_ENDPOINT = "/api/v1/wechat_channels/v2/fetch_video_detail"
_DECRYPT_SERVICE_REPO = "https://github.com/Evil0ctal/WeChat-Channels-Video-File-Decryption.git"
_DEFAULT_DECRYPT_SERVICE_PORT = 10000
_DEFAULT_DECRYPT_SERVICE_DIR = "./data/services/wechat-decrypt-api/api-service"


class WeChatDecryptServiceManager:
    """Start the local WeChat decrypt API only while encrypted media is processed."""

    _lock = threading.RLock()
    _process: Optional[subprocess.Popen] = None
    _ref_count = 0
    _active_url = ""

    def __init__(self, config: dict) -> None:
        decrypt_config = config.get("wechat_channels", {}) or {}
        configured_url = (
            os.getenv("WECHAT_CHANNELS_DECRYPT_SERVICE_URL")
            or decrypt_config.get("decrypt_service_url")
            or f"http://localhost:{_DEFAULT_DECRYPT_SERVICE_PORT}"
        )
        self.service_url = configured_url.rstrip("/")
        parsed = urlparse(self.service_url)
        self.port = int(
            os.getenv("WECHAT_CHANNELS_DECRYPT_SERVICE_PORT")
            or decrypt_config.get("decrypt_service_port")
            or parsed.port
            or _DEFAULT_DECRYPT_SERVICE_PORT
        )
        self.pool_size = int(decrypt_config.get("decrypt_service_pool_size", 1))
        self.startup_timeout = int(
            decrypt_config.get("decrypt_service_startup_timeout", 90)
        )
        self.install_timeout = int(
            decrypt_config.get("decrypt_service_install_timeout", 600)
        )
        self.auto_start = self._as_bool(
            decrypt_config.get("auto_start_decrypt_service", True)
        )
        self.auto_install = self._as_bool(
            decrypt_config.get("auto_install_decrypt_service", True)
        )
        self.stop_after_request = self._as_bool(
            decrypt_config.get("stop_decrypt_service_after_request", True)
        )
        service_dir = (
            os.getenv("WECHAT_CHANNELS_DECRYPT_SERVICE_DIR")
            or decrypt_config.get("decrypt_service_dir")
            or _DEFAULT_DECRYPT_SERVICE_DIR
        )
        self.service_dir = Path(service_dir).expanduser()
        self._owns_process = False

    def __enter__(self) -> str:
        cls = type(self)
        with cls._lock:
            if (
                cls._process
                and cls._process.poll() is None
                and cls._active_url == self.service_url
            ):
                cls._ref_count += 1
                self._owns_process = True
                return self.service_url

            if self._is_healthy():
                logger.info(f"Using existing WeChat decrypt service: {self.service_url}")
                return self.service_url

            if not self.auto_start:
                raise ValueError(
                    "WeChat Channels media requires decryption; start the decrypt "
                    f"service at {self.service_url} or enable auto_start_decrypt_service."
                )

            self._ensure_service_ready()
            process = self._start_process()
            cls._process = process
            cls._active_url = self.service_url
            cls._ref_count = 1
            self._owns_process = True
            try:
                self._wait_until_healthy()
            except Exception:
                self._stop_process(process)
                cls._process = None
                cls._active_url = ""
                cls._ref_count = 0
                self._owns_process = False
                raise
            return self.service_url

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._owns_process:
            return

        cls = type(self)
        with cls._lock:
            cls._ref_count = max(0, cls._ref_count - 1)
            if (
                self.stop_after_request
                and cls._ref_count == 0
                and cls._process is not None
            ):
                self._stop_process(cls._process)
                cls._process = None
                cls._active_url = ""

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _is_healthy(self) -> bool:
        try:
            response = requests.get(f"{self.service_url}/health", timeout=1.5)
            if response.status_code != 200:
                return False
            data = response.json()
            return data.get("status") == "ok"
        except Exception:
            return False

    def _ensure_service_ready(self) -> None:
        if not (self.service_dir / "server.js").exists():
            if not self.auto_install:
                raise ValueError(
                    f"WeChat decrypt service is missing: {self.service_dir}"
                )
            self._clone_service_source()

        if not (self.service_dir / "node_modules").exists():
            if not self.auto_install:
                raise ValueError(
                    f"WeChat decrypt service dependencies are missing: {self.service_dir}"
                )
            self._install_service_dependencies()

    def _clone_service_source(self) -> None:
        git_binary = shutil.which("git")
        if not git_binary:
            raise ValueError("git is required to install the WeChat decrypt service")

        repo_dir = self.service_dir.parent
        if repo_dir.exists() and any(repo_dir.iterdir()):
            raise ValueError(
                f"WeChat decrypt service directory is not empty and missing server.js: "
                f"{self.service_dir}"
            )

        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                git_binary,
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                _DECRYPT_SERVICE_REPO,
                str(repo_dir),
            ],
            check=True,
            timeout=180,
        )
        subprocess.run(
            [git_binary, "sparse-checkout", "set", "api-service"],
            cwd=str(repo_dir),
            check=True,
            timeout=60,
        )

    def _install_service_dependencies(self) -> None:
        npm_binary = shutil.which("npm")
        npx_binary = shutil.which("npx")
        if not npm_binary or not npx_binary:
            raise ValueError("npm and npx are required to install the decrypt service")

        subprocess.run(
            [npm_binary, "install"],
            cwd=str(self.service_dir),
            check=True,
            timeout=self.install_timeout,
        )
        subprocess.run(
            [npx_binary, "playwright", "install", "chromium"],
            cwd=str(self.service_dir),
            check=True,
            timeout=self.install_timeout,
        )

    def _start_process(self) -> subprocess.Popen:
        npm_binary = shutil.which("npm")
        if not npm_binary:
            raise ValueError("npm is required to start the WeChat decrypt service")

        env = os.environ.copy()
        env["PORT"] = str(self.port)
        env["POOL_SIZE"] = str(self.pool_size)
        logger.info(f"Starting WeChat decrypt service on port {self.port}")
        return subprocess.Popen(
            [npm_binary, "start"],
            cwd=str(self.service_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _wait_until_healthy(self) -> None:
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._is_healthy():
                return
            process = type(self)._process
            if process and process.poll() is not None:
                raise ValueError("WeChat decrypt service exited during startup")
            time.sleep(1)
        raise ValueError(
            f"WeChat decrypt service did not become healthy: {self.service_url}"
        )

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        logger.info("Stopping WeChat decrypt service")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class WeChatChannelsDownloader(BaseDownloader):
    """Downloader for WeChat Channels share links."""

    def __init__(self) -> None:
        super().__init__()
        self._cached_video_info: dict[str, dict] = {}
        self._download_info_by_url: dict[str, dict] = {}

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == "weixin.qq.com" and parsed.path.startswith("/sph/")

    def extract_video_id(self, url: str) -> str:
        match = re.search(r"/sph/([A-Za-z0-9]+)", url)
        if match:
            return match.group(1)
        raise ValueError(f"Failed to extract WeChat Channels share ID from URL: {url}")

    def get_video_info(self, url: str) -> dict:
        share_id = self.extract_video_id(url)
        if share_id in self._cached_video_info:
            logger.debug(f"[cache hit] Returning cached WeChat Channels info: {share_id}")
            return self._cached_video_info[share_id]

        response = self._post_tikhub_request(
            _VIDEO_DETAIL_ENDPOINT,
            {"share_url": url, "raw": False},
        )
        self._validate_response(response)
        result = self._parse_video_info(response["data"], url, share_id)

        self._cached_video_info[share_id] = result
        self._cached_video_info[result["video_id"]] = result
        self._download_info_by_url[result["download_url"]] = result
        return result

    def get_subtitle(self, url: str) -> None:
        return None

    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        info = self.get_video_info(url)
        return VideoMetadata(
            video_id=info.get("video_id", video_id),
            platform=info.get("platform", "wechat_channels"),
            title=info.get("video_title", ""),
            author=info.get("author", ""),
            description=info.get("description", ""),
            extra={
                "username": info.get("username"),
                "share_id": info.get("share_id"),
            },
        )

    def _fetch_download_info(self, url: str, video_id: str) -> DownloadInfo:
        info = self.get_video_info(url)
        filename = info.get("filename")
        file_ext = None
        if filename and "." in filename:
            file_ext = filename.rsplit(".", 1)[-1]
        return DownloadInfo(
            download_url=info.get("download_url"),
            file_ext=file_ext,
            filename=filename,
            file_size=info.get("file_size"),
            extra={
                "decode_key": info.get("decode_key"),
                "requires_decryption": bool(info.get("decode_key")),
            },
        )

    def download_file(
        self,
        url: str,
        filename: str,
        progress_callback=None,
    ) -> Optional[str]:
        info = self._download_info_by_url.get(url, {})
        decode_key = info.get("decode_key")
        if not decode_key:
            return super().download_file(url, filename, progress_callback=progress_callback)

        with self._decrypt_service_context() as decrypt_service_url:
            encrypted_path = self._download_encrypted_file(
                url, filename, progress_callback
            )
            decrypted_path = self._decrypt_with_service(
                decrypt_service_url,
                encrypted_path,
                filename,
                decode_key,
            )

        if not self._validate_media_file(decrypted_path):
            raise ValueError("WeChat Channels decrypted media is not a valid media file")
        return decrypted_path

    def _post_tikhub_request(self, endpoint: str, payload: dict) -> dict:
        tikhub_config = dict(self.config.get("tikhub", {}) or {})
        tikhub_config["api_key"] = self.api_key
        try:
            return TikHubClient(tikhub_config).post(endpoint, payload, min_timeout=30)
        except TikHubError as exc:
            raise ValueError(f"TikHub WeChat Channels request failed: {exc}") from exc

    @staticmethod
    def _validate_response(response: dict) -> None:
        if not isinstance(response, dict):
            raise ValueError(f"TikHub response is not a dict: {type(response)}")
        if response.get("code") != 200:
            raise ValueError(
                f"TikHub returned code={response.get('code')}: "
                f"{response.get('message') or response.get('message_zh')}"
            )
        if not isinstance(response.get("data"), dict):
            raise ValueError("TikHub response missing data object")

    @staticmethod
    def _parse_video_info(data: dict, url: str, share_id: str) -> dict:
        media = data.get("media")
        if not isinstance(media, dict):
            raise ValueError("TikHub WeChat Channels response missing media object")

        download_url = media.get("full_url")
        if not download_url:
            media_url = media.get("url")
            url_token = media.get("url_token") or ""
            if media_url:
                download_url = f"{media_url}{url_token}"

        if not download_url:
            raise ValueError("TikHub WeChat Channels response missing media full_url")

        video_id = str(data.get("id") or share_id)
        title = WeChatChannelsDownloader._normalize_text(
            data.get("title"), f"wechat_channels_{video_id}"
        )
        author = WeChatChannelsDownloader._normalize_text(
            data.get("nickname") or data.get("username"), ""
        )
        description = WeChatChannelsDownloader._normalize_text(
            data.get("description") or data.get("desc"), ""
        )
        filename = f"wechat_channels_{video_id}_{int(time.time())}.mp4"

        return {
            "video_id": video_id,
            "share_id": share_id,
            "username": data.get("username"),
            "video_title": title,
            "author": author,
            "description": description,
            "download_url": download_url,
            "decode_key": media.get("decode_key"),
            "file_size": media.get("file_size"),
            "filename": filename,
            "platform": "wechat_channels",
            "source_url": url,
        }

    @staticmethod
    def _normalize_text(value: Any, fallback: str) -> str:
        """Normalize TikHub text fields that may be strings or structured spans."""
        if value is None:
            return fallback
        if isinstance(value, str):
            return value.strip() or fallback
        if isinstance(value, dict):
            for key in ("shortTitle", "title", "text", "content", "description", "desc"):
                text = WeChatChannelsDownloader._normalize_text(value.get(key), "")
                if text:
                    return text
            return fallback
        if isinstance(value, list):
            parts = [
                WeChatChannelsDownloader._normalize_text(item, "") for item in value
            ]
            text = "\n".join(part for part in parts if part)
            return text or fallback
        return str(value).strip() or fallback

    def _decrypt_service_url(self) -> str:
        configured = self.config.get("wechat_channels", {}).get("decrypt_service_url")
        return (
            configured
            or os.getenv("WECHAT_CHANNELS_DECRYPT_SERVICE_URL")
            or f"http://localhost:{_DEFAULT_DECRYPT_SERVICE_PORT}"
        ).rstrip("/")

    def _decrypt_service_context(self) -> WeChatDecryptServiceManager:
        return WeChatDecryptServiceManager(self.config)

    def _download_encrypted_file(
        self, url: str, filename: str, progress_callback=None
    ) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": "https://weixin.qq.com/",
        }
        response = requests.get(url, stream=True, timeout=60, headers=headers)
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        expected_size = int(content_length) if content_length else None
        local_path = self.temp_manager.create_temp_file(suffix=".encrypted.mp4")

        downloaded_size = 0
        with open(local_path, "wb") as file_obj:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                file_obj.write(chunk)
                downloaded_size += len(chunk)
                if progress_callback:
                    progress_callback(downloaded_size, expected_size)

        actual_size = os.path.getsize(local_path)
        if actual_size == 0:
            raise ValueError(f"Downloaded WeChat Channels file is empty: {filename}")
        return str(local_path)

    def _decrypt_with_service(
        self,
        decrypt_service_url: str,
        encrypted_path: str,
        filename: str,
        decode_key: str,
    ) -> str:
        endpoint = f"{decrypt_service_url}/api/decrypt"
        with open(encrypted_path, "rb") as encrypted_file:
            response = requests.post(
                endpoint,
                data={"decode_key": str(decode_key)},
                files={"video": (filename, encrypted_file, "video/mp4")},
                timeout=(30, 600),
                stream=True,
            )
        response.raise_for_status()

        decrypted_path = self.temp_manager.create_temp_file(suffix=".mp4")
        with open(decrypted_path, "wb") as file_obj:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file_obj.write(chunk)

        if os.path.getsize(decrypted_path) == 0:
            raise ValueError("WeChat Channels decrypt service returned an empty file")
        return str(decrypted_path)
