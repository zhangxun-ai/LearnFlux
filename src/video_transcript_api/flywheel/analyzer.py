"""Single-content analyzer: build a prompt, call the LLM, return markdown.

Mirrors ``comments.post_analyzer.PostInsightAnalyzer``: the ``llm_client`` is
injected, so unit tests pass a fake and production passes the real coordinator
client. The LLM contract is plain markdown with fixed ``##`` sections (proven to
work with this project's llm-compat setup) — parsing happens in ``prompts``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..utils.logging import setup_logger
from .models import MediaType

logger = setup_logger("flywheel_analyzer")


@dataclass(frozen=True)
class AnalyzeOutput:
    markdown: str
    in_chars: int
    out_chars: int


# very rough CNY estimate; chars->tokens ~ /1.7 for mixed zh/en, per-1k-token rate.
_CHARS_PER_TOKEN = 1.7
_RATE_PER_1K_IN = 0.004
_RATE_PER_1K_OUT = 0.012


def estimate_cost(in_chars: int, out_chars: int) -> tuple[int, int, float]:
    """Estimate (in_tokens, out_tokens, total_cost_cny). Estimated, not billed."""
    in_tok = int(in_chars / _CHARS_PER_TOKEN)
    out_tok = int(out_chars / _CHARS_PER_TOKEN)
    cost = in_tok / 1000 * _RATE_PER_1K_IN + out_tok / 1000 * _RATE_PER_1K_OUT
    return in_tok, out_tok, round(cost, 4)


class ContentAnalyzer:
    """Run the right prompt for a piece of content and return markdown."""

    def __init__(self, llm_client, model: str, reasoning_effort: str | None = None):
        self.llm_client = llm_client
        self.model = model
        self.reasoning_effort = reasoning_effort

    def analyze(self, media_type: MediaType, title: str, text: str,
                stats: dict, system_prompt: str) -> AnalyzeOutput:
        user_prompt = self._build_user_prompt(media_type, title, text, stats)
        response = self.llm_client.call(
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            reasoning_effort=self.reasoning_effort,
            task_type="flywheel_analysis",
        )
        markdown = (response.text or "").strip()
        if not markdown:
            raise ValueError("LLM 返回空结果")
        return AnalyzeOutput(
            markdown=markdown,
            in_chars=len(system_prompt) + len(user_prompt),
            out_chars=len(markdown),
        )

    @staticmethod
    def _build_user_prompt(media_type: MediaType, title: str, text: str, stats: dict) -> str:
        kind = "视频" if media_type is MediaType.VIDEO else "图文笔记"
        body_label = "视频转写文字" if media_type is MediaType.VIDEO else "笔记正文"
        s = stats or {}
        stat_line = (f"点赞 {s.get('like_count', 0)} · 收藏 {s.get('collect_count', 0)} · "
                     f"评论 {s.get('comment_count', 0)}")
        body = (text or "").strip() or "（正文为空）"
        return f"""这是一条小红书{kind}。
标题：{title}
互动数据：{stat_line}

{body_label}：
{body}

请按系统提示的四个小标题，拆出它为什么火。"""
