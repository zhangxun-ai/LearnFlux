"""Generate a new Xiaohongshu draft from a saved flywheel teardown."""
from __future__ import annotations

from .models import MediaType


class DraftGenerator:
    """Turn teardown findings into a new non-plagiarizing Xiaohongshu post."""

    def __init__(self, llm_client, model: str, reasoning_effort: str | None = None):
        self.llm_client = llm_client
        self.model = model
        self.reasoning_effort = reasoning_effort

    def generate(
        self,
        *,
        title: str,
        author: str,
        media_type: MediaType,
        stats: dict,
        source_text: str,
        analysis_result: dict,
    ) -> dict:
        system_prompt = _system_prompt()
        user_prompt = _user_prompt(
            title=title,
            author=author,
            media_type=media_type,
            stats=stats,
            source_text=source_text,
            analysis_result=analysis_result,
        )
        response = self.llm_client.call(
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            reasoning_effort=self.reasoning_effort,
            task_type="flywheel_xhs_draft",
        )
        markdown = (response.text or "").strip()
        if not markdown:
            raise ValueError("LLM 返回空草稿")
        return {
            "markdown": markdown,
            "in_chars": len(system_prompt) + len(user_prompt),
            "out_chars": len(markdown),
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }


def _system_prompt() -> str:
    return """你是顶级小红书爆款文案创作者。
你的任务：基于一条已拆解的对标内容，重新生成一篇新的小红书帖子。

硬性规则：
1. 不要抄袭原文，不要复写原文句子，不要沿用原作者个人经历。
2. 新帖必须围绕原始对标内容的同一核心议题、同一核心人物或同一核心事件展开。
3. 不要把拆解结果里的模板示例、下一条选题建议或类比案例替换成正文主题。
4. 可以复用选题结构、开头机制、信息组织方式、转折节奏和互动设计。
5. 新帖必须像真实小红书笔记，不要写成分析报告、课程大纲或广告文案。
6. 输出只使用 Markdown，严格包含以下二级标题：
## 标题候选
## 封面钩子
## 正文
## 互动引导
## 话题标签
## 创作说明
"""


def _user_prompt(
    *,
    title: str,
    author: str,
    media_type: MediaType,
    stats: dict,
    source_text: str,
    analysis_result: dict,
) -> str:
    kind = "视频" if media_type is MediaType.VIDEO else "图文"
    stat_line = (
        f"点赞 {stats.get('like_count', 0)} · "
        f"收藏 {stats.get('collect_count', 0)} · "
        f"评论 {stats.get('comment_count', 0)}"
    )
    sections = analysis_result.get("sections") or []
    section_text = "\n".join(
        f"- {item.get('title', '')}: {item.get('body', '')}" for item in sections
    )
    one_thing = analysis_result.get("one_thing") or ""
    source = (source_text or "").strip()
    if len(source) > 5000:
        source = source[:5000] + "\n（原文过长，已截断）"

    return f"""对标内容信息：
标题：{title}
作者：{author or "unknown"}
类型：小红书{kind}
互动数据：{stat_line}

拆解结果：
{section_text or "（无结构化拆解）"}

可复用动作：
{one_thing or "（无）"}

原文/转写摘录：
{source or "（无）"}

核心议题锁定：
- 新帖必须围绕原始对标内容的同一核心议题：{title}
- 涉及的人物、事件、行业判断必须来自原始对标内容或原文摘录。
- 不得把拆解里的模板示例、下一条选题建议、类比案例当成新帖主题。
- 如果拆解中出现“例：”“方向一/二/三”“下一条”等内容，只能学习结构，不能替换原始话题。

请生成一篇新的小红书帖子：
- 标题候选给 3 个，每个标题要能单独使用。
- 封面钩子给 1-2 句，适合放在封面或首屏。
- 正文要完整，可直接发布，语气自然，信息密度高。
- 互动引导要能引发评论。
- 话题标签给 8-12 个。
- 创作说明只说明你复用了哪些结构，以及如何避免抄袭。"""
