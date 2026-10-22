"""Current Xiaohongshu detail API contracts shared by acquisition clients."""

from typing import Any
from urllib.parse import parse_qs, urlsplit

from .xiaohongshu_url import normalize_xiaohongshu_url

APP_VIDEO_DETAIL = "/api/v1/xiaohongshu/app_v2/get_video_note_detail"
APP_NOTE_DETAIL = "/api/v1/xiaohongshu/app_v2/get_image_note_detail"
WEB_NOTE_DETAIL = "/api/v1/xiaohongshu/web_v3/fetch_note_detail"


def note_detail_candidates(url: str, note_id: str) -> list[tuple[str, dict]]:
    """App V2 returns both note types; signed Web V3 is the fallback.

    The image endpoint identifies video notes but does not return their streams.
    Video downloads must use APP_VIDEO_DETAIL after classification.
    """
    url = normalize_xiaohongshu_url(url)
    candidates = [(APP_NOTE_DETAIL, {"note_id": note_id})]
    xsec = parse_qs(urlsplit(url).query).get("xsec_token", [""])[0]
    if xsec:
        candidates.append((WEB_NOTE_DETAIL, {"note_id": note_id, "xsec_token": xsec}))
    return candidates


def response_data(response: Any) -> Any:
    """Reject upstream failures even when TikHub's outer HTTP/code is 200."""
    if not isinstance(response, dict):
        raise ValueError("小红书 API 返回无效响应")
    current = response
    for _ in range(6):
        if not isinstance(current, dict):
            break
        code = current.get("code")
        if code not in (None, 0, 200) or current.get("success") is False:
            # Upstream messages may contain signed URLs; expose only the code.
            raise ValueError(f"小红书内容接口返回错误 (code={code})")
        if "data" not in current:
            break
        current = current["data"]
    return response.get("data", response)
