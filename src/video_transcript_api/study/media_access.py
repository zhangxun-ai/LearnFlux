import base64
import hashlib
import hmac
import json
import time
from typing import Any, Callable


class StudyMediaAccess:
    """Issue and validate short-lived, context-bound media capabilities."""

    def __init__(self, secret: str, clock: Callable[[], float] = time.time):
        if not secret:
            raise ValueError("study media signing secret is required")
        self._key = hashlib.sha256(f"study-media:{secret}".encode("utf-8")).digest()
        self._clock = clock

    def issue_single(
        self,
        *,
        user_id: str,
        view_token: str,
        ttl_seconds: int = 21600,
    ) -> str:
        return self._issue({
            "kind": "single",
            "user_id": user_id,
            "view_token": view_token,
            "exp": int(self._clock()) + int(ttl_seconds),
        })

    def verify_single(self, token: str, *, view_token: str) -> dict[str, Any]:
        payload = self._verify(token)
        if payload.get("kind") != "single" or payload.get("view_token") != view_token:
            raise ValueError("media token context mismatch")
        return payload

    def issue_collection(
        self,
        *,
        user_id: str,
        collection_id: str,
        source_id: str,
        ttl_seconds: int = 21600,
    ) -> str:
        return self._issue({
            "kind": "collection",
            "user_id": user_id,
            "collection_id": collection_id,
            "source_id": source_id,
            "exp": int(self._clock()) + int(ttl_seconds),
        })

    def verify_collection(
        self,
        token: str,
        *,
        collection_id: str,
        source_id: str,
    ) -> dict[str, Any]:
        payload = self._verify(token)
        if (
            payload.get("kind") != "collection"
            or payload.get("collection_id") != collection_id
            or payload.get("source_id") != source_id
        ):
            raise ValueError("media token context mismatch")
        return payload

    def _issue(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body = _encode(raw)
        signature = _encode(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def _verify(self, token: str) -> dict[str, Any]:
        try:
            body, signature = token.split(".", 1)
            expected = _encode(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError("invalid media token signature")
            payload = json.loads(_decode(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid media token") from exc
        if int(payload.get("exp") or 0) < int(self._clock()):
            raise ValueError("media token expired")
        return payload


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
