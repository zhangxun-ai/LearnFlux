import os
import re
import requests
import time
import contextlib
from abc import ABC, abstractmethod
from typing import Callable, Dict, Optional
from urllib.parse import urlparse, parse_qs
from .models import VideoMetadata, DownloadInfo
from ..errors import (
    DownloadFailedError,
    DownloadTimeoutError,
    InvalidMediaError,
    NetworkError,
)
from ..tikhub import TikHubClient, TikHubError
from ..utils.logging import setup_logger, load_config, ensure_dir

logger = setup_logger("downloaders")

_temp_manager = None


def get_temp_manager():
    """获取临时文件管理器单例"""
    global _temp_manager
    if _temp_manager is None:
        from ..utils.tempfile_manager import TempFileManager

        config = load_config()
        temp_dir = config.get("storage", {}).get("temp_dir", "./data/temp")
        _temp_manager = TempFileManager(temp_dir)
    return _temp_manager


class BaseDownloader(ABC):
    """
    下载器基类，定义了下载器的通用接口和功能
    """

    def __init__(self):
        self.config = load_config()
        self.api_key = self.config.get("tikhub", {}).get("api_key")
        self.temp_manager = get_temp_manager()
        # 实例级缓存（任务生命周期内有效）
        self._metadata_cache: Dict[str, VideoMetadata] = {}
        self._download_info_cache: Dict[str, DownloadInfo] = {}

    @abstractmethod
    def can_handle(self, url):
        """
        判断是否可以处理该URL

        参数:
            url: 视频URL

        返回:
            bool: 是否可以处理
        """
        pass

    @abstractmethod
    def extract_video_id(self, url: str) -> str:
        """
        提取视频ID（轻量级操作）

        参数:
            url: 视频URL

        返回:
            str: 视频ID
        """
        pass

    def get_metadata(self, url: str) -> VideoMetadata:
        """
        获取视频元数据（可能触发API请求）

        参数:
            url: 视频URL

        返回:
            VideoMetadata: 标准化元数据
        """
        video_id = self.extract_video_id(url)
        if video_id in self._metadata_cache:
            logger.info(f"使用缓存元数据: {video_id}")
            return self._metadata_cache[video_id]

        metadata = self._fetch_metadata(url, video_id)
        self._metadata_cache[video_id] = metadata
        return metadata

    @abstractmethod
    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        """子类实现：实际获取元数据的逻辑"""
        pass

    def get_download_info(self, url: str) -> DownloadInfo:
        """
        获取下载信息（可能触发API请求）

        参数:
            url: 视频URL

        返回:
            DownloadInfo: 标准化下载信息
        """
        video_id = self.extract_video_id(url)
        if video_id in self._download_info_cache:
            logger.info(f"使用缓存下载信息: {video_id}")
            return self._download_info_cache[video_id]

        download_info = self._fetch_download_info(url, video_id)
        self._download_info_cache[video_id] = download_info
        return download_info

    @abstractmethod
    def _fetch_download_info(self, url: str, video_id: str) -> DownloadInfo:
        """子类实现：实际获取下载信息的逻辑"""
        pass

    @abstractmethod
    def get_subtitle(self, url):
        """
        获取字幕，如果有的话

        参数:
            url: 视频URL

        返回:
            str: 字幕文本，如果没有则返回None
        """
        pass

    def get_video_info(self, url: str) -> dict:
        """
        兼容旧接口的 video_info 结构

        参数:
            url: 视频URL

        返回:
            dict: 兼容旧结构的视频信息
        """
        metadata = self.get_metadata(url)
        download_info = self.get_download_info(url)
        return self._build_legacy_video_info(metadata, download_info)

    def _build_legacy_video_info(
        self, metadata: VideoMetadata, download_info: DownloadInfo
    ) -> dict:
        """将标准化结构转换为旧的 video_info 字典"""
        legacy = {
            "video_id": metadata.video_id,
            "video_title": metadata.title,
            "author": metadata.author,
            "description": metadata.description,
            "download_url": download_info.download_url,
            "filename": download_info.filename,
            "platform": metadata.platform,
        }

        if download_info.file_ext:
            legacy["file_ext"] = download_info.file_ext
        if download_info.subtitle_url:
            legacy["subtitle_url"] = download_info.subtitle_url
        if download_info.local_file:
            legacy["local_file"] = download_info.local_file
        if download_info.downloaded:
            legacy["downloaded"] = True

        # 合并额外字段（避免覆盖标准键）
        for key, value in (metadata.extra or {}).items():
            if key not in legacy:
                legacy[key] = value
        for key, value in (download_info.extra or {}).items():
            if key not in legacy:
                legacy[key] = value

        return legacy

    def resolve_short_url(self, url):
        """
        解析短链接，获取原始长链接

        参数:
            url: 短链接URL

        返回:
            str: 原始长链接
        """
        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            resolved_url = response.url

            # 某些短链接服务（如 xhslink.com）不支持 HEAD，返回 404
            # 回退到 GET + stream 模式，只读取 headers 不下载 body
            if response.status_code == 404 or (resolved_url == url and response.status_code != 200):
                logger.debug(f"HEAD failed (status={response.status_code}), falling back to GET: {url}")
                response = requests.get(url, allow_redirects=True, timeout=10, stream=True)
                resolved_url = response.url
                response.close()

            return resolved_url
        except Exception as e:
            logger.error(f"解析短链接失败: {url}, 错误: {str(e)}")
            return url

    def download_file(
        self,
        url,
        filename,
        max_retries: int = 3,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    ):
        """Download file to local temp directory with retry logic.

        Args:
            url: File download URL
            filename: Target filename (used for extension detection)
            max_retries: Maximum retry attempts for retryable errors

        Returns:
            str: Local file path on success, None on failure
        """
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"downloading file (attempt {attempt}/{max_retries}): {url[:100]}...")

                # 带浏览器 User-Agent 下载；部分 CDN（如抖音）裸请求会被拒/断连
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                    )
                }
                if "douyin" in url or "zjcdn.com" in url:
                    headers["Referer"] = "https://www.douyin.com/"
                response = requests.get(url, stream=True, timeout=60, headers=headers)
                response.raise_for_status()

                content_length = response.headers.get("Content-Length")
                expected_size = int(content_length) if content_length else None
                if expected_size:
                    logger.info(f"expected file size: {expected_size / 1024 / 1024:.2f} MB")

                ext = os.path.splitext(filename)[1] if "." in filename else ".tmp"
                local_path = self.temp_manager.create_temp_file(suffix=ext)

                downloaded_size = 0
                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if progress_callback:
                                with contextlib.suppress(Exception):
                                    progress_callback(downloaded_size, expected_size)

                actual_size = os.path.getsize(local_path)
                logger.info(f"actual file size: {actual_size / 1024 / 1024:.2f} MB")

                if actual_size == 0:
                    self.temp_manager.clean_up()
                    raise DownloadFailedError(f"downloaded file is 0 bytes: {local_path}")

                if expected_size and abs(actual_size - expected_size) > 1024:
                    logger.warning(
                        f"file size mismatch - expected: {expected_size}, actual: {actual_size}"
                    )

                if not self._validate_media_file(local_path):
                    self.temp_manager.clean_up()
                    raise InvalidMediaError(f"downloaded file is not valid media: {local_path}")

                logger.info(f"file downloaded and validated: {local_path}")
                return str(local_path)

            except InvalidMediaError:
                # Invalid media is not retryable
                logger.error(f"invalid media file, not retrying: {url}")
                return None

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 403:
                    logger.error(f"HTTP 403 Forbidden, not retrying: {url}")
                    return None
                last_error = NetworkError(f"HTTP {status}: {e}")

            except requests.exceptions.Timeout as e:
                last_error = DownloadTimeoutError(f"download timed out: {e}")

            except requests.exceptions.ConnectionError as e:
                last_error = NetworkError(f"connection error: {e}")

            except DownloadFailedError as e:
                last_error = e

            except Exception as e:
                last_error = DownloadFailedError(f"unexpected error: {e}")

            # Clean up on retry
            try:
                if "local_path" in locals() and os.path.exists(local_path):
                    self.temp_manager.clean_up()
            except Exception:
                pass

            if attempt < max_retries:
                wait = 2 ** (attempt - 1)
                logger.warning(
                    f"download attempt {attempt} failed: {last_error}, retrying in {wait}s"
                )
                time.sleep(wait)

        logger.error(f"download failed after {max_retries} attempts: {url}, error: {last_error}")
        return None

    def _validate_media_file(self, file_path):
        """
        验证文件是否为有效的音视频文件

        参数:
            file_path: 文件路径

        返回:
            bool: 是否为有效的音视频文件
        """
        try:
            import subprocess

            # 使用ffprobe检查文件
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=False, timeout=30)

            if result.returncode != 0:
                logger.error(f"ffprobe检查文件失败: {file_path}")
                # 尝试解码错误输出
                try:
                    stderr_text = result.stderr.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        stderr_text = result.stderr.decode("gbk")
                    except UnicodeDecodeError:
                        stderr_text = result.stderr.decode("utf-8", errors="ignore")
                logger.error(f"ffprobe错误输出: {stderr_text}")
                return False

            # 解析ffprobe输出
            try:
                import json as json_module

                # 尝试解码标准输出
                try:
                    stdout_text = result.stdout.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        stdout_text = result.stdout.decode("gbk")
                    except UnicodeDecodeError:
                        stdout_text = result.stdout.decode("utf-8", errors="ignore")

                probe_data = json_module.loads(stdout_text)

                # 检查是否有音频或视频流
                streams = probe_data.get("streams", [])
                has_audio = any(
                    stream.get("codec_type") == "audio" for stream in streams
                )
                has_video = any(
                    stream.get("codec_type") == "video" for stream in streams
                )

                if not has_audio and not has_video:
                    logger.error(f"文件中没有找到音频或视频流: {file_path}")
                    return False

                # 获取文件时长
                format_info = probe_data.get("format", {})
                duration = format_info.get("duration")
                if duration:
                    duration_float = float(duration)
                    logger.info(f"媒体文件时长: {duration_float:.2f}秒")

                    # 检查时长是否合理（至少1秒）
                    if duration_float < 1.0:
                        logger.error(f"媒体文件时长过短: {duration_float}秒")
                        return False
                else:
                    logger.warning(f"无法获取媒体文件时长: {file_path}")

                logger.info(f"文件验证通过: 音频流={has_audio}, 视频流={has_video}")
                return True

            except Exception as parse_error:
                logger.error(f"解析ffprobe输出失败: {parse_error}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"ffprobe超时: {file_path}")
            return False
        except FileNotFoundError:
            logger.warning("ffprobe未找到，跳过媒体文件验证")
            # 如果ffprobe不可用，至少检查文件扩展名
            valid_extensions = {
                ".mp4",
                ".mp3",
                ".m4a",
                ".wav",
                ".webm",
                ".ogg",
                ".flv",
                ".avi",
                ".mkv",
            }
            file_ext = os.path.splitext(file_path)[1].lower()
            return file_ext in valid_extensions
        except Exception as e:
            logger.error(f"验证媒体文件时出错: {e}")
            return False

    def make_api_request(self, endpoint, params=None):
        """
        调用TikHub API

        参数:
            endpoint: API端点
            params: 请求参数

        返回:
            dict: API响应
        """
        tikhub_config = dict(self.config.get("tikhub", {}) or {})
        tikhub_config["api_key"] = self.api_key
        try:
            return TikHubClient(tikhub_config).get(endpoint, params)
        except TikHubError as exc:
            logger.error(f"TikHub API request failed: {exc}")
            raise ValueError(str(exc)) from exc
