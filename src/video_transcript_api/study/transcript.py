import re
from typing import Any


def _coerce_seconds(value: Any, unit: str = "auto") -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if unit == "milliseconds" or (unit == "auto" and number > 1000):
        number = number / 1000
    return round(number, 3)


def _text_from_segment(segment: dict) -> str:
    for key in ("text", "sentence", "content", "value"):
        value = segment.get(key)
        if value:
            return str(value).strip()
    return ""


def _segment_times(segment: dict) -> tuple[float | None, float | None]:
    if "start_ms" in segment:
        start_seconds = _coerce_seconds(segment.get("start_ms"), "milliseconds")
    elif "start_time" in segment:
        start_seconds = _coerce_seconds(segment.get("start_time"), "seconds")
    else:
        start_seconds = _coerce_seconds(segment.get("start"))

    if "end_ms" in segment:
        end_seconds = _coerce_seconds(segment.get("end_ms"), "milliseconds")
    elif "end_time" in segment:
        end_seconds = _coerce_seconds(segment.get("end_time"), "seconds")
    else:
        end_seconds = _coerce_seconds(segment.get("end"))
    return start_seconds, end_seconds


def _iter_segments(payload: Any):
    if isinstance(payload, list):
        yield from payload
        return
    if isinstance(payload, dict):
        for key in ("segments", "sentences", "result", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                yield from value
                return


def _line(line_id: int, text: str, start_seconds=None, end_seconds=None) -> dict:
    seekable = start_seconds is not None
    return {
        "id": f"line-{line_id}",
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "text": text,
        "seekable": seekable,
    }


def _split_long_sentence(text: str, max_chars: int = 120) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks = []
    buffer = ""
    clauses = re.split(r"(?<=[，,、：:])", text)
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        if buffer and len(buffer) + len(clause) > max_chars:
            chunks.append(buffer)
            buffer = ""
        while len(clause) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(clause[:max_chars])
            clause = clause[max_chars:]
        buffer += clause
    if buffer:
        chunks.append(buffer)
    return chunks


def _split_plain_text(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        sentences = re.split(r"(?<=[。！？!?；;])\s*", raw_line)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                lines.extend(_split_long_sentence(sentence))
    return lines


def normalize_transcript(transcript_data: Any) -> list[dict]:
    if isinstance(transcript_data, str):
        parts = _split_plain_text(transcript_data)
        return [_line(index, text) for index, text in enumerate(parts, start=1)]

    lines = []
    legacy_long_whisper_scale = False
    previous_start = None
    for segment in _iter_segments(transcript_data):
        if not isinstance(segment, dict):
            continue
        text = _text_from_segment(segment)
        if not text:
            continue
        start_seconds, end_seconds = _segment_times(segment)
        if legacy_long_whisper_scale:
            start_seconds = _scale_legacy_long_whisper_time(start_seconds)
            end_seconds = _scale_legacy_long_whisper_time(end_seconds)
        elif (
            start_seconds is not None
            and start_seconds >= 900
            and end_seconds is not None
            and end_seconds < start_seconds / 100
        ):
            end_seconds = _scale_legacy_long_whisper_time(end_seconds)
            legacy_long_whisper_scale = True
        elif (
            previous_start is not None
            and previous_start >= 900
            and start_seconds is not None
            and start_seconds < previous_start / 100
        ):
            start_seconds = _scale_legacy_long_whisper_time(start_seconds)
            end_seconds = _scale_legacy_long_whisper_time(end_seconds)
            legacy_long_whisper_scale = True
        lines.append(_line(len(lines) + 1, text, start_seconds, end_seconds))
        if start_seconds is not None:
            previous_start = start_seconds
    return lines


def _scale_legacy_long_whisper_time(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 1000, 3)
