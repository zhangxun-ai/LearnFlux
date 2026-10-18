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


class LocalTranscriptionError(RuntimeError):
    """Expose a stable local failure code without subprocess output or paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def local_transcription_error_message(code: str) -> str:
    """Return a safe actionable message for a local transcription failure."""
    return {
        "local_binary_unavailable": "本地转录程序不可用，请检查安装和执行权限。",
        "local_transcription_timeout": "本地转录超过处理时限，请重试或改用云端转录。",
        "local_transcription_failed": "本地转录程序运行失败，请重试或检查本地模型。",
        "local_result_missing": "本地转录未生成结果，请重试。",
        "local_result_invalid": "本地转录结果格式异常，请重试。",
        "local_transcript_empty": "本地转录没有识别到语音，请检查音频或更换转录方式。",
        "low_quality_local_transcript": "本地转录结果包含异常重复，请重试或更换转录方式。",
        "local_result_write_failed": "本地转录结果保存失败，请检查可用磁盘空间和目录权限。",
    }.get(code, "本地转录失败，请重试。")


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
        if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            raise LocalTranscriptionError("local_binary_unavailable")
        timeout = self._transcription_timeout(audio_path, local_config)

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
            "Local transcription started: model={}, language={}, timeout={}s",
            model, language or "auto", timeout,
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
            logger.warning("Local transcription timed out after {}s", timeout)
            raise LocalTranscriptionError("local_transcription_timeout") from exc
        except OSError as exc:
            logger.warning("Local transcription could not start: {}", type(exc).__name__)
            raise LocalTranscriptionError("local_binary_unavailable") from exc

        if process.returncode != 0:
            logger.warning("Local transcription exited with code {}", process.returncode)
            raise LocalTranscriptionError("local_transcription_failed")

        if not os.path.isfile(json_path):
            raise LocalTranscriptionError("local_result_missing")

        try:
            with open(json_path, "r", encoding="utf-8") as file:
                whisper_data = json.load(file)
        except (OSError, UnicodeError, ValueError) as exc:
            logger.warning("Local result could not be read: {}", type(exc).__name__)
            raise LocalTranscriptionError("local_result_invalid") from exc
        if not isinstance(whisper_data, dict):
            raise LocalTranscriptionError("local_result_invalid")
        segments = whisper_data.get("segments", [])
        if (
            not isinstance(segments, list)
            or not isinstance(whisper_data.get("text", ""), (str, type(None)))
            or any(
                isinstance(segment, dict)
                and not isinstance(segment.get("text", ""), (str, type(None)))
                for segment in segments
            )
        ):
            raise LocalTranscriptionError("local_result_invalid")

        transcript = (whisper_data.get("text") or "").strip()
        if not transcript:
            transcript = "\n".join(
                (segment.get("text") or "").strip()
                for segment in segments
                if isinstance(segment, dict)
                and (segment.get("text") or "").strip()
            ).strip()

        if not transcript:
            raise LocalTranscriptionError("local_transcript_empty")

        nonempty_segments = [
            segment
            for segment in segments
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
            raise LocalTranscriptionError("low_quality_local_transcript")

        try:
            with open(txt_path, "w", encoding="utf-8") as file:
                file.write(transcript)
        except OSError as exc:
            logger.warning("Local result could not be saved: {}", type(exc).__name__)
            raise LocalTranscriptionError("local_result_write_failed") from exc

        funasr_json_data = self.whisper_json_to_funasr(whisper_data, audio_path)
        elapsed_seconds = time.time() - started_at
        logger.info(
            "Local transcription completed: elapsed={:.1f}s, text_length={}",
            elapsed_seconds, len(transcript),
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
    def _positive_number(value: Any, default: float) -> float:
        """Use a finite positive setting, or preserve a working default."""
        if isinstance(value, bool):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) and number > 0 else default

    def _transcription_timeout(
        self, audio_path: str, local_config: dict[str, Any]
    ) -> float:
        """Allow longer media more processing time; probing never blocks ASR."""
        base_timeout = self._positive_number(local_config.get("timeout"), 1800)
        duration = self._probe_duration(audio_path)
        if duration is None:
            return base_timeout
        factor = self._positive_number(local_config.get("timeout_duration_factor"), 1)
        maximum = self._positive_number(local_config.get("max_timeout"), 14400)
        return max(base_timeout, min(maximum, math.ceil(duration * factor)))

    @staticmethod
    def _probe_duration(audio_path: str) -> float | None:
        """Read duration with a bounded probe, tolerating missing/invalid metadata."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            duration = float(result.stdout.strip())
            return duration if math.isfinite(duration) and duration > 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            return None

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
        if value is None or value == "" or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number, 3) if math.isfinite(number) else None
