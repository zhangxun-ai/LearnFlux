"""Configuration used when preparing and submitting cloud ASR tasks."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Mapping


PROVIDER = "aliyun"
MODEL = "fun-asr-2025-11-07"
REGION = "cn-beijing"
DEFAULT_PRICE_CNY_PER_SECOND = Decimal("0.00022")

_SAFE_ERROR_CODES = frozenset(
    {
        "invalid_cloud_asr_config",
        "cloud_asr_disabled",
        "invalid_provider",
        "invalid_model",
        "invalid_price",
        "invalid_price_verification",
        "invalid_poll_interval",
        "invalid_poll_timeout",
        "invalid_audio_seconds",
    }
)


class CloudASRConfigError(ValueError):
    """A safe cloud-ASR configuration error."""

    def __init__(self, code: str) -> None:
        if code not in _SAFE_ERROR_CODES:
            code = "invalid_cloud_asr_config"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NewCloudSubmissionSettings:
    """Verified settings for a newly submitted cloud ASR task."""

    provider: str
    model: str
    region: str
    price_cny_per_second: Decimal
    price_verified_at: date
    poll_interval_seconds: int
    poll_timeout_seconds: int
    accepted_max_cost: Decimal | None = None

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        today: date,
    ) -> "NewCloudSubmissionSettings":
        cloud_asr = config.get("cloud_asr")
        if not isinstance(cloud_asr, Mapping):
            raise CloudASRConfigError("invalid_cloud_asr_config")
        if cloud_asr.get("enabled") is not True:
            raise CloudASRConfigError("cloud_asr_disabled")
        if cloud_asr.get("provider") != PROVIDER:
            raise CloudASRConfigError("invalid_provider")
        if cloud_asr.get("model") != MODEL:
            raise CloudASRConfigError("invalid_model")

        return cls(
            provider=PROVIDER,
            model=MODEL,
            region=REGION,
            price_cny_per_second=_fixed_price(cloud_asr.get("price_cny_per_second")),
            price_verified_at=_verified_price_date(
                cloud_asr.get("price_verified_at"), today
            ),
            poll_interval_seconds=_bounded_positive_int(
                cloud_asr.get("poll_interval_seconds", 1),
                maximum=60,
                code="invalid_poll_interval",
            ),
            poll_timeout_seconds=_bounded_positive_int(
                cloud_asr.get("poll_timeout_seconds", 3600),
                maximum=43200,
                code="invalid_poll_timeout",
            ),
            accepted_max_cost=None,
        )

    def estimated_cost(self, audio_seconds: Decimal | float | int | str) -> Decimal:
        seconds = _positive_decimal(audio_seconds, "invalid_audio_seconds")
        return seconds.to_integral_value(rounding=ROUND_CEILING) * self.price_cny_per_second

    def reserve_estimate(self, audio_seconds: Decimal | float | int | str) -> Decimal:
        """Return an estimate; user confirmation is the spending boundary."""
        return self.estimated_cost(audio_seconds)


def _positive_decimal(value: object, code: str) -> Decimal:
    decimal_value = _decimal(value, code)
    if decimal_value <= 0:
        raise CloudASRConfigError(code)
    return decimal_value


def _nonnegative_decimal(value: object, code: str) -> Decimal:
    decimal_value = _decimal(value, code)
    if decimal_value < 0:
        raise CloudASRConfigError(code)
    return decimal_value


def _fixed_price(value: object) -> Decimal:
    price = _nonnegative_decimal(value, "invalid_price")
    if price != DEFAULT_PRICE_CNY_PER_SECOND:
        raise CloudASRConfigError("invalid_price")
    return price


def _decimal(value: object, code: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise CloudASRConfigError(code) from None
    if not decimal_value.is_finite():
        raise CloudASRConfigError(code)
    return decimal_value


def _verified_price_date(value: object, today: date) -> date:
    try:
        verified_at = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise CloudASRConfigError("invalid_price_verification") from None
    if verified_at > today or (today - verified_at).days > 30:
        raise CloudASRConfigError("invalid_price_verification")
    return verified_at


def _bounded_positive_int(value: object, *, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise CloudASRConfigError(code)
    return value
