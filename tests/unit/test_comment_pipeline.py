"""Unit tests for comment insight pipeline.

All console output must be in English only.
"""

from video_transcript_api.comments.pipeline import generate_comment_insight
from video_transcript_api.comments.selector import CommentItem


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def fetch_hot_comments(self, **kwargs):
        self.calls.append(kwargs)
        return [
            CommentItem(text="哈哈", like_count=999, platform_rank=0),
            CommentItem(text="导出格式不稳定，这是我最大的使用顾虑", like_count=120, reply_count=8, platform_rank=1),
            CommentItem(text="价格如果能低一点我会马上买", like_count=80, reply_count=3, platform_rank=2),
            CommentItem(text="导出格式不稳定，这是我最大的使用顾虑", like_count=70, platform_rank=3),
        ]


class FakeAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return "## 评论区核心共识\n用户关注导出稳定性和价格。"


def test_generate_comment_insight_filters_samples_before_analysis():
    fetcher = FakeFetcher()
    analyzer = FakeAnalyzer()

    result = generate_comment_insight(
        url="https://www.youtube.com/watch?v=abc123",
        platform="youtube",
        media_id="abc123",
        title="AI 工具演示",
        author="tester",
        summary_text="视频介绍了一个 AI 工具。",
        fetch_limit=100,
        analysis_limit=50,
        fetcher=fetcher,
        analyzer=analyzer,
    )

    assert result["insight_text"].startswith("## 评论区核心共识")
    assert result["fetched_count"] == 4
    assert result["selected_count"] == 2
    assert [sample["text"] for sample in result["samples"]] == [
        "导出格式不稳定，这是我最大的使用顾虑",
        "价格如果能低一点我会马上买",
    ]
    assert fetcher.calls[0]["limit"] == 100
    assert analyzer.calls[0]["comments"][0].like_count == 120
