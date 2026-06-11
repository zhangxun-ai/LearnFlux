"""Single-note acquisition: a note URL -> (media_type, title, text, stats).

For an ARTICLE the analyzable text is the note body (desc). For a VIDEO the
analyzable text is the spoken transcript, produced by the project's existing
transcription pipeline (download -> ASR) — heavier, and reused as-is.

Defensive parsing mirrors ``comments/xiaohongshu_post.py`` (TikHub note endpoints
are individually flaky, so several are tried).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from ..utils.logging import setup_logger
from .fetchers import _as_int, _first
from .models import MediaType

logger = setup_logger("flywheel_text_acquisition")

ApiRequest = Callable[[str, dict], dict]


@dataclass(frozen=True)
class NoteDetail:
    note_id: str
    media_type: MediaType
    title: str
    body_text: str          # desc/caption (article body, or video caption)
    author: str
    author_user_id: str = ""
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0


def _note_id_from_url(url: str) -> str:
    m = re.search(r"/(?:discovery/item|explore|item)/([0-9a-zA-Z]+)", url)
    return m.group(1) if m else ""


def _xsec_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query).get("xsec_token", [""])[0]


def _endpoint_candidates(url: str, note_id: str, xsec: str) -> list[tuple[str, dict]]:
    candidates: list[tuple[str, dict]] = []
    if xsec:
        candidates.append(("/api/v1/xiaohongshu/web_v3/fetch_note_detail",
                           {"note_id": note_id, "xsec_token": xsec}))
    candidates.append(("/api/v1/xiaohongshu/web/get_note_info_v7",
                       {"note_id": note_id, "share_text": url}))
    candidates.append(("/api/v1/xiaohongshu/app_v2/get_image_note_detail",
                       {"note_id": note_id, "share_text": url}))
    candidates.append(("/api/v1/xiaohongshu/web/get_note_info_v4",
                       {"note_id": note_id, "share_text": url}))
    return candidates


def _data(resp: Any) -> Any:
    if not isinstance(resp, dict):
        raise ValueError("小红书 API 返回无效响应")
    if resp.get("code") not in (None, 0, 200) and not resp.get("success", True):
        raise ValueError(resp.get("msg") or "小红书 API 返回错误")
    return resp.get("data", resp)


def _find_note_dict(obj: Any) -> Optional[dict]:
    if isinstance(obj, dict):
        if "desc" in obj or "title" in obj or "interact_info" in obj or "type" in obj:
            return obj
        for v in obj.values():
            found = _find_note_dict(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj[:8]:
            found = _find_note_dict(v)
            if found:
                return found
    return None


def _extract_note(resp: Any) -> Optional[dict]:
    data = _data(resp)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        note_list = data[0].get("note_list")
        if isinstance(note_list, list) and note_list and isinstance(note_list[0], dict):
            return note_list[0]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            card = items[0].get("noteCard") or items[0].get("note_card")
            if isinstance(card, dict):
                return card
    return _find_note_dict(data)


def _media_type(note: dict) -> MediaType:
    t = str(_first(note, ("type", "note_type"), "normal")).lower()
    return MediaType.VIDEO if t == "video" else MediaType.ARTICLE


def fetch_note_detail(url: str, *, api_request: Optional[ApiRequest] = None) -> NoteDetail:
    """Fetch a single note's type/title/body/stats via TikHub (tries several endpoints)."""
    note_id = _note_id_from_url(url)
    if not note_id:
        raise ValueError(f"无法从链接解析 note_id: {url}")
    xsec = _xsec_from_url(url)
    request = api_request
    if request is None:
        from ..downloaders import create_downloader  # lazy: avoid heavy import in unit tests
        request = create_downloader(url).make_api_request

    last_error: Optional[Exception] = None
    for endpoint, params in _endpoint_candidates(url, note_id, xsec):
        try:
            note = _extract_note(request(endpoint, params))
            if not note:
                continue
            title = str(_first(note, ("title", "display_title"), "")).strip()
            desc = str(_first(note, ("desc", "description"), "")).strip()
            if not title and not desc:
                continue
            interact = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else note
            user = note.get("user") if isinstance(note.get("user"), dict) else {}
            logger.info(f"fetched note detail via {endpoint}: id={note_id}")
            return NoteDetail(
                note_id=note_id,
                media_type=_media_type(note),
                title=title or f"小红书笔记 {note_id}",
                body_text=desc,
                author=str(_first(user, ("nickname", "nick_name", "name"), "unknown")),
                author_user_id=str(_first(user, ("user_id", "userId", "id"), "")),
                like_count=_as_int(_first(interact, ("liked_count", "like_count"), 0)),
                collect_count=_as_int(_first(interact, ("collected_count", "collect_count"), 0)),
                comment_count=_as_int(_first(interact, ("comment_count", "comments"), 0)),
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(f"note endpoint failed: {endpoint}, error={exc}")
    raise ValueError(f"无法获取笔记详情（已尝试多个接口）: {last_error}")


def transcribe_video_url(url: str, *, config: Optional[dict] = None) -> str:
    """Download a video note and transcribe it via the project's pipeline.

    Reuses the existing downloader + Transcriber (local whisper when enabled). The
    flywheel does not reimplement ASR — it delegates to the project's core.
    """
    from ..downloaders import create_downloader  # lazy heavy imports
    from ..transcriber.transcriber import Transcriber
    from ..utils.logging import load_config

    config = config or load_config()
    downloader = create_downloader(url)
    info = downloader.get_video_info(url)
    download_url = info.get("download_url")
    if not download_url:
        raise ValueError("未获取到视频下载地址")
    filename = info.get("filename") or f"{info.get('video_id', 'video')}.mp4"

    local_path = downloader.download_file(download_url, filename)
    if not local_path:
        raise ValueError("视频下载失败")

    result = Transcriber(config).transcribe(local_path)
    transcript = ((result or {}).get("transcript") or "").strip()
    if not transcript:
        raise ValueError("转写结果为空")
    logger.info(f"transcribed video note: chars={len(transcript)}")
    return transcript


def acquire_text(url: str, *, config: Optional[dict] = None,
                 api_request: Optional[ApiRequest] = None) -> tuple[NoteDetail, str]:
    """Return ``(detail, analyzable_text)`` for a note URL.

    Article -> note body; Video -> spoken transcript.
    """
    detail = fetch_note_detail(url, api_request=api_request)
    if detail.media_type is MediaType.VIDEO:
        text = transcribe_video_url(url, config=config)
    else:
        text = detail.body_text
    return detail, text
