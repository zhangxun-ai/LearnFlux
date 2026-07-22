"""Provider-neutral contracts for ordinary speech transcription."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from .media_preparer import PreparedASRMedia


@dataclass(frozen=True)
class TranscriptionContext:
    """Metadata required to route and account for a cloud transcription task."""

    task_id: str
    platform: str
    media_id: str
    owner_key: str | None = None
    continuation_json: str | None = None
    accepted_max_cost: Decimal | None = None
    prepared_media: PreparedASRMedia | None = None

    def __post_init__(self) -> None:
        for field_name in ("task_id", "platform", "media_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be blank")


@dataclass(frozen=True)
class TranscriptionResult:
    """Typed result returned by an ordinary transcription provider."""

    transcript: str
    txt_path: str
    funasr_json_data: dict[str, Any] | None
    generated_files: tuple[Path, ...]
    provider: str
    model: str | None = None
    elapsed_seconds: float | None = None
    language: str | None = None
    audio_seconds: float | None = None
    usage_seconds: float | None = None
    estimated_cost: Decimal | None = None
    currency: str | None = None
    remote_status: str | None = None
    remote_task_id_hash: str | None = None
    usage_event_id: str | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        """Convert to the result shape consumed by existing call sites."""
        return {
            "transcript": self.transcript,
            "txt_path": self.txt_path,
            "funasr_json_data": self.funasr_json_data,
            "generated_files": list(self.generated_files),
        }


class TranscriptionProvider(Protocol):
    """Contract implemented by ordinary transcription backends."""

    name: str

    def transcribe(
        self,
        audio_path: str,
        output_base: str,
        *,
        context: TranscriptionContext | None = None,
    ) -> TranscriptionResult:
        """Transcribe one local media file."""
        ...
