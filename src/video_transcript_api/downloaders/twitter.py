"""Resolve X post videos through the shared TikHub REST client."""

import re
from typing import Any
from urllib.parse import urlsplit

from .base import BaseDownloader
from .models import DownloadInfo, VideoMetadata


class TwitterDownloader(BaseDownloader):
    """Keep post text as metadata and expose only actual video as media."""

    def __init__(self):
        super().__init__()
        self._details: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _match(url: str) -> re.Match[str] | None:
        parsed = urlsplit(url)
        if (parsed.hostname or "").lower() not in {
            "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
        }:
            return None
        path = re.sub(r"/photo/[1-9]\d*/?$", "", parsed.path)
        return re.fullmatch(r"/[^/]+/status/(\d+)(?:/video/([1-9]\d*))?/?", path)

    def can_handle(self, url: str) -> bool:
        return self._match(url) is not None

    def extract_video_id(self, url: str) -> str:
        match = self._match(url)
        if not match:
            raise ValueError("Invalid X post URL")
        return match[1]

    def _detail(self, url: str) -> dict[str, Any]:
        tweet_id = self.extract_video_id(url)
        if tweet_id not in self._details:
            response = self.make_api_request(
                "/api/v1/twitter/web/fetch_tweet_detail", {"tweet_id": tweet_id}
            )
            if not isinstance(response, dict) or response.get("code") not in (None, 0, 200):
                raise ValueError("X post detail request failed")
            data = response.get("data")
            if not isinstance(data, dict) or not data:
                raise ValueError("X post detail is unavailable")
            self._details[tweet_id] = data
        return self._details[tweet_id]

    @staticmethod
    def _videos(data: dict[str, Any]) -> list[dict[str, Any]]:
        # Prefer entities: its ordering matches the /video/N links. TikHub's
        # normalized media.video is a fallback for responses without entities.
        for key in ("extended_entities", "entities"):
            entities = data.get(key)
            if isinstance(entities, dict):
                videos = [
                    item for item in entities.get("media") or []
                    if isinstance(item, dict) and item.get("type") == "video"
                ]
                if videos:
                    return videos
        media = data.get("media")
        if isinstance(media, dict) and isinstance(media.get("video"), list):
            videos = [item for item in media["video"] if isinstance(item, dict)]
            if videos:
                return videos
        # An embedded/quoted video can belong to another post. Never inspect
        # conversation replies: those are unrelated videos.
        quoted = data.get("quoted")
        if isinstance(quoted, dict):
            return TwitterDownloader._videos(quoted)
        return []

    def _selected_video(self, url: str) -> tuple[dict[str, Any] | None, int]:
        match = self._match(url)
        index = int(match[2] or 1)
        videos = self._videos(self._detail(url))
        indexed = {}
        for item in videos:
            selected = re.search(
                r"/video/(\d+)(?:[/?#]|$)", str(item.get("expanded_url") or "")
            )
            if selected:
                indexed[int(selected[1])] = item
        if match[2] and indexed:
            if index not in indexed:
                raise ValueError("X 链接指定的视频不存在或无法读取，未改用帖子正文")
            return indexed[index], index
        if not match[2] and indexed:
            index = min(indexed)
            return indexed[index], index
        if index > len(videos):
            if match[2]:
                raise ValueError("X 链接指定的视频不存在或无法读取，未改用帖子正文")
            return None, index
        return videos[index - 1], index

    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        data = self._detail(url)
        video, index = self._selected_video(url)
        text = str(data.get("display_text") or data.get("text") or "").strip()
        author_data = data.get("author") or {}
        author = author_data.get("screen_name") or author_data.get("name") or "Unknown"
        info = (video.get("video_info") or video) if video is not None else {}
        duration_ms = info.get("duration_millis", info.get("duration"))
        return VideoMetadata(
            # A distinct namespace prevents old post-text caches and LLM files
            # from being reused as video transcripts, including /video/2 etc.
            video_id=f"{video_id}_video_{index}" if video is not None else video_id,
            platform="twitter",
            title=text.splitlines()[0][:120] if text else f"X 视频 {video_id}",
            author=author,
            description=text,
            duration=float(duration_ms) / 1000 if duration_ms is not None else None,
            extra={"media_type": "video" if video is not None else "article"},
        )

    def _fetch_download_info(self, url: str, video_id: str) -> DownloadInfo:
        video, index = self._selected_video(url)
        if video is None:
            raise ValueError("X 帖子中没有可转录的视频")
        info = video.get("video_info") or video
        variants = [
            item for item in info.get("variants") or []
            if isinstance(item, dict) and item.get("content_type") == "video/mp4"
            and isinstance(item.get("url"), str)
            and urlsplit(item["url"]).scheme == "https"
            and urlsplit(item["url"]).hostname == "video.twimg.com"
        ]
        if not variants:
            raise ValueError("无法获取 X 视频的 MP4 播放地址，未改用帖子正文")
        selected = max(variants, key=lambda item: int(item.get("bitrate") or 0))
        return DownloadInfo(
            download_url=selected["url"],
            file_ext="mp4",
            filename=f"twitter_{video_id}_video_{index}.mp4",
        )

    def get_subtitle(self, url: str) -> str | None:
        """Post descriptions are never subtitles; use the selected ASR path."""
        return None

    def get_metadata(self, url: str) -> VideoMetadata:
        # BaseDownloader caches by tweet id, which loses the /video/N selector.
        if url not in self._metadata_cache:
            self._metadata_cache[url] = self._fetch_metadata(
                url, self.extract_video_id(url)
            )
        return self._metadata_cache[url]

    def get_download_info(self, url: str) -> DownloadInfo:
        if url not in self._download_info_cache:
            self._download_info_cache[url] = self._fetch_download_info(
                url, self.extract_video_id(url)
            )
        return self._download_info_cache[url]
