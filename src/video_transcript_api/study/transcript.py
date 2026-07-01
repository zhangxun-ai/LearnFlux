from typing import Any


def _coerce_seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1000:
        number = number / 1000
    return round(number, 3)


def _text_from_segment(segment: dict) -> str:
    for key in ("text", "sentence", "content", "value"):
        value = segment.get(key)
        if value:
            return str(value).strip()
    return ""


def _segment_times(segment: dict) -> tuple[float | None, float | None]:
    start = (
        segment.get("start")
        if "start" in segment
        else segment.get("start_time", segment.get("start_ms"))
    )
    end = (
        segment.get("end")
        if "end" in segment
        else segment.get("end_time", segment.get("end_ms"))
    )
    return _coerce_seconds(start), _coerce_seconds(end)


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


def normalize_transcript(transcript_data: Any) -> list[dict]:
    if isinstance(transcript_data, str):
        parts = [part.strip() for part in transcript_data.splitlines() if part.strip()]
        return [_line(index, text) for index, text in enumerate(parts, start=1)]

    lines = []
    for segment in _iter_segments(transcript_data):
        if not isinstance(segment, dict):
            continue
        text = _text_from_segment(segment)
        if not text:
            continue
        start_seconds, end_seconds = _segment_times(segment)
        lines.append(_line(len(lines) + 1, text, start_seconds, end_seconds))
    return lines
