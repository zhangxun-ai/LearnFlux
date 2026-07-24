"""Protocol-only client for Aliyun Bailian asynchronous Fun-ASR."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests


_SAFE_ERROR_CODES = frozenset(
    {
        "missing_credentials",
        "invalid_host",
        "invalid_response",
        "http_error",
        "request_error",
        "provider_failed",
        "result_expired",
        "submission_unknown",
        "polling_unknown",
        "invalid_poll_config",
    }
)
_WORKSPACE_ID_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE
)
MODEL = "fun-asr-2025-11-07"
_UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
_DEFAULT_TIMEOUTS = {
    "upload_policy": 30,
    "upload": 120,
    "submit": 30,
    "poll": 30,
    "download": 30,
}
_KNOWN_STATUSES = frozenset(
    {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED"}
)
_ACTIVE_STATUSES = frozenset({"PENDING", "RUNNING"})


class AliyunASRError(RuntimeError):
    """Provider failure containing only allow-listed diagnostic metadata."""

    def __init__(
        self,
        code: str,
        http_status: int | None = None,
        *,
        usage_seconds: int | float | None = None,
    ) -> None:
        self.code = code if code in _SAFE_ERROR_CODES else "invalid_response"
        self.http_status = http_status
        self.usage_seconds = usage_seconds
        super().__init__(self.code)


class PreflightError(AliyunASRError):
    """Local configuration failure raised before any network request."""


class PotentiallyAcceptedError(AliyunASRError):
    """Submission may have been accepted before the response was lost."""


class PollTimeoutError(AliyunASRError):
    """Polling ended locally and may resume only the same provider task."""


@dataclass(frozen=True, slots=True)
class AliyunCredentials:
    """Explicit Aliyun credentials used to construct a real client."""

    api_key: str
    workspace_id: str
    api_host: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, Any]) -> "AliyunCredentials":
        """Read credentials only from the supplied environment mapping."""
        values = (
            environ.get("DASHSCOPE_API_KEY"),
            environ.get("DASHSCOPE_WORKSPACE_ID"),
            environ.get("DASHSCOPE_API_HOST"),
        )
        if any(not isinstance(value, str) or not value for value in values):
            raise PreflightError("missing_credentials")
        return cls(*values)


class AliyunASRClient:
    """Injected-session client for the Beijing Bailian Fun-ASR protocol."""

    def __init__(
        self,
        api_key: str,
        workspace_id: str,
        *,
        api_host: str | None = None,
        session: Any = None,
        sleep: Any = time.sleep,
        clock: Any = time.monotonic,
        timeouts: Mapping[str, Any] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._api_host = _validated_api_host(workspace_id, api_host)
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._stop_event = stop_event
        self._timeouts = dict(_DEFAULT_TIMEOUTS)
        if timeouts:
            self._timeouts.update(timeouts)

    def set_stop_event(self, stop_event: threading.Event) -> None:
        """Attach the owning recovery worker's cooperative stop signal."""
        self._stop_event = stop_event

    def _raise_if_stopped(self) -> None:
        if self._stop_event is not None and self._stop_event.is_set():
            raise PollTimeoutError("polling_unknown")

    def _headers(self, *, async_request: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if async_request:
            headers.update(
                {
                    "X-DashScope-Async": "enable",
                    "X-DashScope-OssResourceResolve": "enable",
                    "X-DashScope-WorkSpace": self._workspace_id,
                }
            )
        return headers

    def upload_audio(
        self,
        audio: Any,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Stage one audio object using a temporary DashScope upload policy."""
        response = _safe_get(
            self._session,
            _UPLOAD_POLICY_URL,
            headers=self._headers(),
            params={"action": "getPolicy", "model": MODEL},
            timeout=self._timeouts["upload_policy"],
        )
        payload = _json_payload(response)
        policy = payload.get("data")
        required = (
            "policy",
            "signature",
            "upload_dir",
            "upload_host",
            "oss_access_key_id",
            "x_oss_object_acl",
            "x_oss_forbid_overwrite",
        )
        if not isinstance(policy, Mapping) or any(
            not isinstance(policy.get(field), str) or not policy[field]
            for field in required
        ):
            raise AliyunASRError("invalid_response", _status_code(response))

        object_key = f"{policy['upload_dir'].rstrip('/')}/{filename.lstrip('/')}"
        upload_response = _safe_post(
            self._session,
            policy["upload_host"],
            data={
                "OSSAccessKeyId": policy["oss_access_key_id"],
                "Signature": policy["signature"],
                "policy": policy["policy"],
                "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
                "key": object_key,
                "success_action_status": "200",
            },
            files={"file": (filename, audio, content_type)},
            timeout=self._timeouts["upload"],
            allow_redirects=False,
        )
        _require_success(upload_response)
        return f"oss://{object_key}"

    def submit(
        self,
        staged_uri: str,
        language_hints: list[str],
        *,
        diarization_enabled: bool | None = None,
        speaker_count: int | None = None,
    ) -> dict[str, Any]:
        """Submit exactly one asynchronous Fun-ASR task."""
        parameters: dict[str, Any] = {"language_hints": list(language_hints)}
        if diarization_enabled is not None:
            parameters["diarization_enabled"] = diarization_enabled
        if speaker_count is not None:
            parameters["speaker_count"] = speaker_count
        response = _submit_once(
            self._session,
            f"{self._api_host}/api/v1/services/audio/asr/transcription",
            headers=self._headers(async_request=True),
            json={
                "model": MODEL,
                "input": {"file_urls": [staged_uri]},
                "parameters": parameters,
            },
            timeout=self._timeouts["submit"],
            allow_redirects=False,
        )
        payload = _json_payload(response)
        output = payload.get("output")
        if not isinstance(output, Mapping):
            raise AliyunASRError("invalid_response", _status_code(response))
        task_id = output.get("task_id")
        status = output.get("task_status")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or status not in _KNOWN_STATUSES
        ):
            raise AliyunASRError("invalid_response", _status_code(response))
        return {"task_id": task_id, "status": status}

    def poll(
        self,
        task_id: str,
        *,
        poll_interval_seconds: float = 1,
        timeout_seconds: float = 300,
    ) -> dict[str, Any]:
        """Poll only the supplied provider task until it reaches a terminal state."""
        started_at = self._clock()
        try:
            deadline = started_at + float(timeout_seconds)
            interval = float(poll_interval_seconds)
            request_timeout = float(self._timeouts["poll"])
        except (TypeError, ValueError, OverflowError):
            raise PreflightError("invalid_poll_config") from None
        if (
            not math.isfinite(deadline)
            or not math.isfinite(interval)
            or not math.isfinite(request_timeout)
            or deadline <= started_at
            or interval < 0
            or request_timeout <= 0
        ):
            raise PreflightError("invalid_poll_config")

        task_url = f"{self._api_host}/api/v1/tasks/{task_id}"
        now = started_at
        while True:
            self._raise_if_stopped()
            if now >= deadline:
                raise PollTimeoutError("polling_unknown")
            response = _poll_once(
                self._session,
                task_url,
                headers=self._headers(),
                timeout=min(request_timeout, deadline - now),
            )
            self._raise_if_stopped()
            payload = _json_payload(response)
            output = payload.get("output")
            if not isinstance(output, Mapping):
                raise AliyunASRError("invalid_response", _status_code(response))
            status = output.get("task_status")
            if status not in _KNOWN_STATUSES:
                raise AliyunASRError("invalid_response", _status_code(response))
            if status in {"FAILED", "CANCELED"}:
                raise AliyunASRError("provider_failed", _status_code(response))
            if status not in _ACTIVE_STATUSES:
                return self._terminal_result(task_id, payload, output)

            now = self._clock()
            if now >= deadline:
                raise PollTimeoutError("polling_unknown")
            sleep_seconds = min(interval, deadline - now)
            if sleep_seconds > 0:
                if self._stop_event is None:
                    self._sleep(sleep_seconds)
                elif self._stop_event.wait(sleep_seconds):
                    raise PollTimeoutError("polling_unknown")
            self._raise_if_stopped()
            now = self._clock()

    def _terminal_result(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_results: list[dict[str, Any]] = []
        successful_results = 0
        usage_seconds = _validated_usage_seconds(payload)
        provider_results = output.get("results", [])
        if not isinstance(provider_results, Sequence) or isinstance(
            provider_results, (str, bytes)
        ):
            raise AliyunASRError("invalid_response")
        for provider_result in provider_results:
            if not isinstance(provider_result, Mapping):
                raise AliyunASRError("invalid_response")
            subtask_status = provider_result.get("subtask_status")
            normalized: dict[str, Any] = {"status": subtask_status}
            if subtask_status == "SUCCEEDED":
                transcript_url = provider_result.get("transcription_url")
                if not isinstance(transcript_url, str) or not transcript_url:
                    raise AliyunASRError("invalid_response")
                transcript_response = _safe_get(
                    self._session,
                    transcript_url,
                    timeout=self._timeouts["download"],
                )
                if _status_code(transcript_response) == 403:
                    raise AliyunASRError(
                        "result_expired", 403, usage_seconds=usage_seconds
                    )
                normalized["transcript"] = _normalized_transcript(
                    _json_payload(transcript_response)
                )
                successful_results += 1
            normalized_results.append(normalized)
        if successful_results == 0:
            raise AliyunASRError("invalid_response")
        return {
            "task_id": task_id,
            "status": output.get("task_status"),
            "usage_seconds": usage_seconds,
            "results": normalized_results,
        }


def _validated_api_host(workspace_id: str, api_host: str | None) -> str:
    if (
        not isinstance(workspace_id, str)
        or _WORKSPACE_ID_PATTERN.fullmatch(workspace_id) is None
    ):
        raise PreflightError("invalid_host")
    expected_hostname = f"{workspace_id.casefold()}.cn-beijing.maas.aliyuncs.com"
    candidate = api_host or f"https://{expected_hostname}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except (TypeError, ValueError):
        raise PreflightError("invalid_host") from None
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != expected_hostname
        or parsed.netloc.casefold() != expected_hostname
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise PreflightError("invalid_host")
    return f"https://{expected_hostname}"


def _milliseconds_to_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AliyunASRError("invalid_response")
    if not math.isfinite(value):
        raise AliyunASRError("invalid_response")
    return value / 1000


def _validated_usage_seconds(payload: Mapping[str, Any]) -> int | float | None:
    if "usage" not in payload:
        return None
    usage = payload["usage"]
    if not isinstance(usage, Mapping):
        raise AliyunASRError("invalid_response")
    if "duration" not in usage:
        return None
    duration = usage["duration"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise AliyunASRError("invalid_response")
    return duration


def _normalized_timed_item(item: Any, *, include_words: bool) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise AliyunASRError("invalid_response")
    normalized: dict[str, Any] = {}
    for source, target in (
        ("text", "text"),
        ("begin_time", "start_time"),
        ("end_time", "end_time"),
        ("speaker_id", "speaker"),
    ):
        if source in item:
            normalized[target] = (
                _milliseconds_to_seconds(item[source])
                if source in {"begin_time", "end_time"}
                else item[source]
            )
    if include_words and "words" in item:
        words = item["words"]
        if not isinstance(words, Sequence) or isinstance(words, (str, bytes)):
            raise AliyunASRError("invalid_response")
        normalized["words"] = [
            _normalized_timed_item(word, include_words=False) for word in words
        ]
    return normalized


def _normalized_transcript(payload: Mapping[str, Any]) -> dict[str, Any]:
    transcripts = payload.get("transcripts")
    if not isinstance(transcripts, Sequence) or isinstance(
        transcripts, (str, bytes)
    ):
        raise AliyunASRError("invalid_response")
    transcript = transcripts[0] if transcripts else None
    if not isinstance(transcript, Mapping):
        raise AliyunASRError("invalid_response")
    text = transcript.get("text")
    if not isinstance(text, str):
        raise AliyunASRError("invalid_response")
    normalized: dict[str, Any] = {"text": text}
    if "sentences" in transcript:
        sentences = transcript["sentences"]
        if not isinstance(sentences, Sequence) or isinstance(
            sentences, (str, bytes)
        ):
            raise AliyunASRError("invalid_response")
        normalized["sentences"] = [
            _normalized_timed_item(sentence, include_words=True)
            for sentence in sentences
        ]
    return normalized


def _status_code(response: Any) -> int | None:
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _require_success(response: Any) -> None:
    status_code = _status_code(response)
    if status_code is None or not 200 <= status_code < 300:
        raise AliyunASRError("http_error", status_code)


def _json_payload(response: Any) -> Mapping[str, Any]:
    _require_success(response)
    try:
        payload = response.json()
    except (TypeError, ValueError):
        raise AliyunASRError("invalid_response", _status_code(response)) from None
    if not isinstance(payload, Mapping):
        raise AliyunASRError("invalid_response", _status_code(response))
    return payload


def _safe_get(session: Any, url: str, **kwargs: Any) -> Any:
    try:
        return session.get(url, **kwargs)
    except requests.exceptions.RequestException:
        raise AliyunASRError("request_error") from None


def _safe_post(session: Any, url: str, **kwargs: Any) -> Any:
    try:
        return session.post(url, **kwargs)
    except requests.exceptions.RequestException:
        raise AliyunASRError("request_error") from None


def _poll_once(session: Any, url: str, **kwargs: Any) -> Any:
    try:
        return session.get(url, **kwargs)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        raise PollTimeoutError("polling_unknown") from None
    except requests.exceptions.RequestException:
        raise AliyunASRError("request_error") from None


def _submit_once(session: Any, url: str, **kwargs: Any) -> Any:
    try:
        return session.post(url, **kwargs)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        raise PotentiallyAcceptedError("submission_unknown") from None
    except requests.exceptions.RequestException:
        raise AliyunASRError("request_error") from None
