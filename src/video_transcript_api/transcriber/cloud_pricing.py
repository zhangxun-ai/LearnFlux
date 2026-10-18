"""Non-blocking refresh of public Aliyun ASR pricing.

Only a successful, unambiguous official price replaces the last known price.
Quote generation reads memory; it never waits for an external HTTP request.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

import requests
from bs4 import BeautifulSoup

from video_transcript_api.transcriber.cloud_config import (
    DEFAULT_PRICE_CNY_PER_SECOND,
    MODEL,
    REGION,
)
from video_transcript_api.utils.logging import setup_logger


logger = setup_logger("cloud_pricing")
OFFICIAL_PRICE_URL = "https://help.aliyun.com/zh/model-studio/fun-asr"
REFRESH_INTERVAL = timedelta(days=7)
RETRY_INTERVAL = timedelta(days=1)


def _price(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid ASR price") from None
    if not result.is_finite() or result <= 0:
        raise ValueError("Invalid ASR price")
    return result


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("(", "（").replace(")", "）")


def parse_official_price(html: str) -> Decimal:
    """Read the Beijing per-second CNY price of the exact supported snapshot.

    Parsing is deliberately conservative: unrelated model sections, international
    regions, wrong units, or conflicting price rows are not usable evidence.
    """
    soup = BeautifulSoup(html, "html.parser")
    headings = ("h1", "h2", "h3", "h4", "h5", "h6")
    matches = [
        node for node in soup.find_all(headings)
        if node.get_text(" ", strip=True) == MODEL
    ]
    if len(matches) != 1:
        raise ValueError("Official ASR model section is missing or ambiguous")
    model_heading = matches[0]
    level = int(model_heading.name[1])
    in_prices = False
    in_beijing = False
    prices = []
    for node in model_heading.find_all_next(list(headings) + ["table"]):
        if node.name in headings:
            if int(node.name[1]) <= level:
                break
            label = _normalized(node.get_text(" ", strip=True))
            if label == "模型价格":
                in_prices = True
                in_beijing = False
            elif label == "华北2（北京）":
                in_beijing = in_prices
            else:
                in_beijing = False
                if label not in {"新加坡"}:
                    in_prices = False
            continue
        if not in_prices or not in_beijing:
            continue
        rows = node.find_all("tr")
        if not rows:
            continue
        headers = [
            _normalized(cell.get_text(" ", strip=True))
            for cell in rows[0].find_all(["th", "td"])
        ]
        if headers != ["计费项", "价格（元）", "单位"]:
            continue
        for row in rows[1:]:
            values = [
                _normalized(cell.get_text(" ", strip=True))
                for cell in row.find_all(["th", "td"])
            ]
            if len(values) == 3 and values[0] == "音频时长" and values[2] == "每秒":
                prices.append(_price(values[1]))
    if len(prices) != 1:
        raise ValueError("Official Beijing ASR price is missing or ambiguous")
    return prices[0]


def fetch_official_price() -> Decimal:
    """Fetch public documentation with bounded HTTP timeouts, without credentials."""
    response = requests.get(OFFICIAL_PRICE_URL, timeout=(5, 15))
    response.raise_for_status()
    return parse_official_price(response.text)


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Pricing timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


class CloudPricingService:
    """Refresh public prices in one daemon worker while ASR remains available."""

    def __init__(
        self,
        cache_path: str | Path,
        *,
        fetcher: Callable[[], Decimal] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.cache_path = Path(cache_path)
        self._fetcher = fetcher or fetch_official_price
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, Any] = {}
        self._next_check = self._now()
        self._load_cache()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _load_cache(self) -> None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if payload.get("model") != MODEL or payload.get("region") != REGION:
                return
            if payload.get("source") != OFFICIAL_PRICE_URL:
                return
            next_check = _timestamp(payload["next_check_at"])
            if "price_cny_per_second" not in payload:
                # Persist failed first checks too, without inventing a verification.
                self._next_check = min(next_check, self._now() + RETRY_INTERVAL)
                return
            verified = _timestamp(payload["verified_at"])
            if verified > self._now():
                return
            price = _price(payload["price_cny_per_second"])
            self._snapshot = {
                "model": MODEL,
                "region": REGION,
                "price_cny_per_second": str(price),
                "source": OFFICIAL_PRICE_URL,
                "verified_at": verified.isoformat(),
            }
            self._next_check = min(next_check, self._now() + REFRESH_INTERVAL)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # Missing or corrupt cache must not prevent the API from starting.
            return

    def status(self) -> dict[str, Any]:
        """Return non-sensitive pricing metadata for diagnostics."""
        with self._state_lock:
            return {
                "model": MODEL,
                "region": REGION,
                "source": OFFICIAL_PRICE_URL,
                **self._snapshot,
                "next_check_at": self._next_check.isoformat(),
            }

    def apply_cached_price(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Copy config and resolve price locally, keeping ASR credentials untouched."""
        result = dict(config)
        raw = config.get("cloud_asr")
        if not isinstance(raw, Mapping):
            return result
        cloud_asr = dict(raw)
        result["cloud_asr"] = cloud_asr
        if cloud_asr.get("model") != MODEL or cloud_asr.get("provider") != "aliyun":
            return result
        with self._state_lock:
            snapshot = dict(self._snapshot)
        if snapshot:
            cloud_asr["price_cny_per_second"] = snapshot["price_cny_per_second"]
            cloud_asr["price_verified_at"] = _timestamp(snapshot["verified_at"]).date().isoformat()
        else:
            try:
                cloud_asr["price_cny_per_second"] = str(
                    _price(cloud_asr.get("price_cny_per_second"))
                )
            except ValueError:
                cloud_asr["price_cny_per_second"] = str(DEFAULT_PRICE_CNY_PER_SECOND)
        return result

    def _persist(self) -> None:
        temporary_path: str | None = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self.status()
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.cache_path.parent,
                prefix=f".{self.cache_path.name}.", suffix=".tmp", delete=False,
            ) as output:
                temporary_path = output.name
                json.dump(payload, output, ensure_ascii=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.cache_path)
            temporary_path = None
        except OSError as exc:
            logger.warning("ASR pricing cache write failed: {}", type(exc).__name__)
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def refresh_if_due(self) -> bool:
        """Refresh at most once when due; failures only schedule another attempt."""
        if not self._refresh_lock.acquire(blocking=False):
            return False
        try:
            now = self._now()
            with self._state_lock:
                if now < self._next_check:
                    return False
            try:
                price = _price(self._fetcher())
            except Exception as exc:
                with self._state_lock:
                    self._next_check = self._now() + RETRY_INTERVAL
                self._persist()
                logger.warning(
                    "ASR pricing refresh failed; retaining current price: {}",
                    type(exc).__name__,
                )
                return False
            checked_at = self._now()
            with self._state_lock:
                self._snapshot = {
                    "model": MODEL,
                    "region": REGION,
                    "price_cny_per_second": str(price),
                    "source": OFFICIAL_PRICE_URL,
                    "verified_at": checked_at.isoformat(),
                }
                self._next_check = checked_at + REFRESH_INTERVAL
            self._persist()
            logger.info("ASR pricing refreshed from official documentation")
            return True
        finally:
            self._refresh_lock.release()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.refresh_if_due()
            with self._state_lock:
                delay = max(0.1, min(60.0, (self._next_check - self._now()).total_seconds()))
            self._stop_event.wait(delay)

    def start(self) -> None:
        """Start asynchronous checks; never perform HTTP in the caller thread."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="cloud-pricing", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Signal shutdown without waiting for an in-flight documentation request."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.1)
