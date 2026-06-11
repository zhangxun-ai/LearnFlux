"""Select and format hot comments for LLM analysis."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommentItem:
    """Normalized comment data used by comment insight processing."""

    text: str
    like_count: int = 0
    reply_count: int = 0
    user_nickname: str = ""
    comment_id: str = ""
    platform_rank: int = 0


_LOW_INFORMATION_TEXTS = {
    "哈哈",
    "哈哈哈",
    "哈哈哈哈",
    "牛",
    "牛逼",
    "支持",
    "赞",
    "来了",
    "第一",
}


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _is_low_information(text: str) -> bool:
    compact = _normalize_text(text).replace(" ", "")
    if len(compact) < 6:
        return True
    if compact in _LOW_INFORMATION_TEXTS:
        return True
    if all(ch in "哈啊哦嗯😂🤣👍👏❤♥️！!?.。~～" for ch in compact):
        return True
    return False


def select_high_value_comments(
    comments: list[CommentItem],
    max_items: int = 50,
) -> list[CommentItem]:
    """Filter a hot-comment window while preserving platform hot order.

    Platforms already provide the first ranking signal. This function only
    removes obvious low-signal and duplicated comments, then caps the size for
    LLM cost control.
    """
    selected: list[CommentItem] = []
    seen_texts: set[str] = set()

    for item in sorted(comments, key=lambda c: c.platform_rank):
        text = _normalize_text(item.text)
        if not text or _is_low_information(text):
            continue

        dedupe_key = text.casefold()
        if dedupe_key in seen_texts:
            continue

        seen_texts.add(dedupe_key)
        selected.append(
            CommentItem(
                text=text,
                like_count=max(item.like_count, 0),
                reply_count=max(item.reply_count, 0),
                user_nickname=item.user_nickname,
                comment_id=item.comment_id,
                platform_rank=item.platform_rank,
            )
        )

        if len(selected) >= max_items:
            break

    return selected


def _truncate_text(text: str, max_length: int) -> str:
    text = _normalize_text(text)
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."


def format_comments_for_llm(
    comments: list[CommentItem],
    max_items: int = 50,
    max_text_length: int = 200,
) -> str:
    """Convert selected comments into compact text for LLM prompts."""
    lines = []
    for index, item in enumerate(comments[:max_items], start=1):
        author = item.user_nickname or "anonymous"
        text = _truncate_text(item.text, max_text_length)
        lines.append(
            f"{index}. @{author} | 点赞 {item.like_count} | 回复 {item.reply_count} | {text}"
        )
    return "\n".join(lines)
