import os
import sys
import json
import shutil
import time
from pathlib import Path
from ..utils.logging import setup_logger, load_config, ensure_dir
from .capswriter_client import CapsWriterClient, Config as ClientConfig

logger = setup_logger("transcriber")

_workspace_dir_cache = None


def get_workspace_dir():
    global _workspace_dir_cache
    if _workspace_dir_cache is None:
        from ..api.context import get_workspace_dir as _get_workspace_dir_impl

        _workspace_dir_cache = _get_workspace_dir_impl()
    return _workspace_dir_cache


class Transcriber:
    """
    音视频转录器，基于CapsWriter-Offline客户端
    """

    def __init__(self, config=None, progress_callback=None):
        """Initialize transcriber with workspace directory."""
        if config is None:
            config = load_config()

        self.config = config
        self.progress_callback = progress_callback
        self.output_dir = get_workspace_dir()
        self.max_retries = config.get("capswriter", {}).get("max_retries", 3)
        self.retry_delay = config.get("capswriter", {}).get("retry_delay", 5)

        ensure_dir(self.output_dir)

        # 设置Client_Only配置
        self._setup_client_config()

    def _setup_client_config(self):
        """
        设置CapsWriter客户端的配置
        """
        try:
            # 从项目配置中获取CapsWriter服务器信息
            server_url = self.config.get("capswriter", {}).get(
                "server_url", "ws://localhost:6006"
            )

            # 解析服务器地址和端口
            if server_url.startswith("ws://"):
                server_url = server_url[5:]

            if ":" in server_url:
                server_addr, server_port = server_url.split(":")
                server_port = int(server_port)
            else:
                server_addr = server_url
                server_port = 6006

            # 更新客户端配置
            ClientConfig.server_addr = server_addr
            ClientConfig.server_port = server_port

            # 设置输出格式 - 只生成txt文件
            ClientConfig.generate_txt = True  # 生成标准文本
            ClientConfig.generate_merge_txt = False
            ClientConfig.generate_srt = False
            ClientConfig.generate_lrc = False
            ClientConfig.generate_json = False

            # 创建CapsWriter客户端实例
            self.capswriter_client = CapsWriterClient(
                server_addr=server_addr,
                server_port=server_port,
                output_dir=self.output_dir,
                max_retries=self.max_retries,
                retry_delay=self.retry_delay,
                progress_callback=self.progress_callback,
            )

            logger.info(f"已配置CapsWriter客户端，服务器: {server_addr}:{server_port}")
        except Exception as e:
            logger.exception(f"设置CapsWriter客户端配置失败: {str(e)}")
            raise

    def transcribe(self, audio_path, output_base=None):
        """
        转录音频文件

        参数:
            audio_path: 音频文件路径
            output_base: 输出文件基础名，如果为None则使用音频文件名

        返回:
            dict: 包含转录结果的字典
                - transcript: 纯文本转录结果
                - merge_txt_path: 合并文本文件路径
        """
        try:
            logger.info(f"开始转录音频文件: {audio_path}")

            # 如果未指定输出基础名，则使用音频文件名（不含扩展名）
            if output_base is None:
                output_base = os.path.splitext(os.path.basename(audio_path))[0]

            # 准备输出文件路径
            output_base_path = os.path.join(self.output_dir, output_base)
            merge_txt_path = f"{output_base_path}.merge.txt"
            final_txt_path = f"{output_base_path}.txt"

            # 确保音频文件存在
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"音频文件不存在: {audio_path}")

            # 本地 mlx-whisper 引擎优先：启用时直接本地转录，无需远程 CapsWriter 服务器
            if self.config.get("local_whisper", {}).get("enabled", False):
                return self._transcribe_local_whisper(audio_path, output_base)

            # 使用CapsWriter客户端进行转录（客户端内部已有重试逻辑）
            logger.info(f"调用CapsWriter客户端转录文件: {audio_path}")
            success, generated_files = self.capswriter_client.transcribe_file(
                audio_path
            )

            if success and generated_files:
                logger.info(f"转录完成，生成文件: {[str(f) for f in generated_files]}")

                # 准备返回结果
                result = {
                    "transcript": "",
                    "txt_path": None,
                    "funasr_json_data": None,  # 用于存储 FunASR 兼容格式的 JSON 数据
                    "generated_files": generated_files,  # 返回生成的文件列表，供后续清理
                }

                # 处理生成的文件
                for file_path in generated_files:
                    # 将Path对象转换为字符串
                    file_path_str = str(file_path)

                    # 处理txt文件
                    if file_path_str.endswith(".txt") and not file_path_str.endswith(
                        ".merge.txt"
                    ):
                        result["txt_path"] = file_path_str

                        # 读取转录文本
                        try:
                            with open(file_path_str, "r", encoding="utf-8") as f:
                                result["transcript"] = f.read().strip()
                            logger.info(f"已从文本文件提取转录文本")
                        except Exception as e:
                            logger.warning(f"读取转录文本失败: {str(e)}")

                    # 处理 FunASR 兼容格式的 JSON 文件
                    elif file_path_str.endswith("_funasr.json"):
                        try:
                            import json

                            with open(file_path_str, "r", encoding="utf-8") as f:
                                result["funasr_json_data"] = json.load(f)
                            logger.info(f"已读取 FunASR 兼容格式 JSON: {file_path_str}")
                        except Exception as e:
                            logger.warning(f"读取 FunASR JSON 失败: {str(e)}")

                # 确保找到了txt文件
                if not result["txt_path"]:
                    error_msg = f"未找到文本文件: {audio_path}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                return result
            else:
                error_msg = f"转录文件失败: {audio_path}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.exception(f"转录音频文件失败: {str(e)}")
            raise

    def _transcribe_local_whisper(self, audio_path, output_base):
        """
        使用本地 mlx-whisper 转录（macOS Apple Silicon 本地引擎）。
        产出与 CapsWriter 路径一致的结果结构，后续 LLM 校对/总结链路无需改动。

        参数:
            audio_path: 音频/视频文件路径（mlx-whisper 内部用 ffmpeg 解码，两者皆可）
            output_base: 输出文件基础名（不含扩展名）

        返回:
            dict: {transcript, txt_path, funasr_json_data, generated_files}
        """
        import subprocess

        lw = self.config.get("local_whisper", {})
        binary = os.path.expanduser(
            lw.get("binary", "~/.venvs/mlx-whisper/bin/mlx_whisper")
        )
        model = lw.get("model", "mlx-community/whisper-large-v3-turbo")
        language = (lw.get("language") or "").strip()
        timeout = lw.get("timeout", 1800)

        if not os.path.exists(binary):
            raise RuntimeError(
                f"本地 mlx-whisper 可执行文件不存在: {binary}（请检查 config.local_whisper.binary）"
            )

        txt_path = os.path.join(self.output_dir, f"{output_base}.txt")
        json_path = os.path.join(self.output_dir, f"{output_base}.json")
        cmd = [
            binary,
            audio_path,
            "--model", model,
            "--output-dir", self.output_dir,
            "--output-name", output_base,
            "--output-format", "json",
            "--verbose", "False",
        ]
        if language:
            cmd += ["--language", language]

        logger.info(
            f"本地 mlx-whisper 转录开始: model={model}, lang={language or 'auto'}, audio={audio_path}"
        )
        start = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"本地 mlx-whisper 转录超时(>{timeout}s): {audio_path}")

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-600:]
            raise RuntimeError(
                f"本地 mlx-whisper 转录失败 (exit {proc.returncode}): {tail}"
            )

        if not os.path.exists(json_path):
            raise RuntimeError(f"本地 mlx-whisper 未生成 JSON 文件: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            whisper_data = json.load(f)

        transcript = (whisper_data.get("text") or "").strip()
        if not transcript:
            transcript = "\n".join(
                (segment.get("text") or "").strip()
                for segment in whisper_data.get("segments", [])
                if isinstance(segment, dict) and (segment.get("text") or "").strip()
            ).strip()

        if not transcript:
            raise RuntimeError(f"本地 mlx-whisper 转录结果为空: {json_path}")

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(transcript)

        funasr_json_data = self._whisper_json_to_funasr(whisper_data, audio_path)

        logger.info(
            f"本地 mlx-whisper 转录完成，用时 {time.time() - start:.1f}s，文本长度 {len(transcript)}"
        )

        return {
            "transcript": transcript,
            "txt_path": txt_path,
            "funasr_json_data": funasr_json_data,
            "generated_files": [Path(txt_path), Path(json_path)],
        }

    @staticmethod
    def _whisper_json_to_funasr(payload, audio_path):
        segments = []
        for segment in payload.get("segments", []):
            if not isinstance(segment, dict):
                continue
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            start_time = Transcriber._as_seconds(segment.get("start"))
            end_time = Transcriber._as_seconds(segment.get("end"))
            segments.append(
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "text": text,
                }
            )

        duration = Transcriber._as_seconds(payload.get("duration"))
        if duration is None and segments:
            end_times = [
                segment["end_time"]
                for segment in segments
                if segment.get("end_time") is not None
            ]
            if end_times:
                duration = max(end_times)

        return {
            "task_id": "",
            "file_name": os.path.basename(audio_path),
            "duration": duration or 0,
            "segments": segments,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "processing_time": 0,
            "error": None,
        }

    @staticmethod
    def _as_seconds(value):
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number, 3)
