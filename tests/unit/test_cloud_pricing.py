"""Offline regression tests for ASR pricing refresh and quote availability."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from video_transcript_api.transcriber.cloud_config import MODEL, REGION
from video_transcript_api.transcriber.cloud_pricing import (
    CloudPricingService,
    OFFICIAL_PRICE_URL,
    parse_official_price,
)


NOW = datetime(2026, 10, 3, 6, tzinfo=timezone.utc)


def config(price="0.00022"):
    return {
        "cloud_asr": {
            "enabled": True,
            "provider": "aliyun",
            "model": MODEL,
            "price_cny_per_second": price,
            "price_verified_at": "2026-08-23",
            "api_key": "test-secret-must-not-be-persisted",
        }
    }


def table(price="0.00022", unit="每秒", currency="元"):
    return (
        f"<table><tr><th>计费项</th><th>价格（{currency}）</th><th>单位</th></tr>"
        f"<tr><td>音频时长</td><td>{price}</td><td>{unit}</td></tr></table>"
    )


def official_html(price="0.00022", unit="每秒", currency="元"):
    return (
        "<h2>模型价格</h2><h4>华北2（北京）</h4>" + table("0.5")
        + f"<h2>快照版本</h2><h3>{MODEL}</h3><h4>模型价格</h4>"
        + "<h4>华北<span></span>2（北京）</h4>" + table(price, unit, currency)
        + "<h4>新加坡</h4>" + table("0.00026")
        + "<h4>限流</h4><h4>华北2（北京）</h4>"
        + "<table><tr><th>参数</th><th>值</th></tr><tr><td>RPM</td><td>600</td></tr></table>"
        + "<h3>fun-asr-2025-08-25</h3><h4>模型价格</h4><h4>华北2（北京）</h4>"
        + table("0.7")
    )


def write_cache(path, price="0.0003", verified=NOW - timedelta(days=41), next_check=NOW):
    path.write_text(json.dumps({
        "model": MODEL,
        "region": REGION,
        "source": OFFICIAL_PRICE_URL,
        "price_cny_per_second": price,
        "verified_at": verified.isoformat(),
        "next_check_at": next_check.isoformat(),
    }), encoding="utf-8")


def test_parse_exact_snapshot_beijing_price():
    assert parse_official_price(official_html("0.00031")) == Decimal("0.00031")


@pytest.mark.parametrize("html", [
    official_html().replace(MODEL, "fun-asr-flash-2025-11-07"),
    official_html().replace("华北<span></span>2（北京）", "新加坡"),
    official_html(unit="每分钟"),
    official_html(currency="美元"),
    official_html(price="NaN"),
    official_html(price="-0.1"),
    official_html(price="0"),
    official_html().replace("<h4>新加坡</h4>", table("0.9") + "<h4>新加坡</h4>"),
    official_html() + f"<h3>{MODEL}</h3>",
])
def test_reject_wrong_model_region_units_and_ambiguous_data(html):
    with pytest.raises(ValueError):
        parse_official_price(html)


def test_old_cached_price_is_immediately_available_without_http(tmp_path):
    path = tmp_path / "pricing.json"
    write_cache(path)
    def forbidden_fetch():
        pytest.fail("Quote generation must not request official documentation")
    service = CloudPricingService(path, fetcher=forbidden_fetch, clock=lambda: NOW)
    original = config()
    resolved = service.apply_cached_price(original)
    assert resolved["cloud_asr"]["price_cny_per_second"] == "0.0003"
    assert resolved["cloud_asr"]["price_verified_at"] == "2026-08-23"
    assert original["cloud_asr"]["price_cny_per_second"] == "0.00022"
    assert resolved["cloud_asr"]["api_key"] == original["cloud_asr"]["api_key"]


def test_failed_refresh_keeps_last_price_and_retries_next_day(tmp_path):
    path = tmp_path / "pricing.json"
    write_cache(path)
    attempts = []
    def fail():
        attempts.append(True)
        raise TimeoutError("Official documentation unavailable")
    current = [NOW]
    service = CloudPricingService(path, fetcher=fail, clock=lambda: current[0])
    assert service.refresh_if_due() is False
    assert service.apply_cached_price(config())["cloud_asr"]["price_cny_per_second"] == "0.0003"
    assert service.status()["next_check_at"] == (NOW + timedelta(days=1)).isoformat()
    assert service.refresh_if_due() is False
    assert len(attempts) == 1
    persisted = json.loads(path.read_text())
    assert persisted["verified_at"] == (NOW - timedelta(days=41)).isoformat()
    reloaded = CloudPricingService(path, fetcher=fail, clock=lambda: NOW)
    assert reloaded.refresh_if_due() is False
    current[0] += timedelta(days=1)
    assert service.refresh_if_due() is False
    assert len(attempts) == 2


def test_success_persists_public_metadata_and_refreshes_after_seven_days(tmp_path):
    path = tmp_path / "pricing.json"
    current = [NOW]
    attempts = []
    def fetch():
        attempts.append(True)
        return Decimal("0.00028")
    service = CloudPricingService(path, fetcher=fetch, clock=lambda: current[0])
    assert service.refresh_if_due() is True
    assert service.apply_cached_price(config())["cloud_asr"]["price_cny_per_second"] == "0.00028"
    assert "test-secret" not in path.read_text()
    current[0] += timedelta(days=7, seconds=-1)
    assert service.refresh_if_due() is False
    current[0] += timedelta(seconds=1)
    assert service.refresh_if_due() is True
    assert len(attempts) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_first_check_does_not_invent_verification_and_survives_restart(tmp_path):
    path = tmp_path / "pricing.json"
    attempts = []
    def fail():
        attempts.append(True)
        raise TimeoutError("Offline")
    service = CloudPricingService(path, fetcher=fail, clock=lambda: NOW)
    assert service.refresh_if_due() is False
    assert "verified_at" not in json.loads(path.read_text())
    reloaded = CloudPricingService(path, fetcher=fail, clock=lambda: NOW)
    assert reloaded.refresh_if_due() is False
    assert len(attempts) == 1
    assert reloaded.apply_cached_price(config())["cloud_asr"]["price_cny_per_second"] == "0.00022"


@pytest.mark.parametrize("configured_price", [None, "NaN", "-1", "0", "invalid"])
def test_missing_or_invalid_cached_data_uses_valid_fallback(tmp_path, configured_price):
    path = tmp_path / "pricing.json"
    path.write_text("broken JSON", encoding="utf-8")
    service = CloudPricingService(path, fetcher=lambda: Decimal("0.00022"), clock=lambda: NOW)
    resolved = service.apply_cached_price(config(configured_price))
    assert resolved["cloud_asr"]["price_cny_per_second"] == "0.00022"


def test_cache_for_other_region_does_not_override_config(tmp_path):
    path = tmp_path / "pricing.json"
    write_cache(path)
    payload = json.loads(path.read_text())
    payload["region"] = "ap-southeast-1"
    path.write_text(json.dumps(payload), encoding="utf-8")
    service = CloudPricingService(path, clock=lambda: NOW)
    assert service.apply_cached_price(config("0.0004"))["cloud_asr"]["price_cny_per_second"] == "0.0004"


def test_only_one_refresh_runs_and_stop_does_not_wait_for_network(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    attempts = []
    def slow_fetch():
        attempts.append(True)
        entered.set()
        assert release.wait(timeout=2)
        return Decimal("0.00022")
    service = CloudPricingService(tmp_path / "pricing.json", fetcher=slow_fetch, clock=lambda: NOW)
    try:
        before = time.monotonic()
        service.start()
        assert time.monotonic() - before < 0.2
        assert entered.wait(timeout=1)
        service.start()
        assert service.refresh_if_due() is False
        assert service.apply_cached_price(config())["cloud_asr"]["price_cny_per_second"] == "0.00022"
        before = time.monotonic()
        service.stop()
        assert time.monotonic() - before < 0.3
        assert len(attempts) == 1
    finally:
        release.set()
        service._thread.join(timeout=2)


def test_unrelated_model_config_is_unchanged(tmp_path):
    path = tmp_path / "pricing.json"
    write_cache(path)
    service = CloudPricingService(path, clock=lambda: NOW)
    original = config()
    original["cloud_asr"]["model"] = "other-model"
    assert service.apply_cached_price(original) == original
