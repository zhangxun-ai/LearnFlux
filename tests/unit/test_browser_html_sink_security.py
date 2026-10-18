"""Contracts for the remaining browser HTML sinks that accept remote data."""

from pathlib import Path

from video_transcript_api.api.routes.post_insight import build_insight_sections


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_post_insight_labels_server_rendered_rich_html_as_sanitized():
    sections = build_insight_sections(
        "## 洞察\n<img src=x onerror=alert(1)> **safe**"
    )

    assert sections
    assert sections[0]["sanitized_html"] == sections[0]["html"]
    assert "onerror" not in sections[0]["sanitized_html"]
    assert "<strong>safe</strong>" in sections[0]["sanitized_html"]


def test_post_page_only_inserts_explicit_nh3_sanitized_rich_html():
    source = (
        PROJECT_ROOT / "src/web/templates/post_insight.html"
    ).read_text(encoding="utf-8")

    assert "body.innerHTML = sec.sanitized_html || '';" in source
    assert "body.dataset.trustedHtml = 'nh3';" in source
    assert "$('error-message').innerHTML = message" not in source


def test_home_status_messages_use_text_nodes_for_remote_errors():
    source = (
        PROJECT_ROOT / "src/web/static/js/app.js"
    ).read_text(encoding="utf-8")
    status_renderer = source.split("static showStatus", 1)[1].split(
        "static hideStatus", 1
    )[0]

    assert "content.replaceChildren(statusTitle)" in status_renderer
    assert "statusTitle.textContent = String(message || '')" in status_renderer
    assert "detailsElement.textContent = String(details)" in status_renderer
    assert "${message}" not in status_renderer
    assert "${details}" not in status_renderer


def test_transcript_error_message_is_escaped_before_html_status_rendering():
    source = (
        PROJECT_ROOT / "src/web/templates/transcript.html"
    ).read_text(encoding="utf-8")

    assert "escapeHtml(err.message || String(err))" in source
    assert "' + (err.message || String(err)) + '" not in source


def test_remote_links_reject_non_http_schemes_before_entering_href_sinks():
    sources = {
        "flywheel": (PROJECT_ROOT / "src/web/templates/flywheel.html").read_text(encoding="utf-8"),
        "trend": (PROJECT_ROOT / "src/web/static/js/trend-radar.js").read_text(encoding="utf-8"),
        "settings": (PROJECT_ROOT / "src/web/static/settings.html").read_text(encoding="utf-8"),
    }

    for source in sources.values():
        assert "function safeHttpURL" in source
        assert "['http:', 'https:'].includes(parsed.protocol)" in source
    assert "safeHttpURL(d.original_url)" in sources["flywheel"]
    assert "safeHttpURL(c.original_url)" in sources["flywheel"]
    assert "safeHttpURL(o.original_url)" in sources["flywheel"]
    assert "safeHttpURL(row.url)" in sources["trend"]
    assert "safeHttpURL(p.api_key_url)" in sources["settings"]


def test_focus_history_escapes_all_remote_attributes_and_labels():
    source = (
        PROJECT_ROOT / "src/web/static/js/focus-journal.js"
    ).read_text(encoding="utf-8")

    assert "const entryDate = escapeHTML(entry.entry_date);" in source
    assert "const entryType = escapeHTML(entry.entry_type);" in source
    assert "const label = escapeHTML(TYPE_LABELS[entry.entry_type] || entry.entry_type);" in source
