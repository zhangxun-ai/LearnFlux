"""Read the text of a public article without executing page code."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.helpers import is_ip_address
from bs4 import BeautifulSoup, Tag
from yarl import URL

_MAX_HTML_BYTES = 4 * 1024 * 1024
_MAX_TEXT_CHARS = 200_000
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_PASTE_TEXT = "可以打开原文，复制正文到「单篇深度学习 → 粘贴文字」。"
_NAT64_PREFIXES = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


class WebArticleError(ValueError):
    """A page could not safely be read as a public article."""


@dataclass(frozen=True)
class WebArticle:
    title: str
    author: str
    text: str
    has_images: bool


def _require_public_address(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif (
            ip.sixtofour or ip.teredo or ip.is_site_local or ip.scope_id
            or any(ip in prefix for prefix in _NAT64_PREFIXES)
        ):
            raise WebArticleError("网页链接必须指向公开网站。")
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        raise WebArticleError("网页链接必须指向公开网站。")


class _PublicResolver(AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC):
        # The connector uses these numeric addresses for the connection while
        # retaining the original hostname for Host, SNI and TLS verification.
        entries = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM,
        )
        addresses = []
        for af, _, proto, _, sockaddr in entries:
            _require_public_address(sockaddr[0])
            addresses.append({
                "hostname": host, "host": sockaddr[0], "port": port, "family": af,
                "proto": proto, "flags": socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            })
        return addresses

    async def close(self) -> None:
        pass


def _check_target(url: URL) -> None:
    expected_ports = {"http": 80, "https": 443}
    host = url.raw_host
    if (
        url.scheme not in expected_ports or not host
        or url.raw_user is not None or url.raw_password is not None
        or url.port != expected_ports[url.scheme]
    ):
        raise WebArticleError("请提交公开的 HTTP 或 HTTPS 网页链接。")
    # aiohttp bypasses its resolver when the hostname is an IP literal.
    if is_ip_address(host):
        try:
            _require_public_address(host)
        except WebArticleError:
            raise
        except ValueError as exc:
            raise WebArticleError("网页链接必须指向公开网站。") from exc


async def _read_page(url: str) -> WebArticle | None:
    target = URL(url)
    connector = aiohttp.TCPConnector(resolver=_PublicResolver(), family=socket.AF_UNSPEC)
    async with asyncio.timeout(15), aiohttp.ClientSession(
        connector=connector, cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
        headers={"Accept": "text/html, application/xhtml+xml, */*;q=0.1", "Accept-Encoding": "identity"},
        auto_decompress=False,
    ) as session:
        for _ in range(6):
            _check_target(target)
            async with session.get(target, allow_redirects=False) as response:
                if response.status in _REDIRECT_STATUSES and response.headers.get("Location"):
                    target = target.join(URL(response.headers["Location"]))
                    continue
                if response.status != 200:
                    raise WebArticleError(f"网站未返回可读取的正文（HTTP {response.status}）。{_PASTE_TEXT}")
                if response.content_type not in _HTML_TYPES:
                    return None
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise WebArticleError(f"暂时无法读取该网站返回的网页格式。{_PASTE_TEXT}")
                body = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    body.extend(chunk)
                    if len(body) > _MAX_HTML_BYTES:
                        raise WebArticleError(f"网页超过读取大小限制。{_PASTE_TEXT}")
                return _extract_article(bytes(body), encoding=response.charset)
    raise WebArticleError(f"网页跳转次数过多。{_PASTE_TEXT}")


def _extract_article(html: bytes, *, encoding: str | None = None) -> WebArticle:
    soup = BeautifulSoup(html, "html.parser", from_encoding=encoding)
    for element in soup.select(
        "script, style, noscript, template, nav, aside, footer, form, button, "
        "[hidden], [aria-hidden='true'], [role='navigation']"
    ):
        element.decompose()

    # Prefer explicit article containers. Editorial sites sometimes use a
    # prose wrapper instead of <article>, with the headline outside that wrapper.
    containers = (
        soup.select("[itemprop='articleBody'], article, .article-body, .post-content, .prose"),
        soup.select("main, [role='main']"),
    )
    for candidates in containers:
        if candidates:
            body = max(candidates, key=_prose_length)
            if _prose_length(body) >= 100:
                break
    else:
        raise WebArticleError(f"没有从网页中提取到足够的文章正文。{_PASTE_TEXT}")

    has_images = body.find(["img", "svg", "canvas"]) is not None
    for svg in body.find_all("svg"):
        svg.decompose()
    headline = body.find("h1") or soup.find("h1")
    title = headline.get_text(" ", strip=True) if headline else (
        _meta(soup, "property", "og:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    )
    blocks = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "tr", "figcaption"}
    paragraphs = []
    for block in body.find_all(blocks):
        if block is headline or block.find_parent(blocks):
            continue
        if block.name == "pre":
            text = block.get_text().strip("\n")
        elif block.name == "tr":
            text = " | ".join(cell.get_text(" ", strip=True) for cell in block.find_all(["th", "td"]))
        else:
            text = block.get_text(" ", strip=True)
        if text:
            paragraphs.append(text)
    text = "\n\n".join(paragraphs)
    if len(text) > _MAX_TEXT_CHARS:
        raise WebArticleError(f"文章超过正文长度限制。{_PASTE_TEXT}")
    author = _meta(soup, "name", "author") or _meta(soup, "property", "article:author")
    return WebArticle(title[:500] or "网页文章", author[:200], text, has_images)


def _prose_length(container: Tag) -> int:
    return sum(len(p.get_text(" ", strip=True)) for p in container.find_all("p"))


def _meta(soup: BeautifulSoup, attribute: str, value: str) -> str:
    tag = soup.find("meta", attrs={attribute: value})
    return str(tag.get("content") or "").strip() if tag else ""


def fetch_web_article(url: str) -> WebArticle | None:
    """Return article text, or None when the URL returns non-HTML content."""
    try:
        return asyncio.run(_read_page(url))
    except WebArticleError:
        raise
    except (aiohttp.ClientError, OSError, TimeoutError, ValueError) as exc:
        raise WebArticleError(f"暂时无法读取该网页。{_PASTE_TEXT}") from exc
