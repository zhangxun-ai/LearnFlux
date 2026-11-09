"""Public article extraction, request safety, and the single-study worker."""

import asyncio
import socket
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from yarl import URL

from src.video_transcript_api.document_sources import web

ARTICLE_URL = "https://claude.dev/blog/code-review/"
ARTICLE_HTML = b"""
<head><meta name="author" content="Example Author"></head>
<body>
  <h1>How we review code</h1>
  <nav><p>Navigation and footer links never belong in the article text.</p></nav>
  <div class="prose">
    <p>The reviewer checks whether a proposed change addresses the issue,
       fits the repository, and is supported by useful evidence.</p>
    <h2>Verify the change</h2>
    <p>Authors run the focused checks before asking their teammates to review.</p>
    <figure><svg></svg><figcaption>Checks before release.</figcaption></figure>
    <pre>first_line()
    second_line()</pre>
    <footer><p>Read another article.</p></footer>
  </div>
</body>
"""


def test_extracts_article_body_and_keeps_text_structure():
    article = web._extract_article(ARTICLE_HTML)

    assert article.title == "How we review code"
    assert article.author == "Example Author"
    assert "Verify the change\n\nAuthors run" in article.text
    assert "Checks before release." in article.text
    assert "first_line()\n    second_line()" in article.text
    assert "Navigation" not in article.text
    assert "Read another article." not in article.text
    assert article.has_images


def test_rejects_a_page_without_article_text():
    with pytest.raises(web.WebArticleError, match="复制正文"):
        web._extract_article(b"<main><h1>Sign in</h1><p>Loading...</p></main>")


@pytest.mark.parametrize("address", [
    "http://127.0.0.1", "http://127.000.000.001", "http://169.254.169.254",
    "http://[::ffff:127.0.0.1]", "http://[64:ff9b::a00:1]",
    "https://user:password@example.org/", "https://example.org:8443/",
])
def test_rejects_unsafe_targets_before_fetch(address):
    with pytest.raises(web.WebArticleError):
        web._check_target(URL(address))


def test_resolver_rejects_a_hostname_with_any_private_answer(monkeypatch):
    async def resolve():
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.1", 443)),
        ]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=answers))
        with pytest.raises(web.WebArticleError, match="公开网站"):
            await web._PublicResolver().resolve("example.org", 443)

    asyncio.run(resolve())


def test_redirect_target_is_checked_before_the_next_request(monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        def get(self, url, *, allow_redirects):
            requests.append(url)
            assert allow_redirects is False
            response = Mock(status=302, headers={"Location": "http://127.0.0.1/"})
            return AsyncMock(__aenter__=AsyncMock(return_value=response))

    requests = []
    monkeypatch.setattr(web.aiohttp, "TCPConnector", Mock())
    monkeypatch.setattr(web.aiohttp, "ClientSession", lambda **kwargs: Session())
    with pytest.raises(web.WebArticleError, match="公开网站"):
        web.fetch_web_article(ARTICLE_URL)
    assert requests == [URL(ARTICLE_URL)]


def test_single_study_queues_web_article_text_without_media_work(monkeypatch, tmp_path):
    from src.video_transcript_api.api.routes.views import _decorate_source_link
    from src.video_transcript_api.api.services import transcription
    from src.video_transcript_api.cache.cache_manager import CacheManager
    from src.video_transcript_api.downloaders.generic import GenericDownloader
    from src.video_transcript_api.utils.url_parser import URLParser

    article = web._extract_article(ARTICLE_HTML)
    fetch = Mock(return_value=article)
    monkeypatch.setattr(web, "fetch_web_article", fetch)
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr(transcription, "cache_manager", cache)
    queue = Mock()
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "get_notification_router", Mock())
    monkeypatch.setattr(transcription, "get_config", lambda: {
        "storage": {"source_files_dir": str(tmp_path / "sources")},
    })
    downloader = Mock(spec=GenericDownloader, supported_extensions={".mp4"})
    monkeypatch.setattr(transcription, "create_downloader", Mock(return_value=downloader))
    task = cache.create_task(url=ARTICLE_URL, platform="generic")

    result = transcription.process_transcription(
        task["task_id"], ARTICLE_URL, include_comments=True,
        transcription_strategy="cloud", preserve_source_file=True,
    )

    assert result["status"] == "success", result
    assert result["data"]["media_type"] == "article"
    fetch.assert_called_once_with(ARTICLE_URL)
    downloader.get_metadata.assert_not_called()
    downloader.get_download_info.assert_not_called()
    queue.put.assert_called_once()
    payload = queue.put.call_args.args[0]
    assert payload["transcript"] == article.text
    assert payload["include_comments"] is False
    saved_task = cache.get_task_by_id(task["task_id"])
    assert saved_task["status"] == "calibrating"
    assert saved_task["platform"] == "web"
    assert article.text in Path(saved_task["source_file_path"]).read_text()
    media_id = URLParser().parse(ARTICLE_URL).video_id
    assert cache.get_cache("web", media_id, False)["transcript_data"] == article.text
    view = {"url": ARTICLE_URL, "platform": "web"}
    _decorate_source_link(view)
    assert view["source_link_label"] == "查看原文"

    retry = cache.create_task(url=ARTICLE_URL, platform="generic")
    retried = transcription.process_transcription(retry["task_id"], ARTICLE_URL)
    assert retried["data"]["cached"] is True
    fetch.assert_called_once()
