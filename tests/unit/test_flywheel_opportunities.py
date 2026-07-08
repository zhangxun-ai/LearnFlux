"""Unit tests for flywheel opportunity ranking."""

from datetime import datetime, timedelta

from src.video_transcript_api.flywheel.models import (
    AnalysisStatus,
    Content,
    ContentSource,
    MediaType,
)
from src.video_transcript_api.flywheel.opportunities import build_opportunity


def _content(**overrides):
    data = {
        "id": 1,
        "blogger_id": 7,
        "platform": "xiaohongshu",
        "platform_item_id": "n1",
        "media_type": MediaType.ARTICLE,
        "title": "3 个 AI 自动化模板",
        "original_url": "https://x/n1",
        "published_at": datetime.now() - timedelta(days=3),
        "like_count": 3600,
        "collect_count": 2200,
        "comment_count": 420,
        "share_count": 80,
        "source": ContentSource.FEED,
        "analysis_status": AnalysisStatus.SUCCESS,
    }
    data.update(overrides)
    return Content(**data)


def test_build_opportunity_scores_high_signal_content():
    analysis = {
        "one_thing": "把模板下载需求做成一条清单帖。",
        "sections": [
            {
                "title": "10 可复制模板",
                "body": "标题模板、首屏模板和正文结构都可以直接迁移。",
            },
            {
                "title": "12 下一条怎么插接",
                "body": "选题：AI 自动化清单。标题：别再手动整理资料。",
            },
        ],
    }

    item = build_opportunity(_content(), analysis, blogger_handle="@阿K")

    assert item["score"] >= 80
    assert item["level"] == "high"
    assert item["opportunity_type"] == "template"
    assert "收藏" in item["reason"]
    assert item["next_action"] == "把模板下载需求做成一条清单帖。"
    assert item["blogger_handle"] == "@阿K"


def test_build_opportunity_detects_product_or_tool_angle():
    analysis = {
        "one_thing": "做一个自动化工具试用入口。",
        "sections": [
            {"title": "机会判断", "body": "评论区持续追问工具、插件、API 和自动化脚本。"},
        ],
    }

    item = build_opportunity(
        _content(like_count=900, collect_count=100, comment_count=80),
        analysis,
        blogger_handle="@工具号",
    )

    assert item["opportunity_type"] == "product"
    assert "自动化工具" in item["next_action"]


def test_low_signal_content_gets_low_level():
    item = build_opportunity(
        _content(like_count=10, collect_count=2, comment_count=1, published_at=None),
        {"sections": [], "one_thing": ""},
        blogger_handle="",
    )

    assert item["score"] < 45
    assert item["level"] == "low"
    assert item["next_action"]
