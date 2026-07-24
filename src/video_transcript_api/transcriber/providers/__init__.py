"""Ordinary transcription provider implementations."""

from .aliyun_funasr import AliyunFunASRProvider
from .capswriter import CapsWriterProvider
from .local_whisper import LocalWhisperProvider

__all__ = [
    "AliyunFunASRProvider",
    "CapsWriterProvider",
    "LocalWhisperProvider",
]
