"""内容总结处理器"""

from typing import Dict, Optional

from ...utils.logging import setup_logger
from ..core.config import LLMConfig
from ..core.llm_client import LLMClient
from ..prompts import SUMMARY_SYSTEM_PROMPT, build_summary_user_prompt
from ..summary_quality import summary_incompleteness_reason, summary_source_issues

logger = setup_logger(__name__)

_MIN_USEFUL_SUMMARY_CHARS = 50


class SummaryProcessor:
    """内容总结处理器

    职责：
    - 生成视频内容的文本总结
    - 根据实际内容自动适配解析结构，检查明显残缺结果
    - fallback 由共享 LLM 客户端统一调度，避免重复执行模型链
    """

    def __init__(
        self,
        llm_client: LLMClient,
        config: LLMConfig,
    ):
        """初始化总结处理器

        Args:
            llm_client: LLM 客户端（含智能重试）
            config: LLM 配置对象
        """
        self.llm_client = llm_client
        self.config = config

        logger.info("SummaryProcessor initialized")

    def process(
        self,
        text: str,
        title: str,
        author: str = "",
        description: str = "",
        speaker_count: int = 0,
        transcription_data: Optional[Dict] = None,
        selected_models: Optional[Dict] = None,
    ) -> Optional[str]:
        """生成文本总结

        Args:
            text: 待总结的文本（通常是校对后的文本）
            title: 视频标题
            author: 作者/频道
            description: 视频描述
            speaker_count: 检测到的说话人数量（0 表示未知）
            transcription_data: 原始转录数据（可选，用于辅助分析）
            selected_models: 选定的模型配置（可选，来自风险检测）

        Returns:
            总结文本，如果文本过短则返回 None

        Raises:
            不抛出异常，出错时返回 None
        """
        # 步骤 1: 长度检查
        if len(text) < self.config.min_summary_threshold:
            logger.info(
                f"Text too short for summary: {len(text)} < {self.config.min_summary_threshold}"
            )
            return None

        logger.info(
            f"Generating summary for text (length: {len(text)}, speaker_count: {speaker_count})"
        )

        if selected_models:
            primary_model = selected_models.get(
                "summary_model", self.config.summary_model
            )
            reasoning_effort = selected_models.get(
                "summary_reasoning_effort",
                self.config.summary_reasoning_effort,
            )
        else:
            primary_model = self.config.summary_model
            reasoning_effort = self.config.summary_reasoning_effort

        system_prompt = SUMMARY_SYSTEM_PROMPT
        user_prompt = build_summary_user_prompt(
            transcript=text,
            video_title=title,
            author=author,
            description=description,
            speaker_count=speaker_count,
            duration_seconds=(transcription_data or {}).get("duration"),
        )

        try:
            response = self.llm_client.call(
                model=primary_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                reasoning_effort=reasoning_effort,
                task_type="summary",
            )
            summary_text = (response.text or "").strip()
            if len(summary_text) < _MIN_USEFUL_SUMMARY_CHARS:
                logger.warning(
                    f"Summary too short or empty: {len(summary_text)} chars"
                )
                return None

            defect = summary_incompleteness_reason(text, summary_text)
            if defect:
                logger.warning(f"Incomplete summary rejected: {defect}")
                return None

            source_issues = summary_source_issues(text, summary_text)
            if source_issues:
                logger.warning(f"Correcting summary source defects: {len(source_issues)}")
                correction_prompt = (
                    "【上一稿的来源核对问题】\n"
                    + "\n".join(f"- {issue}" for issue in source_issues)
                    + "\n请逐项对照转录正文，修订整篇解析。核对所有日期、数字、专名、"
                    "案例和引语；删除没有正文依据的补充，不用外部知识填补。"
                    "无法逐字匹配的引语应忠实转述，不使用引号。"
                    "相对时间以正文上下文为准，不自行替换年份。"
                    "只返回修订后的完整正文。\n\n【待修订草稿】\n"
                    + summary_text
                    + "\n\n"
                    + user_prompt
                )
                repaired = self.llm_client.call(
                    model=getattr(response, "model", "") or primary_model,
                    system_prompt=system_prompt,
                    user_prompt=correction_prompt,
                    reasoning_effort=reasoning_effort,
                    task_type="summary",
                )
                summary_text = (repaired.text or "").strip()
                if (
                    len(summary_text) < _MIN_USEFUL_SUMMARY_CHARS
                    or summary_incompleteness_reason(text, summary_text)
                    or summary_source_issues(text, summary_text)
                ):
                    logger.warning("Corrected summary still has source or completion defects")
                    return None

            logger.info(
                f"Summary generated successfully (length: {len(summary_text)})"
            )
            return summary_text
        except Exception as exc:
            logger.error(
                f"Summary generation failed after client fallback chain: {exc}",
                exc_info=True,
            )
            return None

    def _select_system_prompt(self, speaker_count: int) -> str:
        """Compatibility helper: unknown speaker count does not imply monologue."""
        return SUMMARY_SYSTEM_PROMPT
