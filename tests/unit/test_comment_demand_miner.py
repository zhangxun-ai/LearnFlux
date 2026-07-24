"""Unit tests for comment demand mining."""

from src.video_transcript_api.comments.demand_miner import (
    format_demand_signals_for_llm,
    mine_comment_demands,
)
from src.video_transcript_api.comments.selector import CommentItem


def test_mines_core_demand_categories():
    comments = [
        CommentItem(text="这个流程太麻烦了，经常卡在导入那里", like_count=30, user_nickname="a", platform_rank=0),
        CommentItem(text="请问具体怎么做，有没有一步步教程？", like_count=18, user_nickname="b", platform_rank=1),
        CommentItem(text="不太认同，问题是样本太少了", like_count=22, user_nickname="c", platform_rank=2),
        CommentItem(text="哪里买？价格多少？有链接吗", like_count=15, user_nickname="d", platform_rank=3),
        CommentItem(text="求自动化工具或者脚本", like_count=12, user_nickname="e", platform_rank=4),
        CommentItem(text="哈哈哈", like_count=999, user_nickname="noise", platform_rank=5),
    ]

    signals = mine_comment_demands(comments)

    assert signals["pain_points"][0]["text"] == "这个流程太麻烦了，经常卡在导入那里"
    assert signals["questions"][0]["text"] == "请问具体怎么做，有没有一步步教程？"
    assert signals["objections"][0]["text"] == "不太认同，问题是样本太少了"
    assert signals["purchase_intent"][0]["text"] == "哪里买？价格多少？有链接吗"
    assert signals["tutorial_requests"][0]["text"] == "请问具体怎么做，有没有一步步教程？"
    assert signals["tool_requests"][0]["text"] == "求自动化工具或者脚本"
    assert all(item["user_nickname"] != "noise" for group in signals.values() for item in group)


def test_caps_each_category_and_sorts_by_likes():
    comments = [
        CommentItem(text=f"这个工具太难用了，怎么解决 {i}", like_count=i, platform_rank=i)
        for i in range(10)
    ]

    signals = mine_comment_demands(comments, max_items_per_category=3)

    assert [item["like_count"] for item in signals["pain_points"]] == [9, 8, 7]
    assert len(signals["questions"]) == 3


def test_formats_demand_signals_for_llm():
    signals = mine_comment_demands(
        [
            CommentItem(text="求一份可直接复制的模板", like_count=8, user_nickname="alice"),
            CommentItem(text="这个软件有没有自动化 API？", like_count=7, user_nickname="bob"),
        ]
    )

    formatted = format_demand_signals_for_llm(signals)

    assert "评论需求矿场" in formatted
    assert "教程/模板需求" in formatted
    assert "工具/自动化需求" in formatted
    assert "@alice" in formatted
    assert "@bob" in formatted


def test_empty_comments_return_empty_categories():
    signals = mine_comment_demands([])

    assert set(signals) == {
        "pain_points",
        "questions",
        "objections",
        "purchase_intent",
        "tutorial_requests",
        "tool_requests",
    }
    assert all(items == [] for items in signals.values())
    assert "暂无明显需求信号" in format_demand_signals_for_llm(signals)
