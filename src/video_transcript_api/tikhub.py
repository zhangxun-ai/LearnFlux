"""TikHub REST API client."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

import requests

from .utils.logging import setup_logger

logger = setup_logger("tikhub_client")

_DEFAULT_BASE_URL = "https://api.tikhub.io"
_DEFAULT_CACHE_DIR = "./data/cache/tikhub"
_DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
_PLACEHOLDER_KEYS = {
    "",
    "your-tikhub-api-key-here",
    "请替换为您的实际API密钥",
}


class TikHubError(ValueError):
    """Base TikHub client error."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TikHubAuthError(TikHubError):
    """TikHub authentication or authorization failed."""


class TikHubPaymentRequiredError(TikHubError):
    """TikHub account balance or quota is insufficient."""


class TikHubRateLimitError(TikHubError):
    """TikHub request was rate limited."""


class TikHubRequestError(TikHubError):
    """TikHub request failed for a non-auth, non-quota reason."""


class TikHubClient:
    """Small synchronous client for TikHub REST endpoints."""

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        tikhub_config = config or {}
        self.base_url = (tikhub_config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        self.api_key = self._clean_key(tikhub_config.get("api_key"))
        self.alternate_api_key = self._clean_key(tikhub_config.get("alternate_api_key"))
        self.max_retries = max(int(tikhub_config.get("max_retries", 3)), 1)
        self.retry_delay = float(tikhub_config.get("retry_delay", 2))
        self.timeout = tikhub_config.get("timeout", 30)
        self.cache_enabled = self._as_bool(tikhub_config.get("cache_enabled", True))
        self.cache_ttl_seconds = int(
            tikhub_config.get("cache_ttl_seconds", _DEFAULT_CACHE_TTL_SECONDS)
        )
        self.cache_dir = Path(tikhub_config.get("cache_dir") or _DEFAULT_CACHE_DIR)

    def get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict:
        return self.request("GET", endpoint, params=params)

    def post(
        self,
        endpoint: str,
        payload: Optional[dict[str, Any]] = None,
        min_timeout: Optional[float] = None,
    ) -> dict:
        return self.request("POST", endpoint, json_body=payload, min_timeout=min_timeout)

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        min_timeout: Optional[float] = None,
    ) -> dict:
        method = method.upper()
        keys = self._api_keys()
        if not keys:
            raise TikHubAuthError("TikHub API key is not configured")

        cached = self._read_cache(method, endpoint, params, json_body)
        if cached is not None:
            return cached

        last_error: Optional[TikHubError] = None
        for index, api_key in enumerate(keys):
            try:
                result = self._request_with_key(
                    method,
                    endpoint,
                    api_key,
                    params=params,
                    json_body=json_body,
                    min_timeout=min_timeout,
                )
                self._write_cache(method, endpoint, params, json_body, result)
                return result
            except TikHubError as exc:
                last_error = exc
                if index + 1 >= len(keys) or exc.status_code == 404:
                    break
                logger.warning(
                    "TikHub request failed with primary key, trying alternate key"
                )

        if last_error:
            raise last_error
        raise TikHubRequestError("TikHub request failed")

    def _request_with_key(
        self,
        method: str,
        endpoint: str,
        api_key: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        min_timeout: Optional[float] = None,
    ) -> dict:
        url = self._url(endpoint)
        headers = self._headers(api_key, method)
        timeout = self._timeout(min_timeout)
        last_error: Optional[TikHubError] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"Requesting TikHub {method} {url} "
                    f"(attempt {attempt}/{self.max_retries})"
                )
                if method == "GET":
                    response = requests.get(
                        url,
                        headers=headers,
                        params=params,
                        timeout=timeout,
                    )
                elif method == "POST":
                    response = requests.post(
                        url,
                        headers=headers,
                        json=json_body,
                        timeout=timeout,
                    )
                else:
                    raise TikHubRequestError(f"Unsupported TikHub method: {method}")

                if response.status_code == 200:
                    return self._json_dict(response)

                error = self._error_for_response(response)
                if response.status_code >= 500 and attempt < self.max_retries:
                    last_error = error
                    time.sleep(self.retry_delay)
                    continue
                raise error
            except requests.RequestException as exc:
                last_error = TikHubRequestError(f"TikHub request failed: {exc}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue
                raise last_error

        if last_error:
            raise last_error
        raise TikHubRequestError("TikHub request failed")

    def _url(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _headers(self, api_key: str, method: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
        return headers

    def _timeout(self, min_timeout: Optional[float]) -> Any:
        if min_timeout is None:
            return self.timeout
        return max(float(self.timeout), float(min_timeout))

    def _api_keys(self) -> list[str]:
        keys = []
        if self.api_key:
            keys.append(self.api_key)
        if self.alternate_api_key and self.alternate_api_key not in keys:
            keys.append(self.alternate_api_key)
        return keys

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _clean_key(value: Any) -> str:
        key = str(value or "").strip()
        if key in _PLACEHOLDER_KEYS:
            return ""
        return key

    def _read_cache(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]],
        json_body: Optional[dict[str, Any]],
    ) -> Optional[dict]:
        if not self.cache_enabled or self.cache_ttl_seconds <= 0:
            return None
        cache_file = self._cache_file(method, endpoint, params, json_body)
        if not cache_file.exists():
            return None
        if time.time() - cache_file.stat().st_mtime > self.cache_ttl_seconds:
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"TikHub cache read failed: {cache_file}, error={exc}")
            return None
        return data if isinstance(data, dict) else None

    def _write_cache(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]],
        json_body: Optional[dict[str, Any]],
        result: dict,
    ) -> None:
        if not self.cache_enabled or self.cache_ttl_seconds <= 0:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self._cache_file(method, endpoint, params, json_body)
            cache_file.write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"TikHub cache write failed: error={exc}")

    def _cache_file(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]],
        json_body: Optional[dict[str, Any]],
    ) -> Path:
        payload = {
            "method": method,
            "url": self._url(endpoint),
            "params": params or {},
            "json": json_body or {},
        }
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _json_dict(self, response: requests.Response) -> dict:
        try:
            result = response.json()
        except json.JSONDecodeError as exc:
            raise TikHubRequestError(f"TikHub returned invalid JSON: {exc}") from exc
        except ValueError as exc:
            raise TikHubRequestError(f"TikHub returned invalid JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise TikHubRequestError(
                f"TikHub response is not a JSON object: {type(result)}"
            )
        return result

    def _error_for_response(self, response: requests.Response) -> TikHubError:
        message = self._response_message(response)
        status_code = response.status_code
        full_message = f"TikHub request failed with HTTP {status_code}: {message}"

        if status_code in (401, 403):
            return TikHubAuthError(full_message, status_code)
        if status_code == 402:
            return TikHubPaymentRequiredError(full_message, status_code)
        if status_code == 429:
            return TikHubRateLimitError(full_message, status_code)
        return TikHubRequestError(full_message, status_code)

    @staticmethod
    def _response_message(response: requests.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                return (
                    data.get("message")
                    or data.get("message_zh")
                    or data.get("detail")
                    or str(data)
                )
            return str(data)
        except Exception:
            return response.text[:200] if response.text else "unknown error"
