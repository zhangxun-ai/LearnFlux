"""OpenAI-only planning and image generation with no automatic retries."""

from __future__ import annotations

import base64
import copy
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack
import json
import math
from pathlib import Path
import re
from typing import Any, Callable

from .config import ImageDiagramSettings
from .prompts import (
    MAX_IMAGE_PROMPT_CHARS,
    build_planning_prompt,
    build_synthesis_prompt,
    render_paragraphs,
)


class ImageDiagramAPIError(RuntimeError):
    """An intentionally content-free provider failure safe for storage and logs."""

    def __init__(self, code: str, unknown_outcome: bool = False, usage: dict | None = None):
        self.code = code
        self.unknown_outcome = unknown_outcome
        self.usage = usage or {}
        super().__init__(code)


def _object(properties: dict) -> dict:
    return {
        "type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False,
    }


def _string(max_length: int) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": max_length}


_REFS = {"type": "array", "items": _string(160), "minItems": 1, "maxItems": 12}
_PLAN_SCHEMA = _object({
    "title": _string(160),
    "learning_goal": _string(600),
    "visual_story": _string(800),
    "must_show": {
        "type": "array", "minItems": 1, "maxItems": 8,
        "items": _object({"text": _string(600), "source_ref_ids": _REFS}),
    },
    "sections": {
        "type": "array", "minItems": 1, "maxItems": 8,
        "items": _object({
            "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,60}$"},
            "title": _string(160), "source_ref_ids": _REFS,
        }),
    },
    "caveats": {"type": "array", "items": _string(600), "maxItems": 8},
    "case_studies": {
        "type": "array", "maxItems": 2,
        "items": _object({"title": _string(160), "text": _string(600), "source_ref_ids": _REFS}),
    },
})

def _plan_schema(allowed_ids: set[str]) -> dict:
    """Constrain references during decoding, as well as checking them afterward."""
    schema = copy.deepcopy(_PLAN_SCHEMA)
    reference = {"type": "string", "enum": sorted(allowed_ids)} if len(allowed_ids) <= 333 else {
        "type": "string", "pattern": r"^P[1-9][0-9]*$",
    }
    for field in ("must_show", "sections", "case_studies"):
        schema["properties"][field]["items"]["properties"]["source_ref_ids"]["items"] = reference
    return schema


def _value(value: Any, name: str, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _usage(response: Any) -> dict:
    usage = _value(response, "usage")
    # Some SDK-constructed usage models lack optional Pydantic internals under
    # the project's supported older Pydantic. Read their parsed fields directly;
    # accounting serialization must not invalidate an already paid response.
    if not isinstance(usage, dict) and hasattr(usage, "__dict__"):
        usage = vars(usage)
    # Usage responses must never smuggle provider error text into local artifacts.
    def numeric_tree(value):
        if not isinstance(value, dict) and hasattr(value, "__dict__"):
            value = vars(value)
        if isinstance(value, dict):
            return {key: cleaned for key, item in value.items()
                    if isinstance(key, str) and not key.startswith("_") and re.fullmatch(r"[A-Za-z0-9_]{1,80}", key)
                    and (cleaned := numeric_tree(item)) is not None}
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return value
        return None
    return numeric_tree(usage) if isinstance(usage, dict) else {}


def _request_id(response: Any) -> str | None:
    value = _value(response, "_request_id")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) else None


def _stage_usage(stage: str, usage: dict) -> dict:
    return {stage: {"calls": [usage]} if stage == "planning" else usage}


def _safe_error(exc: Exception, *, image_request: bool = False) -> ImageDiagramAPIError:
    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        return ImageDiagramAPIError("openai_access_denied")
    if status == 429:
        return ImageDiagramAPIError("openai_quota_or_rate_limit")
    if isinstance(status, int) and 400 <= status < 500 and status not in {408, 409}:
        return ImageDiagramAPIError("openai_request_rejected")
    name = type(exc).__name__.lower()
    ambiguous = (
        isinstance(exc, (TimeoutError, ConnectionError))
        or any(word in name for word in ("timeout", "connection", "transport"))
        or status in {408, 409}
        or isinstance(status, int) and status >= 500
    )
    code = "image_outcome_unknown" if image_request and ambiguous else "openai_request_failed"
    return ImageDiagramAPIError(code, unknown_outcome=image_request and ambiguous)


def _validate_refs(plan: dict, allowed_ids: set[str]) -> None:
    for field in ("must_show", "sections"):
        items = plan.get(field)
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise ImageDiagramAPIError("invalid_image_plan")
        for item in items:
            if not isinstance(item, dict):
                raise ImageDiagramAPIError("invalid_image_plan")
            refs = item.get("source_ref_ids")
            if (
                not isinstance(refs, list) or not refs or len(refs) > 12
                or any(not isinstance(ref, str) or ref not in allowed_ids for ref in refs)
            ):
                raise ImageDiagramAPIError("invalid_image_plan_reference")
            label = item.get("text" if field == "must_show" else "title")
            if not isinstance(label, str) or not label.strip() or len(label) > 600:
                raise ImageDiagramAPIError("invalid_image_plan")
            if field == "sections" and not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", str(item.get("id", ""))):
                raise ImageDiagramAPIError("invalid_image_plan")
    if len({item["id"] for item in plan["sections"]}) != len(plan["sections"]):
        raise ImageDiagramAPIError("invalid_image_plan")
    if any(not isinstance(plan.get(key), str) or not plan[key].strip() for key in ("title", "learning_goal")):
        raise ImageDiagramAPIError("invalid_image_plan")
    if not isinstance(plan.get("caveats"), list) or any(not isinstance(value, str) for value in plan["caveats"]):
        raise ImageDiagramAPIError("invalid_image_plan")
    if not isinstance(plan.get("visual_story"), str) or not plan["visual_story"].strip():
        raise ImageDiagramAPIError("invalid_image_plan")
    cases = plan.get("case_studies")
    if not isinstance(cases, list) or len(cases) > 2:
        raise ImageDiagramAPIError("invalid_image_plan")
    for case in cases:
        if not isinstance(case, dict) or any(
            not isinstance(case.get(key), str) or not case[key].strip()
            for key in ("title", "text")
        ):
            raise ImageDiagramAPIError("invalid_image_plan")
        refs = case.get("source_ref_ids")
        if not isinstance(refs, list) or not 1 <= len(refs) <= 12 or any(not isinstance(ref, str) or ref not in allowed_ids for ref in refs):
            raise ImageDiagramAPIError("invalid_image_plan_reference")


def _chunks(paragraphs: list[dict], limit: int) -> list[list[dict]]:
    """Cover every character, even when an individual source paragraph exceeds a chunk."""
    chunks, current, chars = [], [], 0
    for paragraph in paragraphs:
        text = str(paragraph["text"])
        for offset in range(0, len(text), limit):
            part = {**paragraph, "text": text[offset:offset + limit]}
            if current and chars + len(part["text"]) > limit:
                chunks.append(current)
                current, chars = [], 0
            current.append(part)
            chars += len(part["text"])
    if current:
        chunks.append(current)
    return chunks


class OpenAIImageDiagramClient:
    """Run only explicitly requested work, through the official OpenAI endpoint."""

    def __init__(self, settings: ImageDiagramSettings, client=None):
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if not settings.api_key:
                raise ImageDiagramAPIError("openai_key_missing")
            from openai import OpenAI

            # Shared LLM gateways and OPENAI_BASE_URL must never receive this key.
            self.client = OpenAI(
                api_key=settings.api_key,
                base_url="https://api.openai.com/v1",
                timeout=settings.timeout,
                max_retries=0,
            )

    def _structured(self, prompt: str, schema: dict, name: str):
        model = self.settings.text_model
        content = [{"type": "input_text", "text": prompt}]
        kwargs = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "store": False,
            "max_output_tokens": 6000,
            "text": {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        }
        if model.startswith(("gpt-5", "gpt-6")):
            kwargs["reasoning"] = {"effort": "low"}
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            raise _safe_error(exc) from None
        usage = {"model": model, "usage": _usage(response),
                 "request_id": _request_id(response)}
        if _value(response, "status", "completed") != "completed":
            raise ImageDiagramAPIError("openai_response_incomplete", usage=_stage_usage("planning", usage))
        text = _value(response, "output_text", "")
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            raise ImageDiagramAPIError("openai_invalid_json", usage=_stage_usage("planning", usage)) from None
        if not isinstance(payload, dict):
            raise ImageDiagramAPIError("openai_invalid_json", usage=_stage_usage("planning", usage))
        return payload, usage

    def plan(self, source: dict, request: dict, *, on_progress: Callable[[dict], None] | None = None) -> dict:
        """Read all allowed source text in bounded chunks, then synthesize a grounded brief."""
        paragraphs = source.get("paragraphs", [])
        if not paragraphs or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str)
            or not isinstance(item.get("text"), str) or not item["text"].strip()
            for item in paragraphs
        ):
            raise ImageDiagramAPIError("image_source_not_ready")
        total_chars = sum(len(item["text"]) for item in paragraphs)
        if total_chars > self.settings.max_source_chars:
            raise ImageDiagramAPIError("image_source_too_large")
        allowed_ids = {item["id"] for item in paragraphs}
        if len(allowed_ids) != len(paragraphs):
            raise ImageDiagramAPIError("invalid_image_source_identity")
        # Plan the whole allowed source once when it fits the configured budget.
        # Fragmented source lines and JSON labels count toward that budget too.
        chunks = ([paragraphs] if len(render_paragraphs(paragraphs)) <= self.settings.single_pass_chars
                  else _chunks(paragraphs, self.settings.chunk_chars))
        briefs, calls = [None] * len(chunks), []
        completed_chars = 0

        def report(phase: str, completed: int) -> None:
            if on_progress:
                on_progress({"phase": phase, "completed_chunks": completed,
                             "total_chunks": len(chunks), "read_chars": completed_chars,
                             "source_chars": total_chars})

        try:
            report("reading", 0)

            def read_chunk(chunk):
                brief, usage = self._structured(
                    build_planning_prompt(source, request, chunk,
                                          previous_plan=request.get("previous_plan") if len(chunks) == 1 else None),
                    _plan_schema({item["id"] for item in chunk}), "image_diagram_plan"
                )
                try:
                    _validate_refs(brief, {item["id"] for item in chunk})
                except ImageDiagramAPIError as exc:
                    exc.usage = _stage_usage("planning", usage)
                    raise
                return brief, usage

            workers = min(self.settings.planning_workers, len(chunks))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="diagram-plan") as executor:
                pending, next_chunk, completed, failure = {}, 0, 0, None
                while pending or next_chunk < len(chunks):
                    # Only one bounded window is submitted. On failure, drain
                    # already-running calls for accounting; never launch the tail.
                    while failure is None and next_chunk < len(chunks) and len(pending) < workers:
                        pending[executor.submit(read_chunk, chunks[next_chunk])] = next_chunk
                        next_chunk += 1
                    if not pending:
                        break
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in sorted(done, key=lambda item: pending[item]):
                        index = pending.pop(future)
                        try:
                            brief, usage = future.result()
                            calls.append(usage)
                            briefs[index] = brief
                            completed += 1
                            completed_chars += sum(len(item["text"]) for item in chunks[index])
                            if failure is None:
                                report("reading", completed)
                        except ImageDiagramAPIError as exc:
                            calls.extend((exc.usage.get("planning") or {}).get("calls", []))
                            failure = failure or ImageDiagramAPIError(exc.code)
                        except Exception:
                            failure = failure or ImageDiagramAPIError("image_planning_failed")
                if failure is not None:
                    raise failure
            plan = briefs[0]
            if len(briefs) > 1:
                report("composing", len(chunks))
                plan, usage = self._structured(
                    build_synthesis_prompt(source, request, briefs),
                    _plan_schema(allowed_ids), "image_diagram_synthesis"
                )
                calls.append(usage)
                _validate_refs(plan, allowed_ids)
        except ImageDiagramAPIError as exc:
            response_calls = (exc.usage.get("planning") or {}).get("calls", [])
            exc.usage["planning"] = {"calls": calls + response_calls}
            raise
        plan["coverage"] = {
            "mode": "full" if len(chunks) == 1 else "full_chunked",
            "source_paragraphs": len(paragraphs),
            "covered_paragraphs": len(paragraphs),
            "source_chars": total_chars,
            "chunks": len(chunks),
        }
        plan["usage"] = {"calls": calls}
        return plan

    def generate(
        self, prompt: str, reference_paths: list[Path], revision_image: Path | None = None
    ) -> dict:
        """Generate one image; ambiguous failures must never cause automatic resubmission."""
        roles = (
            "输入图1为上一版修订目标，其余输入图仅提供美术风格。\n"
            if revision_image is not None else "所有输入图仅为美术参考，内容以本次材料为准。\n"
        )
        effective_prompt = roles + prompt
        if len(effective_prompt) > MAX_IMAGE_PROMPT_CHARS:
            raise ImageDiagramAPIError("image_prompt_too_long")
        paths = ([revision_image] if revision_image is not None else []) + list(reference_paths)
        if len(paths) > 16:
            raise ImageDiagramAPIError("too_many_image_references")
        kwargs = {
            "model": self.settings.image_model, "prompt": effective_prompt,
            "n": 1, "quality": self.settings.quality, "size": self.settings.size,
            "output_format": "png",
        }
        with ExitStack() as stack:
            if paths:
                for path in paths:
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
                        raise ImageDiagramAPIError("invalid_image_reference")
                kwargs["image"] = [stack.enter_context(path.open("rb")) for path in paths]
            try:
                result = self.client.images.edit(**kwargs) if paths else self.client.images.generate(**kwargs)
            except Exception as exc:
                raise _safe_error(exc, image_request=True) from None
        confirmed_usage = {"image": {
            "model": self.settings.image_model, "usage": _usage(result),
            "request_id": _request_id(result),
        }}
        data = _value(result, "data", [])
        if not data or len(data) != 1:
            raise ImageDiagramAPIError("invalid_image_response", unknown_outcome=True, usage=confirmed_usage)
        encoded = _value(data[0], "b64_json", "")
        if not isinstance(encoded, str) or len(encoded) > 72 * 1024 * 1024:
            raise ImageDiagramAPIError("invalid_image_response", unknown_outcome=True, usage=confirmed_usage)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ImageDiagramAPIError("invalid_image_response", unknown_outcome=True, usage=confirmed_usage) from None
        if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > 50 * 1024 * 1024:
            raise ImageDiagramAPIError("invalid_image_response", unknown_outcome=True, usage=confirmed_usage)
        return {"image_bytes": raw, "usage": _usage(result), "request_id": _request_id(result)}

