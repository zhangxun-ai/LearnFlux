"""Unit tests for comment insight selection.

All console output must be in English only.
"""

from video_transcript_api.comments.selector import (
    CommentItem,
    format_comments_for_llm,
    select_high_value_comments,
)


def test_select_high_value_comments_filters_noise_and_keeps_hot_order():
    comments = [
        CommentItem(text="哈哈哈", like_count=999, reply_count=0, platform_rank=0),
        CommentItem(text="这个工具实际使用门槛高吗？有没有本地部署教程", like_count=120, reply_count=8, platform_rank=1),
        CommentItem(text="我试了同类工具，最大的痛点是导出格式不稳定", like_count=90, reply_count=12, platform_rank=2),
        CommentItem(text="我试了同类工具，最大的痛点是导出格式不稳定", like_count=80, reply_count=1, platform_rank=3),
        CommentItem(text="种草了，想知道价格和免费额度", like_count=70, reply_count=3, platform_rank=4),
    ]

    selected = select_high_value_comments(comments, max_items=3)

    assert [item.text for item in selected] == [
        "这个工具实际使用门槛高吗？有没有本地部署教程",
        "我试了同类工具，最大的痛点是导出格式不稳定",
        "种草了，想知道价格和免费额度",
    ]


def test_format_comments_for_llm_limits_count_and_text_length():
    comments = [
        CommentItem(
            text="这个评论很长" * 80,
            like_count=42,
            reply_count=5,
            user_nickname="user-a",
            platform_rank=0,
        )
    ]

    formatted = format_comments_for_llm(comments, max_items=1, max_text_length=30)

    assert "点赞 42" in formatted
    assert "回复 5" in formatted
    assert "user-a" in formatted
    assert "..." in formatted
    assert len(formatted) < 120
