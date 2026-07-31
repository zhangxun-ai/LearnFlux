"""Unit tests for post-insight presentation logic (markdown -> sections + chips)."""

from pathlib import Path

from src.video_transcript_api.api.routes.post_insight import build_insight_sections


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POST_TEMPLATE = PROJECT_ROOT / "src/web/templates/post_insight.html"

_SAMPLE = """## 正文核心主张
作者认为财富来自资产而非出卖时间。

## 可信度与存疑点
[共识/可信] 复利效应有大量实证。
[单方面断言] "出租时间不可能致富"过于绝对。
[需外部核实] "道德财富可能"需更多论证。
[回复区有反驳] 有人指出反例。

## 评论需求矿场
- 痛点：执行成本高。
- 工具需求：需要模板和自动化工具。

## 机会判断
可以围绕低门槛资产积累清单做选题。

## 代表性高赞回复
@someone 很受启发。

## 对你的可行动启发
- 优先积累可产生睡后收入的资产。
"""


def test_splits_into_known_sections():
    sections = build_insight_sections(_SAMPLE)
    keys = [s["key"] for s in sections]
    assert keys == [
        "claims",
        "credibility",
        "demand_mine",
        "opportunity",
        "representative",
        "actions",
    ]
    for s in sections:
        assert s["title"]
        assert isinstance(s["html"], str) and s["html"]


def test_credibility_labels_become_chips():
    sections = build_insight_sections(_SAMPLE)
    cred = next(s for s in sections if s["key"] == "credibility")
    assert 'class="cred-chip cred-ok"' in cred["html"]
    assert 'class="cred-chip cred-claim"' in cred["html"]
    assert 'class="cred-chip cred-verify"' in cred["html"]
    assert 'class="cred-chip cred-rebut"' in cred["html"]
    # raw bracket labels should be gone after chip substitution
    assert "[共识/可信]" not in cred["html"]


def test_non_credibility_sections_have_no_chips():
    sections = build_insight_sections(_SAMPLE)
    claims = next(s for s in sections if s["key"] == "claims")
    assert "cred-chip" not in claims["html"]


def test_markdown_without_headers_becomes_single_block():
    sections = build_insight_sections("这是一段没有任何标题的洞察内容。")
    assert len(sections) == 1
    assert sections[0]["key"] == "other"
    assert sections[0]["html"]


def test_empty_markdown_returns_empty_list():
    assert build_insight_sections("") == []
    assert build_insight_sections(None) == []


def test_prefilled_post_url_never_auto_analyzes_or_repeats_paid_work():
    template = POST_TEMPLATE.read_text(encoding="utf-8")
    startup = template[template.index("// 带 ?view=<id>"):]

    assert "analyze();" not in startup
    assert "点击“分析”后才会开始抓取并调用 AI" in template
    assert "可能产生 TikHub 与模型费用" in template
    assert "未找到已保存的帖子洞察结果" in startup
