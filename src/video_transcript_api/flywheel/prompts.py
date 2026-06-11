"""Default analysis prompts (video / article) + a section parser.

Prompts are plain-language on purpose (the user is a beginner creator). They are
seeded into ``prompt_template`` and are user-editable; these constants are the
fallback defaults. Video and article prompts are separate and never mixed.
"""
from __future__ import annotations

import re

from .models import MediaType

VIDEO_SYSTEM_PROMPT = """你是爆款短视频拆解教练，说人话、不用术语。
给你一条小红书视频的标题、转写文字和互动数据，请拆出"它为什么火"，让一个新手也能照着做。
严格用下面四个小标题输出中文 Markdown，每段 1-3 句话，具体、能照做：

## 开头怎么抓人
## 中间怎么留住人
## 结尾怎么促互动
## 你可以马上试的一件事
"""

ARTICLE_SYSTEM_PROMPT = """你是爆款图文笔记拆解教练，说人话、不用术语。
给你一条小红书图文笔记的标题、正文和互动数据，请拆出"它为什么火"，让一个新手也能照着做。
严格用下面四个小标题输出中文 Markdown，每段 1-3 句话，具体、能照做：

## 标题怎么写
## 封面/首图怎么做
## 正文怎么组织
## 你可以马上试的一件事
"""

DEFAULT_PROMPTS: dict[MediaType, str] = {
    MediaType.VIDEO: VIDEO_SYSTEM_PROMPT,
    MediaType.ARTICLE: ARTICLE_SYSTEM_PROMPT,
}


def default_prompt(media_type: MediaType) -> str:
    return DEFAULT_PROMPTS[media_type]


def parse_sections(markdown: str) -> dict:
    """Split ``## heading`` markdown into structured sections + the 'one thing'.

    Returns ``{"markdown", "sections": [{"title", "body"}], "one_thing"}``. The
    last section is treated as the actionable takeaway when its title hints at it.
    """
    text = (markdown or "").strip()
    parts = re.split(r"(?m)^\s*##\s+(.+?)\s*$", text)
    sections: list[dict] = []
    i = 1
    while i < len(parts):
        title = parts[i].strip()
        body = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        sections.append({"title": title, "body": body})
        i += 2

    one_thing = ""
    for sec in sections:
        if any(k in sec["title"] for k in ("一件事", "马上试", "下一条", "下一篇")):
            one_thing = sec["body"]
    return {"markdown": text, "sections": sections, "one_thing": one_thing}
