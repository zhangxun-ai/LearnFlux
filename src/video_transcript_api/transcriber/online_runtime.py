"""Safe runtime selection for local and online transcription infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv


class OnlineRuntimeConfigError(ValueError):
    """Configuration failure represented by a safe, value-free code."""


def _required_text(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _bounded_int(
    environ: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    error_code: str,
) -> int:
    raw = environ.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
        raise OnlineRuntimeConfigError(error_code)
    value = int(raw)
    if value < minimum or value > maximum:
        raise OnlineRuntimeConfigError(error_code)
    return value


def load_project_dotenv(path: str | Path) -> bool:
    """Load a dotenv file without overriding deployment-provided variables."""
    return bool(load_dotenv(dotenv_path=Path(path), override=False))


@dataclass(frozen=True, slots=True)
class OnlineRuntimeSettings:
    """Validated infrastructure settings whose representation is redacted."""

    persistence_backend: str = "sqlite"
    object_backend: str = "local"
    database_url: str | None = field(default=None, repr=False)
    s3_endpoint_url: str | None = field(default=None, repr=False)
    s3_bucket: str | None = field(default=None, repr=False)
    s3_region: str | None = field(default=None, repr=False)
    s3_access_key_id: str | None = field(default=None, repr=False)
    s3_secret_access_key: str | None = field(default=None, repr=False)
    presign_ttl_seconds: int = 900
    source_retention_days: int = 7

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "OnlineRuntimeSettings":
        """Build settings from an environment mapping and fail closed."""
        persistence = (
            _required_text(environ, "LEARNFLUX_PERSISTENCE_BACKEND") or "sqlite"
        ).lower()
        if persistence not in {"sqlite", "postgres"}:
            raise OnlineRuntimeConfigError("invalid_persistence_backend")

        object_backend = (
            _required_text(environ, "LEARNFLUX_OBJECT_BACKEND") or "local"
        ).lower()
        if object_backend not in {"local", "s3"}:
            raise OnlineRuntimeConfigError("invalid_object_backend")

        database_url = _required_text(environ, "DATABASE_URL")
        if persistence == "postgres" and not database_url:
            raise OnlineRuntimeConfigError("database_url_missing")

        s3_values = {
            "endpoint": _required_text(environ, "LEARNFLUX_S3_ENDPOINT_URL"),
            "bucket": _required_text(environ, "LEARNFLUX_S3_BUCKET"),
            "region": _required_text(environ, "LEARNFLUX_S3_REGION"),
            "access": _required_text(environ, "LEARNFLUX_S3_ACCESS_KEY_ID"),
            "secret": _required_text(environ, "LEARNFLUX_S3_SECRET_ACCESS_KEY"),
        }
        if object_backend == "s3":
            if not all(s3_values.values()):
                raise OnlineRuntimeConfigError("s3_config_incomplete")
            parsed_endpoint = urlsplit(s3_values["endpoint"] or "")
            if (
                parsed_endpoint.scheme != "https"
                or not parsed_endpoint.hostname
                or parsed_endpoint.username
                or parsed_endpoint.password
                or parsed_endpoint.query
                or parsed_endpoint.fragment
            ):
                raise OnlineRuntimeConfigError("invalid_s3_endpoint")

        return cls(
            persistence_backend=persistence,
            object_backend=object_backend,
            database_url=database_url,
            s3_endpoint_url=s3_values["endpoint"],
            s3_bucket=s3_values["bucket"],
            s3_region=s3_values["region"],
            s3_access_key_id=s3_values["access"],
            s3_secret_access_key=s3_values["secret"],
            presign_ttl_seconds=_bounded_int(
                environ,
                "LEARNFLUX_S3_PRESIGN_TTL_SECONDS",
                default=900,
                minimum=60,
                maximum=3600,
                error_code="invalid_presign_ttl",
            ),
            source_retention_days=_bounded_int(
                environ,
                "LEARNFLUX_SOURCE_RETENTION_DAYS",
                default=7,
                minimum=1,
                maximum=30,
                error_code="invalid_source_retention",
            ),
        )
