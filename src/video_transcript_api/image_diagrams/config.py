"""Dedicated, secret-safe configuration for manually requested image diagrams."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class ImageDiagramSettings:
    api_key: str = field(default="", repr=False)
    enabled: bool = False
    image_model: str = "gpt-image-2"
    text_model: str = "gpt-6-luna"
    quality: str = "high"
    size: str = "1536x2048"
    timeout: float = 240.0
    max_source_chars: int = 200000
    chunk_chars: int = 12000
    planning_workers: int = 3
    single_pass_chars: int = 200000
    max_daily_generations: int = 20
    data_dir: Path = Path("data/image_diagrams")

    @classmethod
    def from_config(
        cls, config: dict, environ: Mapping[str, str] | None = None
    ) -> "ImageDiagramSettings":
        """Read only this feature's settings; the key always stays in the environment."""
        env = os.environ if environ is None else environ
        values = config.get("image_diagrams") or {}
        if not isinstance(values, dict):
            raise ValueError("invalid_image_diagram_config")
        key = str(env.get("OPENAI_API_KEY") or "").strip()
        enabled = values.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("invalid_image_diagram_boolean")
        settings = cls(
            api_key=key,
            enabled=enabled and bool(key),
            image_model=str(values.get("image_model") or "gpt-image-2"),
            text_model=str(values.get("text_model") or "gpt-6-luna"),
            quality=str(values.get("quality") or "high"),
            size=str(values.get("size") or "1536x2048"),
            timeout=float(values.get("timeout", 240)),
            max_source_chars=int(values.get("max_source_chars", 200000)),
            chunk_chars=int(values.get("chunk_chars", 12000)),
            planning_workers=int(values.get("planning_workers", 3)),
            single_pass_chars=int(values.get("single_pass_chars", 200000)),
            max_daily_generations=int(values.get("max_daily_generations", 20)),
            data_dir=Path(values.get("data_dir") or "data/image_diagrams"),
        )
        if not settings.image_model.startswith("gpt-image-"):
            raise ValueError("invalid_image_diagram_model")
        if settings.quality not in {"low", "medium", "high", "auto"}:
            raise ValueError("invalid_image_diagram_quality")
        try:
            width, height = (int(part) for part in settings.size.split("x"))
        except (ValueError, TypeError):
            raise ValueError("invalid_image_diagram_size") from None
        if (
            min(width, height) <= 0
            or width % 16 or height % 16
            or max(width, height) > 3840
            or max(width, height) / min(width, height) > 3
            or not 655360 <= width * height <= 8294400
        ):
            raise ValueError("invalid_image_diagram_size")
        if not 10 <= settings.timeout <= 900:
            raise ValueError("invalid_image_diagram_timeout")
        if not 1000 <= settings.max_source_chars <= 500000:
            raise ValueError("invalid_image_diagram_source_limit")
        if not 128 <= settings.chunk_chars <= 24000:
            raise ValueError("invalid_image_diagram_chunk_limit")
        if not 1 <= settings.planning_workers <= 4:
            raise ValueError("invalid_image_diagram_planning_workers")
        if not 1000 <= settings.single_pass_chars <= 250000:
            raise ValueError("invalid_image_diagram_single_pass_limit")
        if not 0 <= settings.max_daily_generations <= 1000:
            raise ValueError("invalid_image_diagram_daily_limit")
        return settings
