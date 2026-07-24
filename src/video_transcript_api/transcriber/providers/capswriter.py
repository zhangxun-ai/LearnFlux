"""CapsWriter ordinary transcription provider."""

import json
import time
from pathlib import Path
from typing import Any, Callable

from ...utils.logging import setup_logger
from ..capswriter_client import CapsWriterClient, Config as ClientConfig
from ..contracts import TranscriptionContext, TranscriptionResult

logger = setup_logger("transcriber")


class CapsWriterProvider:
    """Transcribe media through the existing CapsWriter WebSocket client."""

    name = "capswriter"

    def __init__(
        self,
        config: dict[str, Any],
        output_dir: str,
        progress_callback: Callable[..., Any] | None = None,
    ):
        self.config = config
        self.output_dir = str(output_dir)
        self.progress_callback = progress_callback
        self.max_retries = config.get("capswriter", {}).get("max_retries", 3)
        self.retry_delay = config.get("capswriter", {}).get("retry_delay", 5)
        self.capswriter_client = self._build_client()

    def _build_client(self) -> CapsWriterClient:
        """Build the existing client with the current configuration semantics."""
        try:
            server_url = self.config.get("capswriter", {}).get(
                "server_url", "ws://localhost:6006"
            )
            if server_url.startswith("ws://"):
                server_url = server_url[5:]

            if ":" in server_url:
                server_addr, server_port_value = server_url.split(":")
                server_port = int(server_port_value)
            else:
                server_addr = server_url
                server_port = 6006

            ClientConfig.server_addr = server_addr
            ClientConfig.server_port = server_port
            ClientConfig.generate_txt = True
            ClientConfig.generate_merge_txt = False
            ClientConfig.generate_srt = False
            ClientConfig.generate_lrc = False
            ClientConfig.generate_json = False

            client = CapsWriterClient(
                server_addr=server_addr,
                server_port=server_port,
                output_dir=self.output_dir,
                max_retries=self.max_retries,
                retry_delay=self.retry_delay,
                progress_callback=self.progress_callback,
            )
            logger.info(
                f"已配置CapsWriter客户端，服务器: {server_addr}:{server_port}"
            )
            return client
        except Exception as exc:
            logger.exception(f"设置CapsWriter客户端配置失败: {str(exc)}")
            raise

    def transcribe(
        self,
        audio_path: str,
        output_base: str,
        *,
        context: TranscriptionContext | None = None,
    ) -> TranscriptionResult:
        """Transcribe one media file and parse the generated artifacts."""
        del context
        del output_base
        logger.info(f"调用CapsWriter客户端转录文件: {audio_path}")
        started_at = time.time()
        success, generated_files = self.capswriter_client.transcribe_file(audio_path)

        if not success or not generated_files:
            error_message = f"转录文件失败: {audio_path}"
            logger.error(error_message)
            raise RuntimeError(error_message)

        logger.info(f"转录完成，生成文件: {[str(path) for path in generated_files]}")
        transcript = ""
        txt_path = None
        funasr_json_data = None

        for file_path in generated_files:
            file_path_str = str(file_path)
            if file_path_str.endswith(".txt") and not file_path_str.endswith(
                ".merge.txt"
            ):
                txt_path = file_path_str
                try:
                    with open(file_path_str, "r", encoding="utf-8") as file:
                        transcript = file.read().strip()
                    logger.info("已从文本文件提取转录文本")
                except Exception as exc:
                    logger.warning(f"读取转录文本失败: {str(exc)}")
            elif file_path_str.endswith("_funasr.json"):
                try:
                    with open(file_path_str, "r", encoding="utf-8") as file:
                        funasr_json_data = json.load(file)
                    logger.info(f"已读取 FunASR 兼容格式 JSON: {file_path_str}")
                except Exception as exc:
                    logger.warning(f"读取 FunASR JSON 失败: {str(exc)}")

        if not txt_path:
            error_message = f"未找到文本文件: {audio_path}"
            logger.error(error_message)
            raise RuntimeError(error_message)

        return TranscriptionResult(
            transcript=transcript,
            txt_path=txt_path,
            funasr_json_data=funasr_json_data,
            generated_files=tuple(Path(path) for path in generated_files),
            provider=self.name,
            elapsed_seconds=time.time() - started_at,
        )
