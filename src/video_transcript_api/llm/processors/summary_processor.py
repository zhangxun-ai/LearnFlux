"""内容总结处理器"""

from typing import Dict, Optional

from ...utils.logging import setup_logger
from ..core.config import LLMConfig
from ..core.llm_client import LLMClient
from ..prompts import (
    SUMMARY_SYSTEM_PROMPT_DEEP_LEARNING_ARTICLE,
    SUMMARY_SYSTEM_PROMPT_SINGLE_SPEAKER,
    SUMMARY_SYSTEM_PROMPT_MULTI_SPEAKER,
    build_summary_user_prompt,
)

logger = setup_logger(__name__)

_MIN_USEFUL_SUMMARY_CHARS = 50


class SummaryProcessor:
    """内容总结处理器

    职责：
    - 生成视频内容的文本总结
    - 根据说话人数量选择合适的 System Prompt
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
        summary_profile: Optional[str] = None,
    ) -> Optional[str]:
        """生成文本总结

        Args:
            text: 待总结的文本（通常是校对后的文本）
            title: 视频标题
            author: 作者/频道
            description: 视频描述
            speaker_count: 说话人数量（0 或 1 表示单说话人，>= 2 表示多说话人）
            transcription_data: 原始转录数据（可选，用于辅助分析）
            selected_models: 选定的模型配置（可选，来自风险检测）
            summary_profile: 总结输出契约（可选）

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

        system_prompt = self._select_system_prompt(speaker_count, summary_profile)
        user_prompt = build_summary_user_prompt(
            transcript=text,
            video_title=title,
            author=author,
            description=description,
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

    def _select_system_prompt(
        self,
        speaker_count: int,
        summary_profile: Optional[str] = None,
    ) -> str:
        """根据说话人数量选择 System Prompt

        Args:
            speaker_count: 说话人数量
            summary_profile: 总结输出契约（可选）

        Returns:
            System Prompt 字符串
        """
        if summary_profile in {"deep_learning", "deep_learning_article"}:
            logger.debug("Using deep-learning summary prompt")
            return SUMMARY_SYSTEM_PROMPT_DEEP_LEARNING_ARTICLE
        if speaker_count >= 2:
            # 多说话人：强调对话动态、观点碰撞
            logger.debug("Using multi-speaker summary prompt")
            return SUMMARY_SYSTEM_PROMPT_MULTI_SPEAKER
        else:
            # 单说话人：强调论点提取、逻辑结构
            logger.debug("Using single-speaker summary prompt")
            return SUMMARY_SYSTEM_PROMPT_SINGLE_SPEAKER
