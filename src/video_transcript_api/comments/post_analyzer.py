"""LLM analyzer for X / Twitter post insights.

Unlike the video/note comment analyzer, this one analyzes the author's post
content (a single tweet or a self-thread) together with high-signal replies, and
explicitly produces a credibility judgement -- the user's core need is telling
whether a post and its top replies are trustworthy and worth their time. It also
works when there are no replies (the post content alone is worth analyzing).
"""

from .selector import CommentItem, format_comments_for_llm

POST_INSIGHT_SYSTEM_PROMPT = """你是专业的社交帖子审核分析助手。
你的任务是分析一条社交平台帖子（X / 小红书 / 微信公众号 等）的作者正文与高赞评论/回复，
提炼对读者有价值的精华，并显式做可信度判断。

要求：
- 自适应判断帖子类型（观点 / 经验 / 资讯 / 种草 / 营销），不要套模板。
- 可信度判断要克制、有依据：区分"可核实的事实陈述"与"个人观点 / 单方面断言"。
- 如果评论区/回复区对正文有补充、佐证或反驳，要明确指出。
- 若帖子没有可用评论（如公众号留言不可获取），就只基于正文分析，并说明这一点。
- 信息不足以判断时要直说，禁止臆测或强行拔高。
- 输出中文 Markdown。

固定输出结构：
## 正文核心主张
## 可信度与存疑点
（逐条用标签标注：[共识/可信]、[单方面断言]、[需外部核实]、[回复区有反驳]）
## 评论区：共识 vs 争议
## 代表性高赞回复
## 对你的可行动启发
"""


class PostInsightAnalyzer:
    """Generate structured, credibility-aware insight for an X post.

    Shares ``analyze`` signature with CommentInsightAnalyzer so it can be passed
    wherever an analyzer is expected, but tolerates an empty ``comments`` list.
    """

    def __init__(self, llm_client, model: str, reasoning_effort: str | None = None):
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
        user_prompt = self._build_user_prompt(title, author, summary_text, comments)
        response = self.llm_client.call(
            model=self.model,
            system_prompt=POST_INSIGHT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            reasoning_effort=self.reasoning_effort,
            task_type="post_insight",
        )
        return response.text.strip() if response.text else None

    def _build_user_prompt(
        self,
        title: str,
        author: str,
        summary_text: str | None,
        comments: list[CommentItem],
    ) -> str:
        thread_block = (summary_text or "").strip() or "（正文为空）"
        if comments:
            comment_block = format_comments_for_llm(
                comments, max_items=80, max_text_length=200
            )
        else:
            comment_block = "（无可用回复，请仅基于正文分析。）"

        return f"""帖子标题：{title}
作者：@{author or "Unknown"}

作者正文（thread）：
{thread_block}

高赞回复样本：
{comment_block}

请基于以上内容生成帖子洞察。"""
