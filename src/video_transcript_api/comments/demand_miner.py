"""Extract demand signals from selected social comments."""

from __future__ import annotations

from typing import Any

from .selector import CommentItem

CATEGORY_ORDER = (
    "pain_points",
    "questions",
    "objections",
    "purchase_intent",
    "tutorial_requests",
    "tool_requests",
)

_CATEGORY_TITLES = {
    "pain_points": "痛点/阻碍",
    "questions": "问题/疑问",
    "objections": "反对/质疑",
    "purchase_intent": "购买/付费意向",
    "tutorial_requests": "教程/模板需求",
    "tool_requests": "工具/自动化需求",
}

_LOW_INFORMATION_TEXTS = {
    "哈哈",
    "哈哈哈",
    "哈哈哈哈",
    "牛",
    "支持",
    "赞",
    "第一",
}

_PATTERNS = {
    "pain_points": (
        "太贵",
        "贵",
        "麻烦",
        "难",
        "不会",
        "卡",
        "失败",
        "没用",
        "不好用",
        "不行",
        "踩坑",
        "焦虑",
        "痛点",
        "问题",
        "浪费",
    ),
    "questions": (
        "怎么",
        "如何",
        "为什么",
        "哪里",
        "在哪",
        "多少",
        "有没有",
        "能不能",
        "可以",
        "?",
        "？",
    ),
    "objections": (
        "不认同",
        "反对",
        "但是",
        "可是",
        "不一定",
        "忽略",
        "问题是",
        "营销",
        "广告",
        "割韭菜",
        "夸大",
    ),
    "purchase_intent": (
        "怎么买",
        "哪里买",
        "在哪买",
        "链接",
        "多少钱",
        "价格",
        "购买",
        "下单",
        "付费",
        "有课",
        "求推荐",
    ),
    "tutorial_requests": (
        "教程",
        "步骤",
        "清单",
        "模板",
        "案例",
        "讲讲",
        "展开",
        "详细",
        "怎么做",
        "如何做",
        "复制",
    ),
    "tool_requests": (
        "工具",
        "软件",
        "插件",
        "脚本",
        "自动化",
        "api",
        "平台",
        "系统",
    ),
}


def mine_comment_demands(
    comments: list[CommentItem],
    *,
    max_items_per_category: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Extract high-signal demand categories from comments.

    The miner is intentionally deterministic: it surfaces evidence comments for
    the LLM and UI, but does not invent a summary itself.
    """
    result = {key: [] for key in CATEGORY_ORDER}
    seen_by_category = {key: set() for key in CATEGORY_ORDER}

    for comment in sorted(comments, key=lambda c: (-c.like_count, c.platform_rank)):
        text = _normalize_text(comment.text)
        if _is_low_information(text):
            continue

        matched = _matched_categories(text)
        for category in matched:
            if len(result[category]) >= max_items_per_category:
                continue
            dedupe_key = text.casefold()
            if dedupe_key in seen_by_category[category]:
                continue
            seen_by_category[category].add(dedupe_key)
            result[category].append(_comment_to_dict(comment, text))

    return result


def format_demand_signals_for_llm(signals: dict[str, list[dict[str, Any]]]) -> str:
    """Render demand signals as compact prompt context."""
    if not any(signals.get(category) for category in CATEGORY_ORDER):
        return "## 评论需求矿场\n暂无明显需求信号。"

    blocks = ["## 评论需求矿场"]
    for category in CATEGORY_ORDER:
        items = signals.get(category) or []
        if not items:
            continue
        blocks.append(f"### {_CATEGORY_TITLES[category]}")
        for item in items:
            author = item.get("user_nickname") or "anonymous"
            blocks.append(
                f"- @{author} | 点赞 {item.get('like_count', 0)} | {item.get('text', '')}"
            )
    return "\n".join(blocks)


def _matched_categories(text: str) -> list[str]:
    lowered = text.casefold()
    return [
        category
        for category in CATEGORY_ORDER
        if any(pattern in lowered for pattern in _PATTERNS[category])
    ]


def _comment_to_dict(comment: CommentItem, text: str) -> dict[str, Any]:
    return {
        "text": text,
        "like_count": max(comment.like_count, 0),
        "reply_count": max(comment.reply_count, 0),
        "user_nickname": comment.user_nickname,
        "comment_id": comment.comment_id,
        "platform_rank": comment.platform_rank,
    }


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _is_low_information(text: str) -> bool:
    compact = _normalize_text(text).replace(" ", "")
    if not compact:
        return True
    if compact in _LOW_INFORMATION_TEXTS:
        return True
    if len(compact) <= 2:
        return True
    if all(ch in "哈啊哦嗯😂🤣👍👏❤♥️！!?.。~～" for ch in compact):
        return True
    return False
