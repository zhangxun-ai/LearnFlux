import os
import re
import json
import time
import datetime
from .base import BaseDownloader
from .models import VideoMetadata, DownloadInfo
from ..utils.logging import setup_logger
from ..utils import create_debug_dir

# 创建日志记录器
logger = setup_logger("douyin_downloader")
# 创建调试目录
DEBUG_DIR = create_debug_dir()

class DouyinDownloader(BaseDownloader):
    """
    抖音视频下载器
    """
    def __init__(self):
        super().__init__()
        self._cached_video_info: dict[str, dict] = {}

    def can_handle(self, url):
        """
        判断是否可以处理该URL

        参数:
            url: 视频URL

        返回:
            bool: 是否可以处理
        """
        return "douyin.com" in url or "v.douyin.com" in url

    def extract_video_id(self, url):
        """
        从URL中提取视频ID的公共方法

        参数:
            url: 视频URL
        返回:
            str: 视频ID
        """
        return self._extract_aweme_id(url)

    def _extract_aweme_id(self, url):
        """
        从URL中提取视频ID

        参数:
            url: 视频URL

        返回:
            str: 视频ID
        """
        # 解析短链接
        if "v.douyin.com" in url:
            logger.info(f"解析抖音短链接: {url}")
            url = self.resolve_short_url(url)
            logger.info(f"解析后的完整链接: {url}")

        # 尝试多种模式提取视频ID
        patterns = [
            r'video/(\d+)',      # 标准URL模式
            r'note/(\d+)',       # 笔记模式
            r'(?:aweme_id|modal_id)=(\d+)',   # 查询参数模式
            r'/(\d+)(?:\?|$)'    # 路径末尾模式
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                aweme_id = match.group(1)
                logger.info(f"从URL中提取到抖音视频ID: {aweme_id}")
                return aweme_id

        logger.error(f"无法从URL中提取抖音视频ID: {url}")
        raise ValueError(f"无法从URL中提取抖音视频ID: {url}")

    def _first_reachable_url(self, urls):
        """逐个预检候选下载 URL，返回第一个可达(HTTP<400)的地址；用于跳过被 CDN/网络拒绝的链接。"""
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douyin.com/",
        }
        for u in urls:
            if not u:
                continue
            try:
                resp = requests.get(u, headers=headers, stream=True, timeout=8)
                status = resp.status_code
                resp.close()
                if status < 400:
                    return u
                logger.warning(f"候选下载URL返回 {status}，跳过: {u[:60]}...")
            except Exception as e:
                logger.warning(f"候选下载URL不可达，跳过: {u[:50]}... ({type(e).__name__})")
        return None

    def get_video_info(self, url):
        """
        获取视频信息

        参数:
            url: 视频URL

        返回:
            dict: 包含视频信息的字典
        """
        try:
            # 提取视频ID
            aweme_id = self._extract_aweme_id(url)

            # 实例缓存命中
            if aweme_id in self._cached_video_info:
                logger.debug(f"[实例缓存命中] 使用缓存的视频信息: {aweme_id}")
                return self._cached_video_info[aweme_id]

            # 调用API获取视频信息
            endpoint = f"/api/v1/douyin/web/fetch_one_video"
            params = {"aweme_id": aweme_id}

            logger.info(f"调用TikHub API获取抖音视频信息: aweme_id={aweme_id}")
            response = self.make_api_request(endpoint, params)

            # 生成时间戳前缀
            timestamp_prefix = datetime.datetime.now().strftime("%y%m%d-%H%M%S")

            # 记录API响应摘要，帮助调试
            if isinstance(response, dict):
                response_code = response.get("code")
                response_msg = response.get("message", "无消息")
                logger.info(f"API响应状态: {response_code}, 消息: {response_msg}")

                # 保存完整响应到文件，用于调试
                debug_file = os.path.join(DEBUG_DIR, f"{timestamp_prefix}_debug_douyin_{aweme_id}.json")
                with open(debug_file, 'w', encoding='utf-8') as f:
                    json.dump(response, f, ensure_ascii=False, indent=2)
                logger.debug(f"API完整响应已保存到: {debug_file}")

            # 检查响应格式并提供详细错误信息
            if not isinstance(response, dict):
                logger.error(f"API返回格式错误，预期字典，实际: {type(response)}")
                raise ValueError("API返回格式错误，无法解析响应")

            # TikHub API成功响应时返回code=200
            if response.get("code") != 200:
                error_msg = response.get("message", "未知错误")
                logger.error(f"API返回错误代码: {response.get('code')}, 错误信息: {error_msg}")

                # 保存错误响应到文件
                error_file = os.path.join(DEBUG_DIR, f"{timestamp_prefix}_error_douyin_{aweme_id}.json")
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump(response, f, ensure_ascii=False, indent=2)
                logger.debug(f"错误响应已保存到: {error_file}")

                raise ValueError(f"获取抖音视频信息失败: {error_msg}")

            # 检查data字段
            if not response.get("data") or not isinstance(response.get("data"), dict):
                logger.error("API响应中缺少data字段或格式不正确")
                raise ValueError("API响应数据格式错误，缺少必要字段")

            # 获取视频详情数据
            data = response.get("data", {}).get("aweme_detail", {})

            if not data:
                logger.error("无法获取视频详情数据: aweme_detail为空")
                # 记录完整响应以帮助调试
                logger.debug(f"API完整响应: {json.dumps(response, ensure_ascii=False)[:500]}...")

                # 保存错误响应到文件
                error_file = os.path.join(DEBUG_DIR, f"{timestamp_prefix}_error_data_douyin_{aweme_id}.json")
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump(response, f, ensure_ascii=False, indent=2)

                raise ValueError("获取视频详情失败，API返回数据结构不符合预期")

            # 视频标题
            video_title = data.get("desc", "")
            if not video_title or video_title.strip() == "":
                video_title = f"douyin_{aweme_id}"
                logger.warning(f"未找到视频标题，使用ID作为标题: {video_title}")

            # 视频作者
            author = data.get("author", {}).get("nickname", "未知作者")

            # 视频描述 - 抖音的视频标题和描述是同一个字段(desc)
            description = data.get("desc", "")

            logger.info(f"获取到视频信息: 标题='{video_title}', 作者='{author}', 描述长度={len(description)}")

            # 构建候选下载 URL 列表（音频优先；逐个做可达性预检，自动跳过被 CDN/网络拒绝的地址）
            # 背景：music.play_url 在某些网络下 CDN(douyinstatic) 直接 TLS 断连，需回退到 video CDN(zjcdn)
            candidates = []  # [(url, ext), ...]
            try:
                audio_url = data.get("music", {}).get("play_url", {}).get("uri")
                if audio_url:
                    candidates.append((audio_url, "mp3"))
            except Exception as audio_error:
                logger.warning(f"获取音频URL时出现异常: {str(audio_error)}")

            for path in (
                ("video", "play_addr", "url_list"),
                ("video", "play_addr_h264", "url_list"),
                ("video", "download_addr", "url_list"),
            ):
                try:
                    current = data
                    for key in path:
                        current = current.get(key) if isinstance(current, dict) else None
                        if current is None:
                            break
                    if isinstance(current, list):
                        for u in current:
                            if u:
                                candidates.append((u, "mp4"))
                except Exception:
                    continue

            # 逐个预检，选第一个可达的（music 不可达时自动回退到 video CDN）
            download_url = None
            file_ext = "mp4"
            reachable = self._first_reachable_url([u for u, _ in candidates])
            if reachable:
                download_url = reachable
                file_ext = dict(candidates).get(reachable, "mp4")
                logger.info(f"选用可达下载URL (ext={file_ext}): {download_url[:60]}...")

            if not download_url:
                logger.error("尝试所有候选后仍无法获取可达的下载URL")

                # 保存错误数据到文件
                error_file = os.path.join(DEBUG_DIR, f"{timestamp_prefix}_error_url_douyin_{aweme_id}.json")
                with open(error_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                raise ValueError(f"无法获取抖音视频可达下载地址: {url}")

            # 清理文件名中的非法字符
            safe_title = re.sub(r'[\\/*?:"<>|]', "_", video_title)
            filename = f"douyin_{aweme_id}_{int(time.time())}.{file_ext}"

            result = {
                "video_id": aweme_id,
                "video_title": video_title,
                "author": author,
                "description": description,
                "download_url": download_url,
                "filename": filename,
                "platform": "douyin"
            }

            self._cached_video_info[aweme_id] = result
            logger.info(f"成功获取抖音视频信息: ID={aweme_id}, 文件类型={file_ext}")
            return result

        except Exception as e:
            logger.exception(f"获取抖音视频信息异常: {str(e)}")
            raise

    def get_subtitle(self, url):
        """
        获取字幕，抖音视频通常没有字幕，返回None

        参数:
            url: 视频URL

        返回:
            str: 字幕文本，抖音通常返回None
        """
        # 直接返回None，跳过尝试获取字幕步骤
        return None

    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        info = self.get_video_info(url)
        return VideoMetadata(
            video_id=info.get("video_id", video_id),
            platform=info.get("platform", "douyin"),
            title=info.get("video_title", ""),
            author=info.get("author", ""),
            description=info.get("description", ""),
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
