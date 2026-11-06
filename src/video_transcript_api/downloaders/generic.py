import os
import re
import tempfile
import mimetypes
import hashlib
import contextlib
import requests
from urllib.parse import urlparse, unquote
from .base import BaseDownloader
from .models import VideoMetadata, DownloadInfo
from ..utils.logging import setup_logger
import datetime

# 创建日志记录器
logger = setup_logger("generic_downloader")

class GenericDownloader(BaseDownloader):
    """
    通用下载器，用于处理直接的音视频下载链接
    """

    def __init__(self):
        """
        初始化通用下载器
        """
        super().__init__()
        self._cached_video_info: dict[str, dict] = {}
        # 支持的音视频扩展名
        self.supported_audio_extensions = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.wma'}
        self.supported_video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
        self.supported_extensions = self.supported_audio_extensions | self.supported_video_extensions

        # 初始化临时文件目录
        temp_dir_config = self.config.get("storage", {}).get("temp_dir", "./data/temp")
        self.temp_dir = os.path.abspath(temp_dir_config)
        # 确保临时目录存在
        os.makedirs(self.temp_dir, exist_ok=True)

    def can_handle(self, url):
        """
        判断是否可以处理该URL
        通用下载器作为兜底，可以处理任何URL

        参数:
            url: 视频URL

        返回:
            bool: 总是返回True作为兜底处理器
        """
        return True

    def _is_media_url(self, url):
        """
        检查URL是否直接指向媒体文件

        参数:
            url: 文件URL

        返回:
            bool: 是否是媒体文件URL
        """
        try:
            parsed_url = urlparse(url)
            path = unquote(parsed_url.path.lower())

            # 检查URL路径中的文件扩展名
            _, ext = os.path.splitext(path)
            if ext in self.supported_extensions:
                return True

            # 尝试HEAD请求获取Content-Type
            try:
                response = requests.head(url, allow_redirects=True, timeout=10)
                content_type = response.headers.get('Content-Type', '').lower()

                # 检查Content-Type是否是音视频类型
                if any(media_type in content_type for media_type in ['audio/', 'video/']):
                    return True
            except:
                pass

            return False
        except Exception as e:
            logger.error(f"检查媒体URL失败: {str(e)}")
            return False

    def get_video_info(self, url):
        """
        获取视频信息
        对于通用下载器，只返回基本信息

        参数:
            url: 视频URL

        返回:
            dict: 包含视频信息的字典
        """
        logger.info(f"通用下载器处理URL: {url}")

        try:
            cache_id = self.extract_video_id(url)
            if cache_id in self._cached_video_info:
                logger.debug(f"[实例缓存命中] 使用缓存的视频信息: {cache_id}")
                return self._cached_video_info[cache_id]
        except Exception:
            cache_id = None

        # 检查是否是直接的媒体文件链接
        if self._is_media_url(url):
            logger.info(f"检测到直接媒体文件链接: {url}")

            # 从URL中尝试提取文件名
            parsed_url = urlparse(url)
            path = unquote(parsed_url.path)
            filename = os.path.basename(path)

            # 如果没有文件名或文件名不合法，生成一个
            if not filename or not any(filename.endswith(ext) for ext in self.supported_extensions):
                # 根据时间戳生成文件名
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                # 尝试从HEAD请求获取文件类型
                ext = '.mp4'  # 默认扩展名
                try:
                    response = requests.head(url, allow_redirects=True, timeout=10)
                    content_type = response.headers.get('Content-Type', '').lower()
                    # 根据Content-Type确定扩展名
                    if 'audio/mpeg' in content_type or 'audio/mp3' in content_type:
                        ext = '.mp3'
                    elif 'audio/mp4' in content_type or 'audio/m4a' in content_type:
                        ext = '.m4a'
                    elif 'audio/' in content_type:
                        ext = '.mp3'  # 默认音频格式
                    elif 'video/' in content_type:
                        ext = '.mp4'  # 默认视频格式
                except:
                    pass
                filename = f"generic_{timestamp}{ext}"

            # 返回视频信息
            result = {
                "video_title": "",  # 留空，后续由LLM生成
                "author": "",
                "description": "",
                "download_url": url,
                "filename": filename,
                "platform": "generic",
                "video_id": self.extract_video_id(url),
                "is_generic": True  # 标记为通用下载
            }
            if cache_id:
                self._cached_video_info[cache_id] = result
            return result
        else:
            # 对于非直接媒体链接，尝试作为网页处理
            logger.warning(f"URL不是直接媒体文件链接，尝试作为网页处理: {url}")

            # 这里可以添加网页解析逻辑，尝试从网页中提取媒体链接
            # 目前暂时返回错误
            raise ValueError(f"无法处理该URL，不是有效的媒体文件链接: {url}")

    def get_subtitle(self, url):
        """
        获取字幕
        通用下载器不支持字幕

        参数:
            url: 视频URL

        返回:
            None
        """
        return None

    def extract_video_id(self, url):
        """
        提取视频ID
        对于通用URL，使用URL哈希作为ID

        参数:
            url: 视频URL

        返回:
            str: 视频ID
        """
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def download_file(self, url, filename, progress_callback=None):
        """Stream media into a file owned by this download, resuming interrupted transfers.

        Args:
            url: Media download URL.
            filename: Original filename used to preserve the media extension.
            progress_callback: Optional callback for downloaded and total bytes.

        Returns:
            Temporary file path on success, or None if the download failed.
        """
        with tempfile.NamedTemporaryFile(
            dir=self.temp_dir, prefix="generic-", suffix=os.path.splitext(filename)[1], delete=False,
        ) as staging:
            local_path = staging.name

        etag = None
        for attempt in range(1, 4):
            try:
                headers = {"Accept-Encoding": "identity"}
                initial_pos = os.path.getsize(local_path) if etag else 0
                if initial_pos:
                    headers.update({"Range": f"bytes={initial_pos}-", "If-Range": etag})

                with requests.get(url, headers=headers, stream=True, timeout=(30, 300)) as response:
                    if response.status_code == 416 and initial_pos:
                        etag = None
                        continue
                    response.raise_for_status()

                    identity = response.headers.get("Content-Encoding", "identity").lower() == "identity"
                    response_etag = response.headers.get("ETag", "")
                    content_length = response.headers.get("Content-Length")
                    if response.status_code == 206:
                        content_range = re.fullmatch(
                            r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""),
                        )
                        if (
                            not initial_pos or not identity or not content_range
                            or (response_etag and response_etag != etag)
                        ):
                            etag = None
                            continue
                        start, end, total_size = map(int, content_range.groups())
                        if start != initial_pos or end != total_size - 1 or end < start:
                            etag = None
                            continue
                        next_etag = etag
                    elif response.status_code == 200:
                        # A server may ignore Range or return a new representation.
                        initial_pos = 0
                        total_size = int(content_length) if content_length and identity else None
                        next_etag = response_etag if identity and re.fullmatch(r'"[^"]*"', response_etag) else None
                    else:
                        raise ValueError(f"unexpected download HTTP status {response.status_code}")

                    downloaded = initial_pos
                    with open(local_path, "ab" if initial_pos else "wb") as target:
                        etag = next_etag
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            target.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                with contextlib.suppress(Exception):
                                    progress_callback(downloaded, total_size)

                    if downloaded and (total_size is None or downloaded == total_size):
                        logger.info(f"Media download complete: {downloaded} bytes")
                        return local_path
                    if total_size is not None and downloaded > total_size:
                        etag = None
                    logger.warning(f"Incomplete media download: {downloaded} of {total_size} bytes")
            except (requests.RequestException, OSError, ValueError) as exc:
                logger.warning(f"Media download attempt {attempt}/3 failed: {type(exc).__name__}")

        with contextlib.suppress(OSError):
            os.unlink(local_path)
        return None

    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        info = self.get_video_info(url)
        return VideoMetadata(
            video_id=info.get("video_id", video_id),
            platform=info.get("platform", "generic"),
            title=info.get("video_title", ""),
            author=info.get("author", ""),
            description=info.get("description", ""),
            extra={"is_generic": True},
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
        )
