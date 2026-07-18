"""Unit tests for PostInsightAnalyzer (X post content + replies, credibility-aware)."""

import types

from src.video_transcript_api.comments.post_analyzer import (
    POST_INSIGHT_SYSTEM_PROMPT,
    PostInsightAnalyzer,
)
from src.video_transcript_api.comments.selector import CommentItem


class _FakeLLM:
    def __init__(self, text="## 正文核心主张\nok"):
        self.text_out = text
        self.last = None

    def call(self, **kwargs):
        self.last = kwargs
        return types.SimpleNamespace(text=self.text_out)


def test_uses_post_prompt_and_includes_thread_and_replies():
    llm = _FakeLLM()
    analyzer = PostInsightAnalyzer(llm, model="m")
    out = analyzer.analyze(
        title="How to Get Rich",
        author="naval",
        summary_text="Seek wealth, not money.",
        comments=[CommentItem(text="实测有效的反驳", like_count=10, platform_rank=0)],
        demand_signals={
            "pain_points": [
                {
                    "text": "这个方法太难执行了",
                    "like_count": 12,
                    "user_nickname": "alice",
                }
            ]
        },
    )
    assert out == "## 正文核心主张\nok"
    # post-specific system prompt, not the video/comment one
    assert llm.last["system_prompt"] is POST_INSIGHT_SYSTEM_PROMPT
    assert "可信度" in llm.last["system_prompt"]
    assert "评论需求矿场" in llm.last["system_prompt"]
    assert "机会判断" in llm.last["system_prompt"]
    assert llm.last["task_type"] == "post_insight"
    # user prompt carries both the author thread and the replies
    assert "Seek wealth, not money." in llm.last["user_prompt"]
    assert "实测有效的反驳" in llm.last["user_prompt"]
    assert "这个方法太难执行了" in llm.last["user_prompt"]


def test_works_without_comments():
    llm = _FakeLLM()
    analyzer = PostInsightAnalyzer(llm, model="m")
    out = analyzer.analyze(
        title="t", author="alice", summary_text="只有正文，没有回复", comments=[]
    )
    assert out  # content alone still yields analysis
    assert "只有正文，没有回复" in llm.last["user_prompt"]
    assert "暂无明显需求信号" in llm.last["user_prompt"]


def test_empty_llm_text_returns_none():
    llm = _FakeLLM(text="")
    analyzer = PostInsightAnalyzer(llm, model="m")
    assert analyzer.analyze(title="t", author="a", summary_text="x", comments=[]) is None
