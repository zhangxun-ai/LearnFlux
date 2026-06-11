"""
Downloader factory and platform handler tests.

Covers:
- Factory creates correct downloader for each platform URL
- Unknown URLs get GenericDownloader (fallback)
- Platform-specific can_handle and extract methods

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys
import unittest


from video_transcript_api.downloaders import create_downloader
from video_transcript_api.downloaders.douyin import DouyinDownloader
from video_transcript_api.downloaders.bilibili import BilibiliDownloader
from video_transcript_api.downloaders.xiaohongshu import XiaohongshuDownloader
from video_transcript_api.downloaders.youtube import YoutubeDownloader
from video_transcript_api.downloaders.xiaoyuzhou import XiaoyuzhouDownloader
from video_transcript_api.downloaders.generic import GenericDownloader


class TestDownloaderFactory(unittest.TestCase):
    """Test downloader factory routing."""

    def test_create_downloader_douyin(self):
        """Douyin URL should create DouyinDownloader."""
        downloader = create_downloader("https://v.douyin.com/sample")
        self.assertIsInstance(downloader, DouyinDownloader)

    def test_create_downloader_bilibili(self):
        """Bilibili URL should create BilibiliDownloader."""
        downloader = create_downloader("https://www.bilibili.com/video/BV1234")
        self.assertIsInstance(downloader, BilibiliDownloader)

    def test_create_downloader_xiaohongshu(self):
        """Xiaohongshu URL should create XiaohongshuDownloader."""
        downloader = create_downloader("https://www.xiaohongshu.com/explore/12345")
        self.assertIsInstance(downloader, XiaohongshuDownloader)

    def test_create_downloader_youtube(self):
        """YouTube URL should create YoutubeDownloader."""
        downloader = create_downloader("https://www.youtube.com/watch?v=12345")
        self.assertIsInstance(downloader, YoutubeDownloader)

    def test_create_downloader_xiaoyuzhou(self):
        """Xiaoyuzhou URL should create XiaoyuzhouDownloader."""
        downloader = create_downloader("https://www.xiaoyuzhoufm.com/episode/687893e0a12f9ff06a98a597")
        self.assertIsInstance(downloader, XiaoyuzhouDownloader)

    def test_create_downloader_unsupported_returns_generic(self):
        """Unknown URL should return GenericDownloader (not None)."""
        downloader = create_downloader("https://www.unsupported.com/video/12345")
        self.assertIsInstance(downloader, GenericDownloader)


class TestDouyinDownloaderBasic(unittest.TestCase):
    """Test Douyin downloader basic methods (no network)."""

    def test_extract_video_id_from_modal_url(self):
        """Should extract video ID from Douyin modal URL."""
        downloader = DouyinDownloader()
        video_id = downloader.extract_video_id(
            "https://www.douyin.com/user/self?from_tab_name=main"
            "&modal_id=7616674906457050408&showSubTab=video&showTab=record"
        )
        self.assertEqual(video_id, "7616674906457050408")


class TestXiaoyuzhouDownloaderBasic(unittest.TestCase):
    """Test Xiaoyuzhou downloader basic methods (no network)."""

    def test_can_handle(self):
        """Should handle xiaoyuzhoufm.com URLs."""
        downloader = XiaoyuzhouDownloader()
        self.assertTrue(downloader.can_handle("https://www.xiaoyuzhoufm.com/episode/12345"))
        self.assertFalse(downloader.can_handle("https://www.youtube.com/watch?v=12345"))
        self.assertFalse(downloader.can_handle("https://www.bilibili.com/video/BV12345"))

    def test_extract_episode_id(self):
        """Should extract episode ID from URL."""
        downloader = XiaoyuzhouDownloader()
        episode_id = downloader._extract_episode_id(
            "https://www.xiaoyuzhoufm.com/episode/687893e0a12f9ff06a98a597"
        )
        self.assertEqual(episode_id, "687893e0a12f9ff06a98a597")

    def test_extract_episode_id_invalid(self):
        """Invalid URL should raise ValueError."""
        downloader = XiaoyuzhouDownloader()
        with self.assertRaises(ValueError):
            downloader._extract_episode_id("https://www.example.com/invalid")

    def test_get_subtitle(self):
        """Xiaoyuzhou has no subtitle support."""
        downloader = XiaoyuzhouDownloader()
        result = downloader.get_subtitle("https://www.xiaoyuzhoufm.com/episode/12345")
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
