"""Unit tests for comment insight analyzer.

All console output must be in English only.
"""

from video_transcript_api.comments.analyzer import CommentInsightAnalyzer
from video_transcript_api.comments.selector import CommentItem


class FakeLLMClient:
    def __init__(self):
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)

        class Response:
            text = "## 评论区核心共识\n用户主要在讨论工具使用反馈。"

        return Response()


def test_comment_analyzer_uses_adaptive_prompt_and_summary_model():
    comments = [
        CommentItem(text="导出格式不稳定是最大痛点", like_count=100, reply_count=8),
        CommentItem(text="种草了，想知道价格", like_count=80, reply_count=3),
    ]
    client = FakeLLMClient()
    analyzer = CommentInsightAnalyzer(
        llm_client=client,
        model="summary-model",
        reasoning_effort="high",
    )

    result = analyzer.analyze(
        title="AI 工具演示",
        author="tester",
        summary_text="视频介绍了一个 AI 工具的转录和导出能力。",
        comments=comments,
    )

    assert result.startswith("## 评论区核心共识")
    assert client.calls[0]["model"] == "summary-model"
    assert client.calls[0]["reasoning_effort"] == "high"
    assert client.calls[0]["task_type"] == "comment_insight"
    assert "不要预设评论价值类型" in client.calls[0]["system_prompt"]
    assert "导出格式不稳定" in client.calls[0]["user_prompt"]
