"""LLM analyzer for hot comment insights."""

from .selector import CommentItem, format_comments_for_llm


COMMENT_INSIGHT_SYSTEM_PROMPT = """你是专业的评论洞察分析助手。

你的任务是分析视频/笔记下方的一组高赞评论，提炼评论区真正有价值的信息。

要求：
- 不要预设评论价值类型，要根据视频内容和评论本身自适应判断。
- 如果是种草内容，重点识别购买意向、使用场景、顾虑和被打动的点。
- 如果是工具/产品内容，重点识别使用反馈、痛点、门槛、替代方案和需求。
- 如果是观点内容，重点识别共识、反对意见、争议点和补充信息。
- 如果评论缺少足够信息，要明确说明，不要强行拔高。
- 输出中文 Markdown。

固定输出结构：
## 评论区核心共识
## 高频关注点
## 代表性高赞评论
## 评论价值判断
## 可行动启发
"""


class CommentInsightAnalyzer:
    """Generate adaptive insights from selected hot comments."""

    def __init__(
        self,
        llm_client,
        model: str,
        reasoning_effort: str | None = None,
    ):
        self.llm_client = llm_client
        self.model = model
        self.reasoning_effort = reasoning_effort

    def analyze(
        self,
        title: str,
        author: str,
        summary_text: str | None,
        comments: list[CommentItem],
    ) -> str | None:
        if not comments:
            return None

        user_prompt = self._build_user_prompt(title, author, summary_text, comments)
        response = self.llm_client.call(
            model=self.model,
            system_prompt=COMMENT_INSIGHT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            reasoning_effort=self.reasoning_effort,
            task_type="comment_insight",
        )
        return response.text.strip() if response.text else None

    def _build_user_prompt(
        self,
        title: str,
        author: str,
        summary_text: str | None,
        comments: list[CommentItem],
    ) -> str:
        comment_text = format_comments_for_llm(comments, max_items=80, max_text_length=200)
        summary_block = summary_text or "未生成内容总结，请仅根据标题和评论判断。"

        return f"""视频标题：{title}
作者：{author or "Unknown"}

内容总结：
{summary_block}

高赞评论样本：
{comment_text}

请基于这些高赞评论生成评论洞察。"""
