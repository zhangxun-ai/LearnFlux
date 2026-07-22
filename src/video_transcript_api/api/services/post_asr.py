"""Provider-neutral post-ASR continuation and durable queue dispatch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import uuid4

from ...transcriber.contracts import TranscriptionResult
from ...utils.task_status import TaskStatus


_CONTINUATION_KEYS = (
    "task_id",
    "url",
    "display_url",
    "platform",
    "media_id",
    "video_title",
    "author",
    "description",
    "is_generic",
    "include_comments",
    "comment_limit",
    "preserve_transcript_timestamps",
)
_SIGNED_QUERY_KEYS = {
    "signature",
    "sig",
    "token",
    "access_token",
    "security-token",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-oss-signature",
    "x-oss-credential",
    "x-oss-security-token",
}


def _stop_requested(stop_event: Any | None) -> bool:
    return stop_event is not None and stop_event.is_set()


def _sanitize_continuation_url(value: str) -> str:
    parsed = urlsplit(value)
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
    if query_keys & _SIGNED_QUERY_KEYS:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
    )


def build_cloud_continuation(
    *,
    task_id: str,
    url: str,
    display_url: str,
    platform: str,
    media_id: str,
    video_title: str,
    author: str,
    description: str,
    is_generic: bool,
    include_comments: bool,
    comment_limit: int,
    preserve_transcript_timestamps: bool = False,
) -> str:
    """Serialize only the stable, non-secret inputs needed after ASR."""
    values = locals()
    payload = {"version": 1}
    payload.update({key: values[key] for key in _CONTINUATION_KEYS})
    payload["url"] = _sanitize_continuation_url(payload["url"])
    payload["display_url"] = _sanitize_continuation_url(
        payload["display_url"]
    )
    if not all(
        isinstance(payload[key], str) and payload[key]
        for key in ("task_id", "url", "display_url", "platform", "media_id")
    ):
        raise ValueError("invalid_cloud_continuation")
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def load_cloud_continuation(value: str) -> dict[str, Any]:
    """Load one versioned continuation and reject extra persisted fields."""
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_cloud_continuation") from None
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("invalid_cloud_continuation")
    if set(payload) != {"version", *_CONTINUATION_KEYS}:
        raise ValueError("invalid_cloud_continuation")
    return payload


def dispatch_post_asr(
    result: TranscriptionResult,
    continuation_json: str,
    *,
    cache_manager: Any,
    llm_queue: Any,
    repository: Any,
    ephemeral: Mapping[str, Any] | None = None,
    stop_event: Any | None = None,
) -> bool:
    """Idempotently save one materialized result and enqueue its stable key."""
    if _stop_requested(stop_event):
        return False
    payload = load_cloud_continuation(continuation_json)
    event_id = result.usage_event_id
    if not event_id:
        raise ValueError("usage_event_id_required")
    event = repository.get_event(event_id)
    if event.continuation_json != continuation_json:
        raise ValueError("continuation_identity_conflict")
    if event.postprocess_status == "completed":
        return True

    task = cache_manager.get_task_by_id(payload["task_id"]) or {}
    if _stop_requested(stop_event):
        return False
    terminal_status = task.get("status")
    if terminal_status in {
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
        TaskStatus.SUCCESS,
    }:
        owner = uuid4().hex
        now = datetime.now(UTC)
        if repository.claim_postprocess(event.id, owner, now=now):
            repository.complete_postprocess(
                event.id, owner, now=datetime.now(UTC)
            )
        return terminal_status == TaskStatus.SUCCESS

    structured = result.funasr_json_data
    preserve_timestamps = bool(payload["preserve_transcript_timestamps"])
    transcript_data = structured if preserve_timestamps and structured else result.transcript
    transcript_type = "funasr" if preserve_timestamps and structured else "capswriter"
    if _stop_requested(stop_event):
        return False
    if not cache_manager.save_cache(
        platform=payload["platform"],
        url=payload["url"],
        media_id=payload["media_id"],
        use_speaker_recognition=False,
        transcript_data=transcript_data,
        transcript_type=transcript_type,
        title=payload["video_title"],
        author=payload["author"],
        description=payload["description"],
        source_language=result.language,
    ):
        raise RuntimeError("postprocess_cache_write_failed")
    if _stop_requested(stop_event):
        return False

    llm_payload = {
        "task_id": payload["task_id"],
        "url": payload["url"],
        "display_url": payload["display_url"],
        "platform": payload["platform"],
        "media_id": payload["media_id"],
        "video_title": payload["video_title"],
        "author": payload["author"],
        "description": payload["description"],
        "transcript": result.transcript,
        "use_speaker_recognition": False,
        "transcription_data": None,
        "is_generic": payload["is_generic"],
        "wechat_webhook": None,
        "notification_channel": None,
        "notification_webhooks": {},
        "include_comments": payload["include_comments"],
        "comment_limit": payload["comment_limit"],
        "usage_event_id": event.id,
        "postprocess_key": event.postprocess_key,
    }
    if ephemeral:
        for key in (
            "wechat_webhook",
            "notification_channel",
            "notification_webhooks",
            "perf_tracker",
        ):
            if key in ephemeral:
                llm_payload[key] = ephemeral[key]
    if _stop_requested(stop_event):
        return False
    llm_queue.put(llm_payload)
    cache_manager.update_task_status(
        payload["task_id"],
        TaskStatus.CALIBRATING,
        platform=payload["platform"],
        media_id=payload["media_id"],
        title=payload["video_title"],
        author=payload["author"],
    )
    return True


def dispatch_pending_post_asr(
    *,
    repository: Any,
    output_dir: str | Path,
    cache_manager: Any,
    llm_queue: Any,
    stop_event: Any | None = None,
) -> int:
    """Redeliver durable postprocess rows from materialized local artifacts."""
    output_root = Path(output_dir)
    dispatched = 0
    for event in repository.list_pending_postprocess():
        if _stop_requested(stop_event):
            break
        txt_path = output_root / f"{event.output_name}.txt"
        json_path = output_root / f"{event.output_name}_funasr.json"
        try:
            transcript = txt_path.read_text(encoding="utf-8")
            structured = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _stop_requested(stop_event):
            break
        result = TranscriptionResult(
            transcript=transcript,
            txt_path=str(txt_path),
            funasr_json_data=structured,
            generated_files=(txt_path, json_path),
            provider=event.provider,
            model=event.model,
            usage_event_id=event.id,
        )
        if dispatch_post_asr(
            result,
            event.continuation_json,
            cache_manager=cache_manager,
            llm_queue=llm_queue,
            repository=repository,
            stop_event=stop_event,
        ):
            dispatched += 1
    return dispatched
