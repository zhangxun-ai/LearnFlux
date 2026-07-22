"""Rules and isolated HTTP clients for the remote ASR benchmark tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
import unicodedata
from urllib.parse import urlsplit

import requests


FUNASR_CNY_PER_SECOND = Decimal("0.00022")
GROQ_USD_PER_HOUR = Decimal("0.04")
GROQ_MINIMUM_REQUEST_SECONDS = Decimal("10")
SUPPORTED_CURRENCIES = frozenset({"CNY", "USD"})
FUNASR_MODEL = "fun-asr-2025-11-07"
GROQ_MODEL = "whisper-large-v3-turbo"
SUPPORTED_PROVIDERS = ("aliyun", "groq")
SUPPORTED_VARIANTS = ("main", "terms", "diarization")
SHORT_SAMPLE_IDS = (
    "zh_terms_clean_15s",
    "zh_terms_noise_15s",
    "en_clean_90s",
)
TERM_SAMPLE_IDS = SHORT_SAMPLE_IDS[:2]
MULTI_SPEAKER_SAMPLE_ID = "multi_speaker_5m"
LONG_SAMPLE_ID = "long_natural_20_60m"
REQUIRED_SAMPLE_IDS = SHORT_SAMPLE_IDS + (
    MULTI_SPEAKER_SAMPLE_ID,
    LONG_SAMPLE_ID,
)

_DEFAULT_TIMEOUTS = {
    "upload_policy": 30,
    "upload": 120,
    "submit": 30,
    "poll": 30,
    "download": 30,
    "groq": 120,
}
_ALIYUN_ACTIVE_STATUSES = frozenset({"PENDING", "RUNNING"})
_ALIYUN_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELED"})
_ALIYUN_KNOWN_STATUSES = _ALIYUN_ACTIVE_STATUSES | _ALIYUN_TERMINAL_STATUSES
_WORKSPACE_ID_PATTERN = re.compile(r"^[a-z0-9-]+$", re.IGNORECASE)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class RemoteASRError(RuntimeError):
    """Remote ASR failure containing only explicitly safe metadata."""

    def __init__(self, code: str, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code

    @property
    def safe_details(self) -> dict[str, Any]:
        return {"code": self.code, "status_code": self.status_code}


class PotentiallyAcceptedError(RemoteASRError):
    """A mutating request timed out after its acceptance became unknowable."""


class PollTimeoutError(RemoteASRError):
    """Polling ended locally without submitting another provider task."""


def _timeouts(overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(_DEFAULT_TIMEOUTS)
    if overrides:
        result.update(overrides)
    return result


def _status_code(response: Any) -> int | None:
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _require_success(response: Any) -> None:
    status_code = _status_code(response)
    if status_code is None or not 200 <= status_code < 300:
        raise RemoteASRError("http_error", status_code)


def _json_payload(response: Any) -> Mapping[str, Any]:
    _require_success(response)
    try:
        payload = response.json()
    except (TypeError, ValueError):
        raise RemoteASRError("invalid_response", _status_code(response)) from None
    if not isinstance(payload, Mapping):
        raise RemoteASRError("invalid_response", _status_code(response))
    return payload


def _safe_get(
    session: Any,
    url: str,
    *,
    timeout: Any,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"timeout": timeout}
    if headers is not None:
        kwargs["headers"] = dict(headers)
    if params is not None:
        kwargs["params"] = dict(params)
    try:
        return session.get(url, **kwargs)
    except requests.exceptions.Timeout:
        raise RemoteASRError("timeout") from None
    except requests.exceptions.RequestException:
        raise RemoteASRError("request_error") from None


def _safe_mutating_post(session: Any, url: str, **kwargs: Any) -> Any:
    try:
        return session.post(url, **kwargs)
    except requests.exceptions.Timeout:
        raise PotentiallyAcceptedError("timeout") from None
    except requests.exceptions.RequestException:
        raise RemoteASRError("request_error") from None


def _header(headers: Any, name: str) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if isinstance(key, str) and key.casefold() == name.casefold():
            return value if isinstance(value, str) else None
    return None


def _milliseconds_to_seconds(value: Any) -> int | float | Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise RemoteASRError("invalid_response")
    if isinstance(value, float) and not math.isfinite(value):
        raise RemoteASRError("invalid_response")
    if isinstance(value, Decimal) and not value.is_finite():
        raise RemoteASRError("invalid_response")
    return value / 1000


def _normalized_word(word: Any) -> dict[str, Any]:
    if not isinstance(word, Mapping):
        return {}
    result: dict[str, Any] = {}
    for source, target in (
        ("text", "text"),
        ("begin_time", "start_time"),
        ("end_time", "end_time"),
        ("speaker_id", "speaker"),
    ):
        if source in word:
            result[target] = (
                _milliseconds_to_seconds(word[source])
                if source in {"begin_time", "end_time"}
                else word[source]
            )
    return result


def _normalized_sentence(sentence: Any) -> dict[str, Any]:
    if not isinstance(sentence, Mapping):
        return {}
    result: dict[str, Any] = {}
    for source, target in (
        ("text", "text"),
        ("begin_time", "start_time"),
        ("end_time", "end_time"),
        ("speaker_id", "speaker"),
    ):
        if source in sentence:
            result[target] = (
                _milliseconds_to_seconds(sentence[source])
                if source in {"begin_time", "end_time"}
                else sentence[source]
            )
    words = sentence.get("words")
    if isinstance(words, Sequence) and not isinstance(words, (str, bytes)):
        result["words"] = [_normalized_word(word) for word in words]
    return result


def _normalized_aliyun_transcript(payload: Mapping[str, Any]) -> dict[str, Any]:
    transcripts = payload.get("transcripts")
    if not isinstance(transcripts, Sequence) or isinstance(transcripts, (str, bytes)):
        raise RemoteASRError("invalid_response")
    transcript = transcripts[0] if transcripts else None
    if not isinstance(transcript, Mapping):
        raise RemoteASRError("invalid_response")
    result: dict[str, Any] = {}
    if "text" in transcript:
        result["text"] = transcript["text"]
    sentences = transcript.get("sentences")
    if isinstance(sentences, Sequence) and not isinstance(sentences, (str, bytes)):
        result["sentences"] = [
            _normalized_sentence(sentence) for sentence in sentences
        ]
    return result


def _validated_aliyun_api_host(workspace_id: str, api_host: str | None) -> str:
    if (
        not isinstance(workspace_id, str)
        or _WORKSPACE_ID_PATTERN.fullmatch(workspace_id) is None
    ):
        raise PreflightError("workspace host configuration is invalid")
    expected_hostname = (
        f"{workspace_id.casefold()}.cn-beijing.maas.aliyuncs.com"
    )
    candidate = api_host or f"https://{expected_hostname}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except (TypeError, ValueError):
        raise PreflightError("Aliyun API host is invalid") from None
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
        raise PreflightError("Aliyun API host is invalid")
    return f"https://{expected_hostname}"


class AliyunASRClient:
    """Small injected-session client for the Fun-ASR benchmark protocol."""

    _UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"

    def __init__(
        self,
        api_key: str,
        workspace_id: str,
        *,
        api_host: str | None = None,
        session: Any = None,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeouts: Mapping[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._api_host = _validated_aliyun_api_host(workspace_id, api_host)
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._timeouts = _timeouts(timeouts)

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
        """Obtain an upload policy and stage one audio object in OSS."""
        policy_response = _safe_get(
            self._session,
            self._UPLOAD_POLICY_URL,
            params={"action": "getPolicy", "model": FUNASR_MODEL},
            headers=self._headers(),
            timeout=self._timeouts["upload_policy"],
        )
        policy_payload = _json_payload(policy_response)
        policy = policy_payload.get("data")
        if not isinstance(policy, Mapping):
            raise RemoteASRError("invalid_response", _status_code(policy_response))
        required = (
            "policy",
            "signature",
            "upload_dir",
            "upload_host",
            "oss_access_key_id",
            "x_oss_object_acl",
            "x_oss_forbid_overwrite",
        )
        if any(not isinstance(policy.get(field), str) for field in required):
            raise RemoteASRError("invalid_response", _status_code(policy_response))

        object_key = f"{policy['upload_dir'].rstrip('/')}/{filename.lstrip('/')}"
        upload_response = _safe_mutating_post(
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
        )
        _require_success(upload_response)
        return f"oss://{object_key}"

    def submit(
        self,
        staged_uri: str,
        language_hints: Sequence[str],
        *,
        diarization_enabled: bool | None = None,
        speaker_count: int | None = None,
    ) -> dict[str, Any]:
        """Submit exactly one asynchronous Fun-ASR task without retries."""
        parameters: dict[str, Any] = {"language_hints": list(language_hints)}
        if diarization_enabled is not None:
            parameters["diarization_enabled"] = diarization_enabled
        if speaker_count is not None:
            parameters["speaker_count"] = speaker_count
        response = _safe_mutating_post(
            self._session,
            f"{self._api_host}/api/v1/services/audio/asr/transcription",
            headers=self._headers(async_request=True),
            json={
                "model": FUNASR_MODEL,
                "input": {"file_urls": [staged_uri]},
                "parameters": parameters,
            },
            timeout=self._timeouts["submit"],
        )
        payload = _json_payload(response)
        output = payload.get("output")
        if not isinstance(output, Mapping):
            raise RemoteASRError("invalid_response", _status_code(response))
        task_id = output.get("task_id")
        status = output.get("task_status")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or status not in _ALIYUN_KNOWN_STATUSES
        ):
            raise RemoteASRError("invalid_response", _status_code(response))
        return {
            "task_id": task_id,
            "request_id": payload.get("request_id"),
            "status": status,
        }

    def poll(
        self,
        task_id: str,
        *,
        poll_interval_seconds: float = 1,
        timeout_seconds: float = 300,
    ) -> dict[str, Any]:
        """Poll only the supplied task, then fetch successful transcript files."""
        started_at = self._clock()
        try:
            deadline = started_at + float(timeout_seconds)
            configured_request_timeout = float(self._timeouts["poll"])
        except (TypeError, ValueError, OverflowError):
            raise PreflightError("poll timeout is invalid") from None
        if (
            not math.isfinite(deadline)
            or not math.isfinite(configured_request_timeout)
            or deadline <= started_at
            or configured_request_timeout <= 0
        ):
            raise PreflightError("poll timeout is invalid")
        task_url = f"{self._api_host}/api/v1/tasks/{task_id}"
        now = started_at
        while True:
            if now >= deadline:
                raise PollTimeoutError("poll_timeout")
            response = _safe_get(
                self._session,
                task_url,
                headers=self._headers(),
                timeout=min(configured_request_timeout, deadline - now),
            )
            payload = _json_payload(response)
            output = payload.get("output")
            if not isinstance(output, Mapping):
                raise RemoteASRError("invalid_response", _status_code(response))
            status = output.get("task_status")
            if status not in _ALIYUN_KNOWN_STATUSES:
                raise RemoteASRError("invalid_response", _status_code(response))
            if status in _ALIYUN_TERMINAL_STATUSES:
                return self._terminal_result(task_id, payload, output)
            now = self._clock()
            if now >= deadline:
                raise PollTimeoutError("poll_timeout")
            sleep_seconds = min(float(poll_interval_seconds), deadline - now)
            if sleep_seconds > 0:
                self._sleep(sleep_seconds)
            now = self._clock()

    def _terminal_result(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_results: list[dict[str, Any]] = []
        provider_results = output.get("results", [])
        if isinstance(provider_results, Sequence) and not isinstance(
            provider_results, (str, bytes)
        ):
            for provider_result in provider_results:
                if not isinstance(provider_result, Mapping):
                    continue
                normalized: dict[str, Any] = {
                    "status": provider_result.get("subtask_status")
                }
                transcript_url = provider_result.get("transcription_url")
                if (
                    provider_result.get("subtask_status") == "SUCCEEDED"
                    and isinstance(transcript_url, str)
                ):
                    transcript_response = _safe_get(
                        self._session,
                        transcript_url,
                        timeout=self._timeouts["download"],
                    )
                    normalized["transcript"] = _normalized_aliyun_transcript(
                        _json_payload(transcript_response)
                    )
                normalized_results.append(normalized)
        usage = payload.get("usage")
        return {
            "task_id": task_id,
            "request_id": payload.get("request_id"),
            "status": output.get("task_status"),
            "usage_seconds": usage.get("duration")
            if isinstance(usage, Mapping)
            else None,
            "results": normalized_results,
        }


class GroqASRClient:
    """Small injected-session client for Groq's transcription endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        api_host: str = "https://api.groq.com/openai/v1",
        session: Any = None,
        timeouts: Mapping[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_host = api_host.rstrip("/")
        self._session = session if session is not None else requests.Session()
        self._timeouts = _timeouts(timeouts)

    def transcribe(
        self,
        audio: Any,
        filename: str,
        language: str,
        *,
        prompt: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Send one timestamped transcription request without retries."""
        data: dict[str, Any] = {
            "model": GROQ_MODEL,
            "language": language,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["segment", "word"],
        }
        if prompt is not None:
            data["prompt"] = prompt
        response = _safe_mutating_post(
            self._session,
            f"{self._api_host}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            files={"file": (filename, audio, content_type)},
            data=data,
            timeout=self._timeouts["groq"],
        )
        payload = _json_payload(response)
        segments = payload.get("segments")
        words = payload.get("words")
        return {
            "request_id": _header(getattr(response, "headers", None), "x-request-id"),
            "text": payload.get("text"),
            "duration": payload.get("duration"),
            "segments": [
                {
                    key: segment[key]
                    for key in ("start", "end", "text")
                    if key in segment
                }
                for segment in segments
                if isinstance(segment, Mapping)
            ]
            if isinstance(segments, Sequence) and not isinstance(segments, (str, bytes))
            else [],
            "words": [
                {key: word[key] for key in ("start", "end", "word") if key in word}
                for word in words
                if isinstance(word, Mapping)
            ]
            if isinstance(words, Sequence) and not isinstance(words, (str, bytes))
            else [],
        }


def normalize_chinese(text: str) -> str:
    """Normalize Chinese benchmark text to comparable characters."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def normalize_english(text: str) -> str:
    """Normalize English benchmark text to lowercase word tokens."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", normalized))


def _edit_distance(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            substitution = previous[hypothesis_index - 1] + (
                reference_item != hypothesis_item
            )
            current.append(
                min(
                    previous[hypothesis_index] + 1,
                    current[hypothesis_index - 1] + 1,
                    substitution,
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return normalized Chinese CER; reject an empty normalized reference."""
    normalized_reference = normalize_chinese(reference)
    if not normalized_reference:
        raise ValueError("reference must not be empty after normalization")
    normalized_hypothesis = normalize_chinese(hypothesis)
    return _edit_distance(normalized_reference, normalized_hypothesis) / len(
        normalized_reference
    )


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Return normalized English WER; reject an empty normalized reference."""
    normalized_reference = normalize_english(reference).split()
    if not normalized_reference:
        raise ValueError("reference must not be empty after normalization")
    normalized_hypothesis = normalize_english(hypothesis).split()
    return _edit_distance(normalized_reference, normalized_hypothesis) / len(
        normalized_reference
    )


def term_hits(terms: Iterable[str], hypothesis: str, language: str) -> list[bool]:
    """Return one normalized hit flag per supplied benchmark term."""
    normalized_language = language.casefold()
    if normalized_language in {"zh", "chinese"}:
        normalized_hypothesis = normalize_chinese(hypothesis)
        return [
            bool(normalized_term)
            and normalized_term in normalized_hypothesis
            for term in terms
            for normalized_term in [normalize_chinese(term)]
        ]
    if normalized_language in {"en", "english"}:
        normalized_hypothesis = f" {normalize_english(hypothesis)} "
        return [
            bool(normalized_term)
            and f" {normalized_term} " in normalized_hypothesis
            for term in terms
            for normalized_term in [normalize_english(term)]
        ]
    raise ValueError("language must be 'zh' or 'en'")


def _decimal_duration(value: Any) -> Decimal:
    try:
        duration = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("duration must be a finite non-negative number") from None
    if not duration.is_finite() or duration < 0:
        raise ValueError("duration must be a finite non-negative number")
    return duration


def funasr_worst_case_cost_cny(audio_duration_seconds: Any) -> Decimal:
    """Reserve Fun-ASR cost using the complete audio duration."""
    return _decimal_duration(audio_duration_seconds) * FUNASR_CNY_PER_SECOND


def funasr_terminal_cost_cny(provider_usage_seconds: Any) -> Decimal:
    """Settle Fun-ASR cost using terminal provider usage."""
    return _decimal_duration(provider_usage_seconds) * FUNASR_CNY_PER_SECOND


def groq_request_cost_usd(duration_seconds: Any) -> Decimal:
    """Calculate one Groq request with its ten-second billing minimum."""
    duration = max(
        _decimal_duration(duration_seconds),
        GROQ_MINIMUM_REQUEST_SECONDS,
    )
    return duration / Decimal("3600") * GROQ_USD_PER_HOUR


def groq_chunked_cost_usd(chunk_durations_seconds: Iterable[Any]) -> Decimal:
    """Calculate Groq cost, applying the minimum independently per chunk."""
    return sum(
        (groq_request_cost_usd(duration) for duration in chunk_durations_seconds),
        Decimal("0"),
    )


class MatrixValidationError(ValueError):
    """Fail-closed manifest or action selection error with a safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BenchmarkAction:
    """One independently budgeted provider request in the benchmark matrix."""

    attempt_id: str
    action_id: str
    provider: str
    sample_id: str
    variant: str
    repeat_index: int
    action_index: int
    duration_seconds: Decimal
    currency: str
    worst_case_cost: Decimal


def _positive_duration(value: Any) -> Decimal:
    try:
        duration = _decimal_duration(value)
    except ValueError:
        raise MatrixValidationError("invalid_manifest") from None
    if duration <= 0:
        raise MatrixValidationError("invalid_manifest")
    return duration


def _validated_manifest_samples(
    manifest: Mapping[str, Any],
) -> tuple[str, dict[str, tuple[Mapping[str, Any], Decimal]]]:
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        raise MatrixValidationError("invalid_manifest")
    status = manifest.get("status")
    audio_profile = manifest.get("audio_profile")
    samples = manifest.get("samples")
    if (
        not isinstance(status, str)
        or not status.strip()
        or not isinstance(audio_profile, Mapping)
        or not isinstance(audio_profile.get("codec"), str)
        or not isinstance(audio_profile.get("sample_rate_hz"), int)
        or isinstance(audio_profile.get("sample_rate_hz"), bool)
        or audio_profile.get("sample_rate_hz", 0) <= 0
        or not isinstance(audio_profile.get("channels"), int)
        or isinstance(audio_profile.get("channels"), bool)
        or audio_profile.get("channels", 0) <= 0
        or not isinstance(samples, list)
    ):
        raise MatrixValidationError("invalid_manifest")

    indexed: dict[str, tuple[Mapping[str, Any], Decimal]] = {}
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise MatrixValidationError("invalid_manifest")
        sample_id = sample.get("id")
        language = sample.get("language")
        size_bytes = sample.get("size_bytes")
        sha256 = sample.get("sha256")
        if (
            not isinstance(sample_id, str)
            or not sample_id.strip()
            or sample_id in indexed
            or language not in {"zh", "en"}
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes <= 0
            or not isinstance(sha256, str)
            or _SHA256_PATTERN.fullmatch(sha256) is None
        ):
            raise MatrixValidationError("invalid_manifest")
        indexed[sample_id] = (sample, _positive_duration(sample.get("duration_seconds")))

    if any(sample_id not in indexed for sample_id in REQUIRED_SAMPLE_IDS):
        raise MatrixValidationError("invalid_manifest")
    _validated_groq_boundaries(*indexed[LONG_SAMPLE_ID])
    return status, indexed


def _validated_groq_boundaries(
    long_sample: Mapping[str, Any],
    sample_duration: Decimal,
) -> tuple[Decimal, ...]:
    transport = long_sample.get("groq_transport")
    if not isinstance(transport, Mapping):
        raise MatrixValidationError("invalid_manifest")
    try:
        chunk_seconds = _positive_duration(transport.get("chunk_seconds"))
        overlap = _decimal_duration(transport.get("overlap_seconds"))
    except ValueError:
        raise MatrixValidationError("invalid_manifest") from None
    boundaries = transport.get("boundaries_seconds")
    if (
        transport.get("mode") != "pre_registered_chunks"
        or overlap >= chunk_seconds
        or not isinstance(boundaries, list)
        or not boundaries
    ):
        raise MatrixValidationError("invalid_manifest")

    durations: list[Decimal] = []
    previous_end: Decimal | None = None
    for index, boundary in enumerate(boundaries):
        if not isinstance(boundary, list) or len(boundary) != 2:
            raise MatrixValidationError("invalid_manifest")
        try:
            start = _decimal_duration(boundary[0])
            end = _decimal_duration(boundary[1])
        except ValueError:
            raise MatrixValidationError("invalid_manifest") from None
        if (
            end <= start
            or end > sample_duration
            or (index == 0 and start != 0)
            or (previous_end is not None and start != previous_end - overlap)
        ):
            raise MatrixValidationError("invalid_manifest")
        durations.append(end - start)
        previous_end = end
    if previous_end != sample_duration or durations[-1] < GROQ_MINIMUM_REQUEST_SECONDS:
        raise MatrixValidationError("invalid_manifest")
    return tuple(durations)


def _selection(
    values: Iterable[str] | str | None,
    *,
    default: tuple[str, ...],
    allowed: frozenset[str],
) -> tuple[str, ...]:
    if values is None:
        selected = default
    elif isinstance(values, str):
        selected = tuple(part.strip() for part in values.split(",") if part.strip())
    else:
        selected = tuple(values)
    if not selected or len(set(selected)) != len(selected) or any(
        not isinstance(value, str) or value not in allowed for value in selected
    ):
        raise MatrixValidationError("invalid_selection")
    return tuple(value for value in default if value in selected)


def build_action_matrix(
    manifest: Mapping[str, Any],
    *,
    providers: Iterable[str] | str | None = None,
    sample_ids: Iterable[str] | str | None = None,
    repeats: int = 3,
    variants: Iterable[str] | str | None = None,
) -> list[BenchmarkAction]:
    """Build the stable, independently chargeable benchmark action matrix."""
    _status, samples = _validated_manifest_samples(manifest)
    selected_providers = _selection(
        providers,
        default=SUPPORTED_PROVIDERS,
        allowed=frozenset(SUPPORTED_PROVIDERS),
    )
    selected_samples = _selection(
        sample_ids,
        default=REQUIRED_SAMPLE_IDS,
        allowed=frozenset(REQUIRED_SAMPLE_IDS),
    )
    selected_variants = _selection(
        variants,
        default=SUPPORTED_VARIANTS,
        allowed=frozenset(SUPPORTED_VARIANTS),
    )
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats <= 0:
        raise MatrixValidationError("invalid_selection")

    actions: list[BenchmarkAction] = []

    def add_attempt(
        provider: str,
        sample_id: str,
        variant: str,
        repeat_index: int,
        durations: Iterable[Decimal],
    ) -> None:
        attempt_id = f"{provider}:{sample_id}:{variant}:r{repeat_index:02d}"
        currency = "CNY" if provider == "aliyun" else "USD"
        for action_index, duration in enumerate(durations, start=1):
            cost = (
                funasr_worst_case_cost_cny(duration)
                if provider == "aliyun"
                else groq_request_cost_usd(duration)
            )
            actions.append(
                BenchmarkAction(
                    attempt_id=attempt_id,
                    action_id=f"{attempt_id}:a{action_index:02d}",
                    provider=provider,
                    sample_id=sample_id,
                    variant=variant,
                    repeat_index=repeat_index,
                    action_index=action_index,
                    duration_seconds=duration,
                    currency=currency,
                    worst_case_cost=cost,
                )
            )

    for provider in selected_providers:
        if "main" in selected_variants:
            for sample_id in SHORT_SAMPLE_IDS:
                if sample_id in selected_samples:
                    duration = samples[sample_id][1]
                    for repeat_index in range(1, repeats + 1):
                        add_attempt(
                            provider,
                            sample_id,
                            "main",
                            repeat_index,
                            (duration,),
                        )
            if MULTI_SPEAKER_SAMPLE_ID in selected_samples:
                add_attempt(
                    provider,
                    MULTI_SPEAKER_SAMPLE_ID,
                    "main",
                    1,
                    (samples[MULTI_SPEAKER_SAMPLE_ID][1],),
                )
            if LONG_SAMPLE_ID in selected_samples:
                long_sample, long_duration = samples[LONG_SAMPLE_ID]
                durations = (
                    (long_duration,)
                    if provider == "aliyun"
                    else _validated_groq_boundaries(long_sample, long_duration)
                )
                add_attempt(provider, LONG_SAMPLE_ID, "main", 1, durations)
        if "terms" in selected_variants:
            for sample_id in TERM_SAMPLE_IDS:
                if sample_id in selected_samples:
                    add_attempt(
                        provider,
                        sample_id,
                        "terms",
                        1,
                        (samples[sample_id][1],),
                    )
        if (
            "diarization" in selected_variants
            and provider == "aliyun"
            and MULTI_SPEAKER_SAMPLE_ID in selected_samples
        ):
            add_attempt(
                provider,
                MULTI_SPEAKER_SAMPLE_ID,
                "diarization",
                1,
                (samples[MULTI_SPEAKER_SAMPLE_ID][1],),
            )
    return actions


def _money(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


@dataclass
class _Commitment:
    amount: Decimal
    state: str = "reserved"


@dataclass
class BudgetLedger:
    """Fail-closed, single-currency budget commitments for benchmark calls."""

    limit: Any
    currency: str
    spent: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")
    committed_unknown: Decimal = Decimal("0")
    recovered_commitments: Mapping[str, Mapping[str, Any]] | None = field(
        default=None,
        repr=False,
    )
    _commitments: dict[str, _Commitment] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        parsed_limit = _money(self.limit)
        self.limit = parsed_limit if parsed_limit and parsed_limit > 0 else None
        self.currency = self.currency.upper() if isinstance(self.currency, str) else ""
        for bucket_name in ("spent", "reserved", "committed_unknown"):
            amount = _money(getattr(self, bucket_name))
            if amount is None:
                raise ValueError(
                    f"{bucket_name} must be a finite non-negative number"
                )
            setattr(self, bucket_name, amount)
        self._restore_commitments()

    def _restore_commitments(self) -> None:
        records = self.recovered_commitments
        if records is None:
            if self.reserved or self.committed_unknown:
                raise ValueError(
                    "nonzero commitment aggregates require recovered commitments"
                )
            return
        if not isinstance(records, Mapping):
            raise ValueError("recovered commitments must be a mapping")

        totals = {"reserved": Decimal("0"), "unknown": Decimal("0")}
        for request_id, record in records.items():
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("recovered request ID must be non-empty")
            if request_id in self._commitments:
                raise ValueError("recovered request ID must be unique")
            if not isinstance(record, Mapping):
                raise ValueError("recovered commitment must be a mapping")
            amount = _money(record.get("amount"))
            if amount is None:
                raise ValueError(
                    "recovered commitment amount must be finite and non-negative"
                )
            state = record.get("state")
            if state not in {"reserved", "unknown"}:
                raise ValueError(
                    "recovered commitment state must be reserved or unknown"
                )
            self._commitments[request_id] = _Commitment(amount, state)
            totals[state] += amount

        if (
            totals["reserved"] != self.reserved
            or totals["unknown"] != self.committed_unknown
        ):
            raise ValueError("recovered commitment aggregate does not match records")

    def _matches_currency(self, currency: str) -> bool:
        return (
            self.limit is not None
            and self.currency in SUPPORTED_CURRENCIES
            and isinstance(currency, str)
            and currency.upper() == self.currency
        )

    def can_reserve(self, next_worst_case: Any, currency: str) -> bool:
        """Return whether every current and prospective commitment fits."""
        next_cost = _money(next_worst_case)
        buckets = tuple(_money(value) for value in (
            self.spent,
            self.reserved,
            self.committed_unknown,
        ))
        if (
            not self._matches_currency(currency)
            or next_cost is None
            or any(value is None for value in buckets)
        ):
            return False
        assert self.limit is not None
        return sum(buckets, next_cost) <= self.limit

    def reserve(self, request_id: str, worst_case: Any, currency: str) -> bool:
        """Reserve a unique request if the fail-closed budget gate permits it."""
        if not request_id or request_id in self._commitments:
            return False
        amount = _money(worst_case)
        if amount is None or not self.can_reserve(amount, currency):
            return False
        self._commitments[request_id] = _Commitment(amount)
        self.reserved += amount
        return True

    def mark_unknown(self, request_id: str) -> None:
        """Move an accepted-but-unknown request into durable commitment."""
        commitment = self._require(request_id, "reserved")
        self.reserved -= commitment.amount
        self.committed_unknown += commitment.amount
        commitment.state = "unknown"

    def abandon(self, request_id: str) -> None:
        """Record no release: abandonment cannot erase a provider commitment."""
        self._require(request_id, "reserved", "unknown")

    def settle(self, request_id: str, actual_cost: Any, currency: str) -> None:
        """Replace a reservation or unknown commitment with actual spend."""
        if not self._matches_currency(currency):
            raise ValueError("settlement currency does not match ledger currency")
        actual = _money(actual_cost)
        if actual is None:
            raise ValueError("actual cost must be a finite non-negative number")
        commitment = self._require(request_id, "reserved", "unknown")
        if actual > commitment.amount:
            raise ValueError("actual cost exceeds the request worst-case commitment")
        if commitment.state == "reserved":
            self.reserved -= commitment.amount
        else:
            self.committed_unknown -= commitment.amount
        self.spent += actual
        commitment.state = "settled"

    @property
    def available(self) -> Decimal:
        """Return uncommitted budget, or zero when configuration is invalid."""
        if self.limit is None:
            return Decimal("0")
        return self.limit - self.spent - self.reserved - self.committed_unknown

    def _require(self, request_id: str, *states: str) -> _Commitment:
        commitment = self._commitments.get(request_id)
        if commitment is None or commitment.state not in states:
            raise ValueError("request has no matching active commitment")
        return commitment


_RECOVERY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{1,256}$")
_RECOVERY_STATES = frozenset({"reserved", "unknown", "abandoned_pending"})
_PROVIDER_MODELS = {
    "aliyun": FUNASR_MODEL,
    "groq": GROQ_MODEL,
}


class RecoveryStore:
    """Private, sanitized persistence for active benchmark commitments."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _safe_id(value: Any, *, required: bool = True) -> str | None:
        if value is None and not required:
            return None
        if not isinstance(value, str) or _RECOVERY_ID_PATTERN.fullmatch(value) is None:
            raise PreflightError("recovery record is invalid")
        return value

    @classmethod
    def _sanitize_attempt(cls, attempt: Mapping[str, Any]) -> dict[str, str]:
        provider = attempt.get("provider")
        currency = attempt.get("currency")
        state = attempt.get("state")
        amount = _money(attempt.get("amount"))
        if (
            provider not in _PROVIDER_MODELS
            or attempt.get("model") != _PROVIDER_MODELS[provider]
            or currency != ("CNY" if provider == "aliyun" else "USD")
            or state not in _RECOVERY_STATES
            or amount is None
            or not isinstance(attempt.get("sample_sha256"), str)
            or _SHA256_PATTERN.fullmatch(attempt["sample_sha256"]) is None
        ):
            raise PreflightError("recovery record is invalid")
        sanitized = {
            "attempt_id": cls._safe_id(attempt.get("attempt_id")),
            "action_id": cls._safe_id(attempt.get("action_id")),
            "sample_sha256": attempt["sample_sha256"].casefold(),
            "provider": provider,
            "model": attempt["model"],
            "state": state,
            "amount": str(amount),
            "currency": currency,
        }
        sample_id = attempt.get("sample_id")
        if sample_id is not None:
            if sample_id not in REQUIRED_SAMPLE_IDS:
                raise PreflightError("recovery record is invalid")
            sanitized["sample_id"] = sample_id
        for field_name in ("task_id", "request_id"):
            value = cls._safe_id(attempt.get(field_name), required=False)
            if value is not None:
                sanitized[field_name] = value
        return sanitized

    @staticmethod
    def _money_map(
        values: Mapping[str, Any],
        *,
        positive: bool,
    ) -> dict[str, str]:
        if not isinstance(values, Mapping):
            raise PreflightError("recovery record is invalid")
        result: dict[str, str] = {}
        for currency in ("CNY", "USD"):
            amount = _money(values.get(currency))
            if amount is None or (positive and amount <= 0):
                raise PreflightError("recovery record is invalid")
            result[currency] = str(amount)
        return result

    @staticmethod
    def _price_snapshot(values: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(values, Mapping):
            raise PreflightError("recovery record is invalid")
        result = {}
        for field_name in ("funasr_cny_per_second", "groq_usd_per_hour"):
            amount = _money(values.get(field_name))
            if amount is None or amount <= 0:
                raise PreflightError("recovery record is invalid")
            result[field_name] = str(amount)
        return result

    def write_snapshot(
        self,
        *,
        budgets: Mapping[str, Any],
        price_snapshot: Mapping[str, Any],
        spent: Mapping[str, Any],
        attempts: Iterable[Mapping[str, Any]],
    ) -> None:
        sanitized_attempts = [self._sanitize_attempt(attempt) for attempt in attempts]
        if len({item["action_id"] for item in sanitized_attempts}) != len(
            sanitized_attempts
        ):
            raise PreflightError("recovery record is invalid")
        payload = {
            "schema_version": 1,
            "budgets": self._money_map(budgets, positive=True),
            "price_snapshot": self._price_snapshot(price_snapshot),
            "spent": self._money_map(spent, positive=False),
            "attempts": sanitized_attempts,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=True, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            raise PreflightError("recovery record is invalid") from None
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("attempts"), list)
        ):
            raise PreflightError("recovery record is invalid")
        attempts = [self._sanitize_attempt(item) for item in payload["attempts"]]
        if len({item["action_id"] for item in attempts}) != len(attempts):
            raise PreflightError("recovery record is invalid")
        return {
            "schema_version": 1,
            "budgets": self._money_map(payload.get("budgets"), positive=True),
            "price_snapshot": self._price_snapshot(payload.get("price_snapshot")),
            "spent": self._money_map(payload.get("spent"), positive=False),
            "attempts": attempts,
        }

    def load_ledgers(self) -> dict[str, BudgetLedger]:
        snapshot = self.load()
        ledgers = {}
        for currency in ("CNY", "USD"):
            matching = [
                attempt
                for attempt in snapshot["attempts"]
                if attempt["currency"] == currency
            ]
            recovered = {
                attempt["action_id"]: {
                    "amount": attempt["amount"],
                    "state": "reserved"
                    if attempt["state"] == "reserved"
                    else "unknown",
                }
                for attempt in matching
            }
            reserved = sum(
                (
                    Decimal(attempt["amount"])
                    for attempt in matching
                    if attempt["state"] == "reserved"
                ),
                Decimal("0"),
            )
            unknown = sum(
                (
                    Decimal(attempt["amount"])
                    for attempt in matching
                    if attempt["state"] != "reserved"
                ),
                Decimal("0"),
            )
            ledgers[currency] = BudgetLedger(
                limit=snapshot["budgets"][currency],
                currency=currency,
                spent=snapshot["spent"][currency],
                reserved=reserved,
                committed_unknown=unknown,
                recovered_commitments=recovered,
            )
        return ledgers

    def has_active_attempts(self) -> bool:
        """Return whether a valid recovery snapshot has active commitments."""
        return self.path.exists() and bool(self.load()["attempts"])

    def upsert_attempt(
        self,
        *,
        budgets: Mapping[str, Any],
        price_snapshot: Mapping[str, Any],
        spent: Mapping[str, Any],
        attempt: Mapping[str, Any],
    ) -> None:
        """Atomically merge one active attempt without dropping its peers."""
        sanitized_budgets = self._money_map(budgets, positive=True)
        sanitized_prices = self._price_snapshot(price_snapshot)
        sanitized_spent = self._money_map(spent, positive=False)
        sanitized_attempt = self._sanitize_attempt(attempt)
        attempts: list[Mapping[str, Any]] = []
        if self.path.exists():
            snapshot = self.load()
            if (
                snapshot["budgets"] != sanitized_budgets
                or snapshot["price_snapshot"] != sanitized_prices
            ):
                raise PreflightError("recovery record is incompatible")
            sanitized_spent = {
                currency: str(
                    max(
                        Decimal(snapshot["spent"][currency]),
                        Decimal(sanitized_spent[currency]),
                    )
                )
                for currency in ("CNY", "USD")
            }
            attempts = [
                item
                for item in snapshot["attempts"]
                if item["action_id"] != sanitized_attempt["action_id"]
            ]
        attempts.append(sanitized_attempt)
        self.write_snapshot(
            budgets=sanitized_budgets,
            price_snapshot=sanitized_prices,
            spent=sanitized_spent,
            attempts=attempts,
        )

    def mark_unknown(self, action_id: str) -> None:
        """Persist one active attempt as unknown while preserving provider IDs."""
        snapshot = self.load()
        matching = [
            attempt
            for attempt in snapshot["attempts"]
            if attempt["action_id"] == action_id
        ]
        if len(matching) != 1:
            raise PreflightError("recovery record is invalid")
        matching[0]["state"] = "unknown"
        self.write_snapshot(
            budgets=snapshot["budgets"],
            price_snapshot=snapshot["price_snapshot"],
            spent=snapshot["spent"],
            attempts=snapshot["attempts"],
        )

    def abandon(self, action_id: str) -> None:
        snapshot = self.load()
        matching = [
            attempt
            for attempt in snapshot["attempts"]
            if attempt["action_id"] == action_id
        ]
        if len(matching) != 1:
            raise PreflightError("recovery record is invalid")
        matching[0]["state"] = "abandoned_pending"
        self.write_snapshot(
            budgets=snapshot["budgets"],
            price_snapshot=snapshot["price_snapshot"],
            spent=snapshot["spent"],
            attempts=snapshot["attempts"],
        )

    def settle_terminal(self, action_id: str, actual_cost: Any, currency: str) -> None:
        snapshot = self.load()
        matching = [
            attempt
            for attempt in snapshot["attempts"]
            if attempt["action_id"] == action_id
        ]
        actual = _money(actual_cost)
        if (
            len(matching) != 1
            or currency not in {"CNY", "USD"}
            or matching[0]["currency"] != currency
            or actual is None
            or actual > Decimal(matching[0]["amount"])
        ):
            raise PreflightError("recovery settlement is invalid")
        snapshot["spent"][currency] = str(
            Decimal(snapshot["spent"][currency]) + actual
        )
        remaining = [
            attempt
            for attempt in snapshot["attempts"]
            if attempt["action_id"] != action_id
        ]
        if not remaining:
            self.path.unlink()
            return
        self.write_snapshot(
            budgets=snapshot["budgets"],
            price_snapshot=snapshot["price_snapshot"],
            spent=snapshot["spent"],
            attempts=remaining,
        )


def read_remote_credentials_from_environment() -> dict[str, dict[str, str]]:
    """Read the fixed benchmark credentials from the process environment."""
    names = (
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_WORKSPACE_ID",
        "DASHSCOPE_API_HOST",
        "GROQ_API_KEY",
    )
    values = {name: os.environ.get(name) for name in names}
    if any(
        not isinstance(value, str) or not value.strip()
        for value in values.values()
    ):
        raise PreflightError("remote credentials are invalid")
    aliyun_host = _validated_aliyun_api_host(
        values["DASHSCOPE_WORKSPACE_ID"],
        values["DASHSCOPE_API_HOST"],
    )
    return {
        "aliyun": {
            "api_key": values["DASHSCOPE_API_KEY"],
            "workspace_id": values["DASHSCOPE_WORKSPACE_ID"],
            "api_host": aliyun_host,
        },
        "groq": {"api_key": values["GROQ_API_KEY"]},
    }


def _atomic_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=True, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


class BenchmarkSmokeExecutor:
    """Execute locally verified main-variant samples through injected clients."""

    def __init__(
        self,
        *,
        manifest: Mapping[str, Any],
        samples_dir: str | Path,
        recovery_store: RecoveryStore,
        results_path: str | Path,
        budgets: Mapping[str, Any],
        client_factory: Callable[[str, Mapping[str, str]], Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        _status, samples = _validated_manifest_samples(manifest)
        parsed_budgets = {
            currency: _money(budgets.get(currency)) for currency in ("CNY", "USD")
        }
        self._samples = samples
        self._samples_dir = Path(samples_dir)
        self._recovery_store = recovery_store
        self._results_path = Path(results_path)
        self._budgets = {
            currency: str(parsed_budgets[currency] or Decimal("0"))
            for currency in ("CNY", "USD")
        }
        self._client_factory = client_factory
        self._clock = clock
        self._verified_paths: dict[str, Path] = {}
        self._spent = {"CNY": Decimal("0"), "USD": Decimal("0")}
        self._pending_results: dict[str, dict[str, Any]] = {}

    def preflight(self, actions: Iterable[BenchmarkAction]) -> None:
        """Verify all selected local media before credentials can be read."""
        selected_actions = tuple(actions)
        if not selected_actions:
            raise PreflightError("smoke action is not implemented")
        verified: dict[str, Path] = {}
        for action in selected_actions:
            if (
                action.variant != "main"
                or action.sample_id not in SHORT_SAMPLE_IDS
                + (MULTI_SPEAKER_SAMPLE_ID,)
                or action.action_index != 1
            ):
                raise PreflightError("smoke action is not implemented")
            if action.sample_id in verified:
                continue
            sample, _duration = self._samples[action.sample_id]
            path = self._samples_dir / f"{action.sample_id}.flac"
            try:
                stat = path.stat()
            except OSError:
                raise PreflightError("smoke audio is invalid") from None
            if (
                path.is_symlink()
                or not path.is_file()
                or stat.st_size != sample["size_bytes"]
            ):
                raise PreflightError("smoke audio is invalid")
            digest = hashlib.sha256()
            try:
                with path.open("rb") as audio_file:
                    for block in iter(lambda: audio_file.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError:
                raise PreflightError("smoke audio is invalid") from None
            if not hmac.compare_digest(
                digest.hexdigest(),
                sample["sha256"].casefold(),
            ):
                raise PreflightError("smoke audio is invalid")
            verified[action.sample_id] = path
        self._verified_paths = verified

    def _write_recovery(
        self,
        action: BenchmarkAction,
        *,
        task_id: str | None = None,
    ) -> None:
        sample, _duration = self._samples[action.sample_id]
        attempt = {
            "attempt_id": action.attempt_id,
            "action_id": action.action_id,
            "sample_id": action.sample_id,
            "sample_sha256": sample["sha256"],
            "provider": action.provider,
            "model": _PROVIDER_MODELS[action.provider],
            "state": "reserved",
            "amount": str(action.worst_case_cost),
            "currency": action.currency,
        }
        if task_id is not None:
            attempt["task_id"] = task_id
        self._recovery_store.upsert_attempt(
            budgets=self._budgets,
            price_snapshot={
                "funasr_cny_per_second": str(FUNASR_CNY_PER_SECOND),
                "groq_usd_per_hour": str(GROQ_USD_PER_HOUR),
            },
            spent={currency: str(amount) for currency, amount in self._spent.items()},
            attempt=attempt,
        )

    def has_pending_recovery(self) -> bool:
        """Return whether a normal paid run must stop for active recovery."""
        return self._recovery_store.has_active_attempts()

    def mark_unknown(self, action: BenchmarkAction) -> None:
        """Persist the action as unknown after an indeterminate provider call."""
        self._recovery_store.mark_unknown(action.action_id)

    def _make_client(self, provider: str, credentials: Mapping[str, str]) -> Any:
        if self._client_factory is not None:
            return self._client_factory(provider, credentials)
        if provider == "aliyun":
            return AliyunASRClient(
                credentials["api_key"],
                credentials["workspace_id"],
                api_host=credentials["api_host"],
            )
        if provider == "groq":
            return GroqASRClient(credentials["api_key"])
        raise PreflightError("smoke provider is not implemented")

    @staticmethod
    def _aliyun_result(provider_result: Mapping[str, Any]) -> tuple[str, list[Any]]:
        text_parts: list[str] = []
        timestamps: list[Any] = []
        results = provider_result.get("results")
        if isinstance(results, Sequence) and not isinstance(results, (str, bytes)):
            for item in results:
                transcript = (
                    item.get("transcript") if isinstance(item, Mapping) else None
                )
                if not isinstance(transcript, Mapping):
                    continue
                text = transcript.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
                sentences = transcript.get("sentences")
                if isinstance(sentences, list):
                    timestamps.extend(sentences)
        return "\n".join(text_parts), timestamps

    def _set_pending_result(
        self,
        action: BenchmarkAction,
        *,
        provider_id: str,
        text: str,
        timestamps: Any,
        usage_seconds: Decimal,
        actual_cost: Decimal,
    ) -> dict[str, Any]:
        completed_at = self._clock()
        if not _valid_nonnegative_number(completed_at):
            raise PreflightError("benchmark clock is invalid")
        if action.provider == "aliyun":
            sentences = timestamps if isinstance(timestamps, list) else []
            timeline_items = sentences
            timestamp_summary = {"sentence_count": len(sentences)}
        else:
            segments = (
                timestamps.get("segments", [])
                if isinstance(timestamps, Mapping)
                else []
            )
            words = (
                timestamps.get("words", [])
                if isinstance(timestamps, Mapping)
                else []
            )
            segments = segments if isinstance(segments, list) else []
            words = words if isinstance(words, list) else []
            timeline_items = segments or words
            timestamp_summary = {
                "segment_count": len(segments),
                "word_count": len(words),
            }
        starts = [
            item.get("start_time", item.get("start"))
            for item in timeline_items
            if isinstance(item, Mapping)
            and _valid_nonnegative_number(item.get("start_time", item.get("start")))
        ]
        ends = [
            item.get("end_time", item.get("end"))
            for item in timeline_items
            if isinstance(item, Mapping)
            and _valid_nonnegative_number(item.get("end_time", item.get("end")))
        ]
        if starts:
            timestamp_summary["first_start_seconds"] = _json_safe_number(starts[0])
        if ends:
            timestamp_summary["last_end_seconds"] = _json_safe_number(ends[-1])
        self._pending_results[action.action_id] = {
            "action_id": action.action_id,
            "completed_at": _json_safe_number(completed_at),
            "cost": {"amount": str(actual_cost), "currency": action.currency},
            "model": _PROVIDER_MODELS[action.provider],
            "provider": action.provider,
            "provider_id_sha256": hashlib.sha256(
                provider_id.encode("utf-8")
            ).hexdigest(),
            "sample_id": action.sample_id,
            "text_chars": len(text),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "timestamp_summary": timestamp_summary,
            "usage": {"seconds": str(usage_seconds)},
        }
        return {"actual_cost": actual_cost}

    def __call__(
        self,
        action: BenchmarkAction,
        credentials: Any,
        ledger: BudgetLedger,
    ) -> dict[str, Any]:
        path = self._verified_paths.get(action.sample_id)
        if path is None or not isinstance(credentials, Mapping):
            raise PreflightError("smoke executor was not preflighted")
        provider_credentials = credentials.get(action.provider)
        if not isinstance(provider_credentials, Mapping):
            raise PreflightError("remote credentials are invalid")
        self._spent[action.currency] = ledger.spent
        self._write_recovery(action)
        client = self._make_client(action.provider, provider_credentials)
        sample, _duration = self._samples[action.sample_id]
        language = sample["language"]

        with path.open("rb") as audio_file:
            if action.provider == "aliyun":
                staged_uri = client.upload_audio(
                    audio_file,
                    path.name,
                    content_type="audio/flac",
                )
                submitted = client.submit(staged_uri, [language])
                task_id = (
                    submitted.get("task_id")
                    if isinstance(submitted, Mapping)
                    else None
                )
                if not isinstance(task_id, str) or not task_id:
                    raise RemoteASRError("invalid_response")
                self._write_recovery(action, task_id=task_id)
                provider_result = client.poll(task_id)
            else:
                provider_result = client.transcribe(
                    audio_file,
                    path.name,
                    language,
                    content_type="audio/flac",
                )

        if not isinstance(provider_result, Mapping):
            raise RemoteASRError("invalid_response")
        if action.provider == "aliyun":
            if provider_result.get("status") != "SUCCEEDED":
                raise RemoteASRError("provider_failed")
            usage_seconds = _decimal_duration(provider_result.get("usage_seconds"))
            actual_cost = funasr_terminal_cost_cny(usage_seconds)
            text, timestamps = self._aliyun_result(provider_result)
            provider_id = provider_result.get("task_id")
        else:
            usage_seconds = action.duration_seconds
            actual_cost = groq_request_cost_usd(usage_seconds)
            text = provider_result.get("text")
            timestamps = {
                "segments": provider_result.get("segments", []),
                "words": provider_result.get("words", []),
            }
            provider_id = provider_result.get("request_id")
        if (
            not isinstance(text, str)
            or not isinstance(provider_id, str)
            or not provider_id
        ):
            raise RemoteASRError("invalid_response")
        return self._set_pending_result(
            action,
            provider_id=provider_id,
            text=text,
            timestamps=timestamps,
            usage_seconds=usage_seconds,
            actual_cost=actual_cost,
        )

    def resume_pending_aliyun(
        self,
        credential_reader: Callable[[], Any],
    ) -> dict[str, Any]:
        """Resume exactly one persisted Aliyun task by polling its task ID."""
        try:
            snapshot = self._recovery_store.load()
        except Exception:
            return {
                "mode": "resume_task",
                "status": "blocked",
                "blocked_reasons": ["invalid_recovery"],
            }
        attempts = snapshot["attempts"]
        if len(attempts) != 1:
            return {
                "mode": "resume_task",
                "status": "blocked",
                "blocked_reasons": ["pending_recovery"],
            }
        attempt = attempts[0]
        if attempt["provider"] == "groq":
            return {
                "mode": "resume_task",
                "status": "blocked",
                "blocked_reasons": ["groq_resume_not_supported"],
            }
        sample_id = attempt.get("sample_id")
        task_id = attempt.get("task_id")
        if (
            attempt["provider"] != "aliyun"
            or attempt["state"] != "unknown"
            or not isinstance(task_id, str)
            or sample_id not in self._samples
            or not hmac.compare_digest(
                attempt["sample_sha256"],
                self._samples[sample_id][0]["sha256"].casefold(),
            )
        ):
            return {
                "mode": "resume_task",
                "status": "blocked",
                "blocked_reasons": ["invalid_recovery"],
            }
        try:
            credentials = credential_reader()
            provider_credentials = credentials.get("aliyun")
            if not isinstance(provider_credentials, Mapping):
                raise PreflightError("remote credentials are invalid")
            client = self._make_client("aliyun", provider_credentials)
        except Exception:
            return {
                "mode": "resume_task",
                "status": "blocked",
                "blocked_reasons": ["credential_error"],
            }
        duration = self._samples[sample_id][1]
        action = BenchmarkAction(
            attempt_id=attempt["attempt_id"],
            action_id=attempt["action_id"],
            provider="aliyun",
            sample_id=sample_id,
            variant="main",
            repeat_index=1,
            action_index=1,
            duration_seconds=duration,
            currency="CNY",
            worst_case_cost=Decimal(attempt["amount"]),
        )
        try:
            provider_result = client.poll(task_id)
            if (
                not isinstance(provider_result, Mapping)
                or provider_result.get("status") != "SUCCEEDED"
            ):
                raise PollTimeoutError("poll_not_terminal")
            usage_seconds = _decimal_duration(provider_result.get("usage_seconds"))
            actual_cost = funasr_terminal_cost_cny(usage_seconds)
            text, timestamps = self._aliyun_result(provider_result)
            terminal_task_id = provider_result.get("task_id")
            if (
                not isinstance(text, str)
                or not isinstance(terminal_task_id, str)
                or not hmac.compare_digest(task_id, terminal_task_id)
            ):
                raise RemoteASRError("invalid_response")
            execution_result = self._set_pending_result(
                action,
                provider_id=terminal_task_id,
                text=text,
                timestamps=timestamps,
                usage_seconds=usage_seconds,
                actual_cost=actual_cost,
            )
            self._spent = {
                currency: Decimal(snapshot["spent"][currency])
                for currency in ("CNY", "USD")
            }
            self.finalize(action, execution_result)
        except Exception:
            try:
                self._recovery_store.mark_unknown(action.action_id)
            except Exception:
                pass
            return {
                "mode": "resume_task",
                "status": "unknown",
                "blocked_reasons": ["poll_not_terminal"],
            }
        return {
            "mode": "resume_task",
            "status": "completed",
            "blocked_reasons": [],
            "provider": "aliyun",
            "sample_id": sample_id,
            "action_id": action.action_id,
            "actual_cost": str(actual_cost),
            "currency": "CNY",
        }

    def finalize(
        self,
        action: BenchmarkAction,
        execution_result: Mapping[str, Any],
    ) -> None:
        """Atomically persist a safe result before terminal recovery settlement."""
        del execution_result
        record = self._pending_results.get(action.action_id)
        if record is None:
            raise PreflightError("smoke result is missing")
        if self._results_path.exists():
            try:
                payload = json.loads(self._results_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                raise PreflightError("benchmark results are invalid") from None
            if (
                not isinstance(payload, Mapping)
                or payload.get("schema_version") != 1
                or not isinstance(payload.get("results"), list)
            ):
                raise PreflightError("benchmark results are invalid")
            results = [
                item
                for item in payload["results"]
                if isinstance(item, Mapping)
                and item.get("action_id") != action.action_id
            ]
        else:
            results = []
        results.append(record)
        _atomic_private_json(
            self._results_path,
            {"schema_version": 1, "results": results},
        )
        actual_cost = record["cost"]["amount"]
        self._recovery_store.settle_terminal(
            action.action_id,
            actual_cost,
            action.currency,
        )
        self._spent[action.currency] += Decimal(actual_cost)
        del self._pending_results[action.action_id]


def cleanup_run_artifacts(
    run_dir: str | Path,
    *,
    recovery_path: str | Path,
) -> None:
    """Remove one exact benchmark run directory while preserving recovery."""
    run_path = Path(run_dir)
    recovery = Path(recovery_path)
    resolved_run = run_path.resolve()
    resolved_recovery = recovery.resolve()
    if (
        run_path.name == ""
        or not run_path.name.startswith("run-")
        or run_path.parent.name != "remote_asr_benchmark"
        or resolved_run.parent != resolved_recovery.parent
        or resolved_recovery == resolved_run
        or resolved_run in resolved_recovery.parents
        or run_path.is_symlink()
    ):
        raise PreflightError("run directory is not safely scoped")
    if run_path.exists():
        if not run_path.is_dir():
            raise PreflightError("run directory is not safely scoped")
        shutil.rmtree(run_path)


def _budget_totals(actions: Iterable[BenchmarkAction]) -> dict[str, Decimal]:
    totals = {"CNY": Decimal("0"), "USD": Decimal("0")}
    for action in actions:
        totals[action.currency] += action.worst_case_cost
    return totals


def _ledger_summary(ledgers: Mapping[str, BudgetLedger]) -> dict[str, Any]:
    return {
        currency: {
            "spent": str(ledger.spent),
            "reserved": str(ledger.reserved),
            "committed_unknown": str(ledger.committed_unknown),
        }
        for currency, ledger in ledgers.items()
    }


def run_action_matrix(
    *,
    manifest: Mapping[str, Any],
    execute_paid: bool = False,
    max_cny: Any = None,
    max_usd: Any = None,
    providers: Iterable[str] | str | None = None,
    sample_ids: Iterable[str] | str | None = None,
    repeats: int = 3,
    variants: Iterable[str] | str | None = None,
    retry_unknown: bool = False,
    credential_reader: Callable[[], Any] | None = None,
    external_executor: (
        Callable[[BenchmarkAction, Any, BudgetLedger], Any] | None
    ) = None,
) -> dict[str, Any]:
    """Preflight and optionally execute a paid matrix through injected hooks."""
    del retry_unknown  # Recovery-aware explicit retries belong to the next block.
    try:
        manifest_status, _samples = _validated_manifest_samples(manifest)
        actions = build_action_matrix(
            manifest,
            providers=providers,
            sample_ids=sample_ids,
            repeats=repeats,
            variants=variants,
        )
    except MatrixValidationError as error:
        return {
            "mode": "execute_paid" if execute_paid else "dry_run",
            "status": "blocked",
            "blocked_reasons": [error.code],
            "action_count": 0,
            "required_budget": {"CNY": None, "USD": None},
            "actions": [],
        }

    totals = _budget_totals(actions)
    ledgers = {
        "CNY": BudgetLedger(limit=max_cny, currency="CNY"),
        "USD": BudgetLedger(limit=max_usd, currency="USD"),
    }
    reasons: list[str] = []
    if not execute_paid:
        reasons.append("execute_paid_required")
    if manifest_status != "confirmed":
        reasons.append("manifest_not_confirmed")
    for currency in ("CNY", "USD"):
        ledger = ledgers[currency]
        if ledger.limit is None:
            reasons.append(f"invalid_{currency.casefold()}_budget")
        elif totals[currency] > ledger.limit:
            reasons.append(f"{currency.casefold()}_budget_exceeded")
    if not callable(credential_reader) or not callable(external_executor):
        if execute_paid:
            reasons.append("runner_not_configured")

    summary: dict[str, Any] = {
        "mode": "execute_paid" if execute_paid else "dry_run",
        "status": "blocked" if reasons else "ready",
        "blocked_reasons": reasons,
        "action_count": len(actions),
        "required_budget": {
            currency: str(totals[currency]) for currency in ("CNY", "USD")
        },
        "actions": [],
    }
    if reasons:
        return summary

    pending_recovery = getattr(external_executor, "has_pending_recovery", None)
    if callable(pending_recovery):
        try:
            has_pending_recovery = pending_recovery()
        except Exception:
            has_pending_recovery = True
        if has_pending_recovery:
            summary["status"] = "blocked"
            summary["blocked_reasons"] = ["pending_recovery"]
            return summary

    preflight = getattr(external_executor, "preflight", None)
    if callable(preflight):
        try:
            preflight(actions)
        except Exception:
            summary["status"] = "blocked"
            summary["blocked_reasons"] = ["local_preflight_failed"]
            return summary

    assert credential_reader is not None
    assert external_executor is not None
    try:
        credentials = credential_reader()
    except Exception:
        summary["status"] = "blocked"
        summary["blocked_reasons"] = ["credential_error"]
        return summary

    def mark_unknown(
        action: BenchmarkAction,
        ledger: BudgetLedger,
    ) -> bool:
        persisted = True
        persistent_hook = getattr(external_executor, "mark_unknown", None)
        if callable(persistent_hook):
            try:
                persistent_hook(action)
            except Exception:
                persisted = False
        ledger.mark_unknown(action.action_id)
        return persisted

    for action in actions:
        ledger = ledgers[action.currency]
        if not ledger.reserve(
            action.action_id,
            action.worst_case_cost,
            action.currency,
        ):
            summary["status"] = "blocked"
            summary["blocked_reasons"] = ["budget_reservation_failed"]
            break
        action_summary = {
            "attempt_id": action.attempt_id,
            "action_id": action.action_id,
            "provider": action.provider,
            "sample_id": action.sample_id,
            "status": "started",
            "currency": action.currency,
            "reserved_cost": str(action.worst_case_cost),
        }
        summary["actions"].append(action_summary)
        try:
            execution_result = external_executor(action, credentials, ledger)
        except PotentiallyAcceptedError:
            persisted = mark_unknown(action, ledger)
            action_summary["status"] = "unknown"
            summary["status"] = "unknown"
            summary["blocked_reasons"] = [
                "potentially_accepted" if persisted else "recovery_update_failed"
            ]
            break
        except PollTimeoutError:
            persisted = mark_unknown(action, ledger)
            action_summary["status"] = "unknown"
            summary["status"] = "unknown"
            summary["blocked_reasons"] = [
                "poll_timeout" if persisted else "recovery_update_failed"
            ]
            break
        except Exception:
            persisted = mark_unknown(action, ledger)
            action_summary["status"] = "unknown"
            summary["status"] = "unknown"
            summary["blocked_reasons"] = [
                "executor_error" if persisted else "recovery_update_failed"
            ]
            break
        actual_cost = (
            _money(execution_result.get("actual_cost"))
            if isinstance(execution_result, Mapping)
            else None
        )
        if actual_cost is None:
            mark_unknown(action, ledger)
            action_summary["status"] = "unknown"
            summary["status"] = "unknown"
            summary["blocked_reasons"] = ["invalid_actual_cost"]
            break
        finalize = getattr(external_executor, "finalize", None)
        if callable(finalize):
            try:
                finalize(action, execution_result)
            except Exception:
                mark_unknown(action, ledger)
                action_summary["status"] = "unknown"
                summary["status"] = "unknown"
                summary["blocked_reasons"] = ["finalize_error"]
                break
        try:
            ledger.settle(action.action_id, actual_cost, action.currency)
        except ValueError:
            mark_unknown(action, ledger)
            action_summary["status"] = "unknown"
            summary["status"] = "unknown"
            summary["blocked_reasons"] = ["invalid_actual_cost"]
            break
        action_summary["status"] = "completed"
        action_summary["actual_cost"] = str(actual_cost)
    else:
        summary["status"] = "completed"

    summary["budget_state"] = _ledger_summary(ledgers)
    return summary


class BenchmarkState(str, Enum):
    DISCOVERED = "DISCOVERED"
    AUDIO_READY = "AUDIO_READY"
    STAGED = "STAGED"
    ASR_STARTED = "ASR_STARTED"
    TERMINAL = "TERMINAL"


class InvalidTransition(ValueError):
    """Raised when a benchmark run skips or reverses a state."""


class PreflightError(ValueError):
    """Raised before any external hook when local prerequisites are invalid."""


_NEXT_STATE = {
    BenchmarkState.DISCOVERED: BenchmarkState.AUDIO_READY,
    BenchmarkState.AUDIO_READY: BenchmarkState.STAGED,
    BenchmarkState.STAGED: BenchmarkState.ASR_STARTED,
    BenchmarkState.ASR_STARTED: BenchmarkState.TERMINAL,
}


@dataclass
class BenchmarkStateMachine:
    state: BenchmarkState = BenchmarkState.DISCOVERED

    def transition(self, target: BenchmarkState) -> None:
        """Advance exactly one step through the declared state path."""
        try:
            normalized_target = BenchmarkState(target)
        except ValueError:
            raise InvalidTransition(f"unknown target state: {target}") from None
        if _NEXT_STATE.get(self.state) is not normalized_target:
            raise InvalidTransition(
                f"cannot transition from {self.state.value} to {normalized_target.value}"
            )
        self.state = normalized_target


@dataclass(frozen=True)
class AudioMetadata:
    locator: str
    duration_seconds: Any
    sha256: str


def _validate_preflight(
    machine: BenchmarkStateMachine,
    audio: AudioMetadata | None,
    expected_sha256: str,
) -> None:
    if machine.state is not BenchmarkState.DISCOVERED:
        raise PreflightError("run must be DISCOVERED before preflight")
    if audio is None or not isinstance(audio.locator, str) or not audio.locator.strip():
        raise PreflightError("audio is required")
    try:
        duration = _decimal_duration(audio.duration_seconds)
    except ValueError:
        raise PreflightError("audio duration is required") from None
    if duration <= 0:
        raise PreflightError("audio duration must be positive")
    if (
        not isinstance(audio.sha256, str)
        or not isinstance(expected_sha256, str)
        or _SHA256_PATTERN.fullmatch(audio.sha256) is None
        or _SHA256_PATTERN.fullmatch(expected_sha256) is None
    ):
        raise PreflightError("audio hash is required")
    actual_hash = audio.sha256.casefold()
    expected_hash = expected_sha256.casefold()
    if not hmac.compare_digest(
        actual_hash,
        expected_hash,
    ):
        raise PreflightError("audio hash does not match")


def guarded_start_asr(
    machine: BenchmarkStateMachine,
    audio: AudioMetadata | None,
    expected_sha256: str,
    read_credentials: Callable[[], Any],
    upload: Callable[[AudioMetadata, Any], Any],
    provider_start: Callable[[Any, Any], Any],
) -> Any:
    """Run injected hooks only after all local prerequisites pass."""
    _validate_preflight(machine, audio, expected_sha256)
    assert audio is not None
    machine.transition(BenchmarkState.AUDIO_READY)
    machine.transition(BenchmarkState.STAGED)
    credentials = read_credentials()
    upload_result = upload(audio, credentials)
    machine.transition(BenchmarkState.ASR_STARTED)
    provider_result = provider_start(upload_result, credentials)
    return provider_result


_PROVIDER_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$", re.IGNORECASE)
_STATES = frozenset(state.value for state in BenchmarkState)


def _valid_nonnegative_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, Decimal):
        return value.is_finite() and value >= 0
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return math.isfinite(value) and value >= 0
    return False


def _json_safe_number(value: int | float | Decimal) -> int | float | str:
    return str(value) if isinstance(value, Decimal) else value


def sanitize_result(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a safe summary from explicit scalar fields; ignore everything else."""
    result: dict[str, Any] = {}
    provider = record.get("provider")
    if isinstance(provider, str) and _PROVIDER_PATTERN.fullmatch(provider):
        result["provider"] = provider
    state = record.get("state")
    if isinstance(state, str) and state in _STATES:
        result["state"] = state
    for field_name in ("duration_seconds", "usage_seconds"):
        value = record.get(field_name)
        if _valid_nonnegative_number(value):
            result[field_name] = _json_safe_number(value)
    cost = record.get("cost")
    if _money(cost) is not None and isinstance(cost, (str, int, float, Decimal)):
        result["cost"] = _json_safe_number(cost) if not isinstance(cost, str) else cost
    currency = record.get("currency")
    if isinstance(currency, str) and currency in SUPPORTED_CURRENCIES:
        result["currency"] = currency
    status_code = record.get("status_code")
    if (
        isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and 100 <= status_code <= 599
    ):
        result["status_code"] = status_code
    return result


@dataclass(frozen=True)
class TimeRange:
    start: float
    end: float


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


def _valid_time_range(start: Any, end: Any) -> bool:
    return (
        _valid_nonnegative_number(start)
        and _valid_nonnegative_number(end)
        and start <= end
    )


def timestamps_are_monotonic(segments: Iterable[TranscriptSegment]) -> bool:
    """Check finite, well-formed, nondecreasing segment timestamps."""
    previous_start = Decimal("-1")
    previous_end = Decimal("-1")
    for segment in segments:
        if not _valid_time_range(segment.start, segment.end):
            return False
        start = Decimal(str(segment.start))
        end = Decimal(str(segment.end))
        if start < previous_start or end < previous_end:
            return False
        previous_start = start
        previous_end = end
    return True


def find_empty_speech_holes(
    reference_vad: Iterable[TimeRange],
    result_segments: Iterable[TranscriptSegment],
    *,
    minimum_speech_seconds: float = 5,
    context_seconds: float = 5,
) -> list[TimeRange]:
    """Find long reference speech ranges with no result text in nearby context."""
    minimum = _decimal_duration(minimum_speech_seconds)
    context = _decimal_duration(context_seconds)
    segments = [
        segment
        for segment in result_segments
        if isinstance(segment.text, str)
        and segment.text.strip()
        and _valid_time_range(segment.start, segment.end)
    ]
    holes: list[TimeRange] = []
    for speech_range in reference_vad:
        if not _valid_time_range(speech_range.start, speech_range.end):
            continue
        start = Decimal(str(speech_range.start))
        end = Decimal(str(speech_range.end))
        if end - start < minimum:
            continue
        window_start = max(Decimal("0"), start - context)
        window_end = end + context
        has_nearby_text = any(
            Decimal(str(segment.end)) >= window_start
            and Decimal(str(segment.start)) <= window_end
            for segment in segments
        )
        if not has_nearby_text:
            holes.append(speech_range)
    return holes


def last_timestamp_within_limit(
    result_segments: Iterable[TranscriptSegment],
    registered_last_speech_end: Any,
    *,
    tolerance_seconds: float = 5,
) -> bool:
    """Check that the last nonblank result ends close to registered speech."""
    try:
        reference_end = _decimal_duration(registered_last_speech_end)
        tolerance = _decimal_duration(tolerance_seconds)
    except ValueError:
        return False
    valid_segments = [
        segment
        for segment in result_segments
        if isinstance(segment.text, str)
        and segment.text.strip()
        and _valid_time_range(segment.start, segment.end)
    ]
    if not valid_segments:
        return False
    last_end = max(Decimal(str(segment.end)) for segment in valid_segments)
    return abs(last_end - reference_end) <= tolerance
