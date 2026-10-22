"""Pure Xiaohongshu URL normalization shared by all acquisition paths."""

import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit


_NOTE_PATH = re.compile(r"^/(?:explore|discovery/item|items|item)/([A-Za-z0-9]{24})(?:/|$)")
_REDIRECT_KEYS = ("redirectPath", "redirect_url", "redirect", "redirect_uri")


def _trusted_content_host(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme in {"http", "https"}
                and (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com"))
                and parsed.username is None and parsed.password is None
                and parsed.port in {None, 80, 443})
    except ValueError:
        return False


def normalize_xiaohongshu_url(url: str) -> str:
    """Unwrap trusted login redirects without decoding the note's own query.

    A signed note URL often lives inside a login page's ``redirectPath``.
    Only Xiaohongshu hosts and real note paths may become the result. This
    never follows a network redirect, and never promotes an external target.
    """
    original = url.strip()
    current = original
    for _ in range(5):
        if not _trusted_content_host(current):
            break
        parsed = urlsplit(current)
        if _NOTE_PATH.match(parsed.path):
            return current
        if parsed.path.rstrip("/") not in {"/login", "/website-login"}:
            break
        query = parse_qs(parsed.query)
        target = next((query[key][0] for key in _REDIRECT_KEYS if query.get(key)), "")
        # Decode only an encoded *whole* URL. Decoding an already valid URL
        # would corrupt percent escapes or literal '+' in its xsec_token.
        for _ in range(2):
            if target.startswith(("http://", "https://", "/")):
                break
            decoded = unquote(target)
            if decoded == target:
                break
            target = decoded
        candidate = urljoin("https://www.xiaohongshu.com/", target)
        if not target or not _trusted_content_host(candidate) or candidate == current:
            break
        current = candidate
    return original


def xiaohongshu_note_id(url: str) -> str:
    """Read a note identity only from a trusted content path or a raw ID."""
    if re.fullmatch(r"[A-Za-z0-9]{24}", url):
        return url
    content = normalize_xiaohongshu_url(url)
    if not _trusted_content_host(content):
        return ""
    match = _NOTE_PATH.match(urlsplit(content).path)
    return match.group(1) if match else ""


def url_without_query(url: str) -> str:
    """Keep URL diagnostics useful without exposing signed query strings."""
    try:
        return urlsplit(url)._replace(query="", fragment="").geturl()
    except ValueError:
        return "[invalid URL]"
