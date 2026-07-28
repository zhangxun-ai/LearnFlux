import os
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from video_transcript_api.transcriber.cloud_config import (
    CloudASRConfigError,
    DEFAULT_PRICE_CNY_PER_SECOND,
    MODEL,
    PROVIDER,
    REGION,
    NewCloudSubmissionSettings,
)


def _valid_config() -> dict[str, object]:
    return {
        "cloud_asr": {
            "enabled": True,
            "provider": "aliyun",
            "model": "fun-asr-2025-11-07",
            "price_cny_per_second": "0.00022",
            "price_verified_at": "2026-07-20",
        }
    }


def test_builds_fixed_new_submission_settings_and_estimates_with_decimal() -> None:
    settings = NewCloudSubmissionSettings.from_config(
        {
            "cloud_asr": {
                "enabled": True,
                "provider": "aliyun",
                "model": "fun-asr-2025-11-07",
                "price_cny_per_second": "0.00022",
                "price_verified_at": "2026-07-20",
            }
        },
        today=date(2026, 7, 21),
    )

    assert (PROVIDER, MODEL, REGION) == ("aliyun", "fun-asr-2025-11-07", "cn-beijing")
    assert DEFAULT_PRICE_CNY_PER_SECOND == Decimal("0.00022")
    assert settings.provider == PROVIDER
    assert settings.model == MODEL
    assert settings.region == REGION
    assert settings.poll_interval_seconds == 1
    assert settings.poll_timeout_seconds == 3600
    assert settings.estimated_cost(Decimal("2.1")) == Decimal("0.00066")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("enabled", False, "cloud_asr_disabled"),
        ("provider", "unexpected-provider", "invalid_provider"),
        ("model", "unexpected-model", "invalid_model"),
        ("price_cny_per_second", None, "invalid_price"),
        ("price_cny_per_second", "NaN", "invalid_price"),
        ("price_cny_per_second", "-0.00022", "invalid_price"),
        ("price_verified_at", None, "invalid_price_verification"),
        ("price_verified_at", "not-a-date", "invalid_price_verification"),
        ("price_verified_at", "2026-05-01", "invalid_price_verification"),
        ("price_verified_at", "2026-07-22", "invalid_price_verification"),
        ("poll_interval_seconds", 0, "invalid_poll_interval"),
        ("poll_interval_seconds", 61, "invalid_poll_interval"),
        ("poll_timeout_seconds", 0, "invalid_poll_timeout"),
        ("poll_timeout_seconds", 43201, "invalid_poll_timeout"),
    ],
)
def test_rejects_invalid_new_submission_settings_with_safe_code(
    field: str, value: object, code: str
) -> None:
    config = _valid_config()
    cloud_asr = config["cloud_asr"]
    assert isinstance(cloud_asr, dict)
    cloud_asr[field] = value

    with pytest.raises(CloudASRConfigError) as exc_info:
        NewCloudSubmissionSettings.from_config(config, today=date(2026, 7, 21))

    assert exc_info.value.code == code
    assert str(exc_info.value) == code


def test_rejects_price_that_differs_from_fixed_verified_price() -> None:
    config = _valid_config()
    cloud_asr = config["cloud_asr"]
    assert isinstance(cloud_asr, dict)
    cloud_asr["price_cny_per_second"] = "0.00023"

    with pytest.raises(CloudASRConfigError) as exc_info:
        NewCloudSubmissionSettings.from_config(config, today=date(2026, 7, 21))

    assert exc_info.value.code == "invalid_price"
    assert str(exc_info.value) == "invalid_price"


def test_quote_estimate_has_no_hidden_per_task_budget_cap() -> None:
    config = _valid_config()
    cloud_asr = config["cloud_asr"]
    assert isinstance(cloud_asr, dict)
    cloud_asr.pop("max_cny_per_task", None)
    settings = NewCloudSubmissionSettings.from_config(config, today=date(2026, 7, 21))

    assert settings.reserve_estimate(Decimal("5400")) == Decimal("1.18800")


def test_legacy_per_task_budget_setting_does_not_block_a_quoted_submission() -> None:
    config = _valid_config()
    cloud_asr = config["cloud_asr"]
    assert isinstance(cloud_asr, dict)
    cloud_asr["max_cny_per_task"] = "0"

    settings = NewCloudSubmissionSettings.from_config(config, today=date(2026, 7, 21))

    assert settings.reserve_estimate(Decimal("1")) == Decimal("0.00022")


@pytest.mark.parametrize("audio_seconds", [Decimal("NaN"), Decimal("0")])
def test_estimated_cost_rejects_non_billable_audio_duration(audio_seconds: Decimal) -> None:
    settings = NewCloudSubmissionSettings.from_config(
        _valid_config(), today=date(2026, 7, 21)
    )

    with pytest.raises(CloudASRConfigError) as exc_info:
        settings.estimated_cost(audio_seconds)

    assert exc_info.value.code == "invalid_audio_seconds"
    assert str(exc_info.value) == "invalid_audio_seconds"


def test_settings_are_immutable() -> None:
    settings = NewCloudSubmissionSettings.from_config(
        _valid_config(), today=date(2026, 7, 21)
    )

    with pytest.raises(FrozenInstanceError):
        settings.price_cny_per_second = Decimal("0.00023")


class _ExplodingEnvironment:
    def __getattribute__(self, name: str) -> object:
        if name == "__class__":
            return _ExplodingEnvironment
        raise AssertionError("New cloud submission settings must not read the environment")


def test_building_and_estimating_do_not_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(os, "environ", _ExplodingEnvironment())

        settings = NewCloudSubmissionSettings.from_config(
            _valid_config(), today=date(2026, 7, 21)
        )

        assert settings.reserve_estimate(Decimal("1")) == Decimal("0.00022")
