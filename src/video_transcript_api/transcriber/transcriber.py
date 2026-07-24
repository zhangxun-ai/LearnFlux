"""Backward-compatible facade for ordinary speech transcription."""

import os
from typing import Any

from ..utils.logging import ensure_dir, load_config, setup_logger
from .contracts import TranscriptionContext, TranscriptionProvider
from .providers import CapsWriterProvider, LocalWhisperProvider

logger = setup_logger("transcriber")

_workspace_dir_cache = None


def get_workspace_dir():
    """Return the configured transcription workspace directory."""
    global _workspace_dir_cache
    if _workspace_dir_cache is None:
        from ..api.context import get_workspace_dir as _get_workspace_dir_impl

        _workspace_dir_cache = _get_workspace_dir_impl()
    return _workspace_dir_cache


class Transcriber:
    """Select an ordinary transcription provider and preserve the legacy result."""

    def __init__(
        self,
        config=None,
        progress_callback=None,
        strategy: str | None = None,
        cloud_provider_factory=None,
    ):
        """Initialize the facade without starting a provider."""
        if strategy not in (None, "local", "cloud"):
            raise ValueError("strategy must be one of: None, local, cloud")

        if config is None:
            config = load_config()

        self.config = config
        self.progress_callback = progress_callback
        self.strategy = strategy
        self.cloud_provider_factory = cloud_provider_factory
        self.last_result = None
        self.output_dir = get_workspace_dir()
        ensure_dir(self.output_dir)

    def transcribe(
        self,
        audio_path,
        output_base=None,
        *,
        context: TranscriptionContext | None = None,
    ):
        """Transcribe media and return the dictionary expected by existing callers."""
        try:
            logger.info(
                f"开始转录音频文件: {os.path.basename(str(audio_path))}"
            )
            if output_base is None:
                output_base = os.path.splitext(os.path.basename(audio_path))[0]

            if self.strategy == "cloud" and context is None:
                raise RuntimeError("cloud transcription requires context")

            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"音频文件不存在: {audio_path}")

            provider = self._create_provider(context=context)
            if self.strategy == "cloud":
                result = provider.transcribe(
                    audio_path, output_base, context=context
                )
            else:
                result = provider.transcribe(audio_path, output_base)
            self.last_result = result
            return result.to_legacy_dict()
        except Exception as exc:
            if self.strategy == "cloud":
                logger.error("Cloud transcription failed")
            else:
                logger.exception(f"转录音频文件失败: {str(exc)}")
            raise

    def _create_provider(
        self, *, context: TranscriptionContext | None = None
    ) -> TranscriptionProvider:
        """Create only the provider selected by the existing config flag."""
        if self.strategy == "cloud" and self.cloud_provider_factory is None:
            raise RuntimeError("cloud transcription requires cloud_provider_factory")

        if self.strategy == "cloud":
            return self.cloud_provider_factory(
                config=self.config,
                output_dir=self.output_dir,
                progress_callback=self.progress_callback,
                context=context,
            )

        if self.strategy == "local" or self.config.get(
            "local_whisper", {}
        ).get("enabled", False):
            return LocalWhisperProvider(
                config=self.config,
                output_dir=self.output_dir,
            )
        return CapsWriterProvider(
            config=self.config,
            output_dir=self.output_dir,
            progress_callback=self.progress_callback,
        )

    @staticmethod
    def _whisper_json_to_funasr(payload: dict[str, Any], audio_path: str):
        """Compatibility delegate for the former private conversion helper."""
        return LocalWhisperProvider.whisper_json_to_funasr(payload, audio_path)

    @staticmethod
    def _as_seconds(value: Any):
        """Compatibility delegate for the former private timestamp helper."""
        return LocalWhisperProvider.as_seconds(value)
