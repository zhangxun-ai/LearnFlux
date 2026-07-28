"""Local MLX Whisper transcription provider."""

import json
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ...utils.logging import setup_logger
from ..contracts import TranscriptionContext, TranscriptionResult

logger = setup_logger("transcriber")


class LocalWhisperProvider:
    """Transcribe media with the configured local MLX Whisper binary."""

    name = "local_whisper"

    def __init__(self, config: dict[str, Any], output_dir: str):
        self.config = config
        self.output_dir = str(output_dir)

    def transcribe(
        self,
        audio_path: str,
        output_base: str,
        *,
        context: TranscriptionContext | None = None,
    ) -> TranscriptionResult:
        """Transcribe one audio or video file with MLX Whisper."""
        del context
        local_config = self.config.get("local_whisper", {})
        binary = os.path.expanduser(
            local_config.get("binary", "~/.venvs/mlx-whisper/bin/mlx_whisper")
        )
        model = local_config.get(
            "model", "mlx-community/whisper-large-v3-turbo"
        )
        language = (local_config.get("language") or "").strip()
        timeout = local_config.get("timeout", 1800)

        if not os.path.exists(binary):
            raise RuntimeError(
                f"本地 mlx-whisper 可执行文件不存在: {binary}（请检查 config.local_whisper.binary）"
            )

        txt_path = os.path.join(self.output_dir, f"{output_base}.txt")
        json_path = os.path.join(self.output_dir, f"{output_base}.json")
        command = [
            binary,
            audio_path,
            "--model",
            model,
            "--output-dir",
            self.output_dir,
            "--output-name",
            output_base,
            "--output-format",
            "json",
            "--verbose",
            "False",
        ]
        if language:
            command += ["--language", language]

        logger.info(
            f"本地 mlx-whisper 转录开始: model={model}, "
            f"lang={language or 'auto'}, audio={audio_path}"
        )
        started_at = time.time()
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"本地 mlx-whisper 转录超时(>{timeout}s): {audio_path}"
            ) from exc

        if process.returncode != 0:
            tail = (process.stderr or process.stdout or "")[-600:]
            raise RuntimeError(
                f"本地 mlx-whisper 转录失败 (exit {process.returncode}): {tail}"
            )

        if not os.path.exists(json_path):
            raise RuntimeError(f"本地 mlx-whisper 未生成 JSON 文件: {json_path}")

        with open(json_path, "r", encoding="utf-8") as file:
            whisper_data = json.load(file)

        transcript = (whisper_data.get("text") or "").strip()
        if not transcript:
            transcript = "\n".join(
                (segment.get("text") or "").strip()
                for segment in whisper_data.get("segments", [])
                if isinstance(segment, dict)
                and (segment.get("text") or "").strip()
            ).strip()

        if not transcript:
            raise RuntimeError(f"本地 mlx-whisper 转录结果为空: {json_path}")

        nonempty_segments = [
            segment
            for segment in whisper_data.get("segments", [])
            if isinstance(segment, dict)
            and (segment.get("text") or "").strip()
        ]
        compression_ratios = [
            float(segment["compression_ratio"])
            for segment in nonempty_segments
            if not isinstance(segment.get("compression_ratio"), bool)
            and isinstance(segment.get("compression_ratio"), (int, float))
            and math.isfinite(float(segment["compression_ratio"]))
        ]
        if (
            len(nonempty_segments) >= 2
            and len(compression_ratios) == len(nonempty_segments)
            and min(compression_ratios) >= 10
        ):
            raise RuntimeError("low_quality_local_transcript")

        with open(txt_path, "w", encoding="utf-8") as file:
            file.write(transcript)

        funasr_json_data = self.whisper_json_to_funasr(whisper_data, audio_path)
        elapsed_seconds = time.time() - started_at
        logger.info(
            f"本地 mlx-whisper 转录完成，用时 {elapsed_seconds:.1f}s，"
            f"文本长度 {len(transcript)}"
        )

        return TranscriptionResult(
            transcript=transcript,
            txt_path=txt_path,
            funasr_json_data=funasr_json_data,
            generated_files=(Path(txt_path), Path(json_path)),
            provider=self.name,
            model=model,
            elapsed_seconds=elapsed_seconds,
        )

    @staticmethod
    def whisper_json_to_funasr(
        payload: dict[str, Any], audio_path: str
    ) -> dict[str, Any]:
        """Convert Whisper JSON into the existing FunASR-compatible shape."""
        segments = []
        for segment in payload.get("segments", []):
            if not isinstance(segment, dict):
                continue
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start_time": LocalWhisperProvider.as_seconds(
                        segment.get("start")
                    ),
                    "end_time": LocalWhisperProvider.as_seconds(segment.get("end")),
                    "text": text,
                }
            )

        duration = LocalWhisperProvider.as_seconds(payload.get("duration"))
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
    def as_seconds(value: Any) -> float | None:
        """Normalize one timestamp to seconds without changing its scale."""
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number, 3)
