from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_focus_studio_contains_lightweight_journal_ui():
    html = (PROJECT_ROOT / "src/web/static/focus-studio.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/focus-studio.css").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "src/web/static/js/focus-journal.js").read_text(encoding="utf-8")
    sw = (PROJECT_ROOT / "src/web/static/service-worker.js").read_text(encoding="utf-8")

    assert 'id="journal-type-select"' in html
    assert 'value="weekly_plan"' in html
    assert 'value="monthly_review"' in html
    assert 'class="journal-shell"' in html
    assert 'id="journal-sidecar"' in html
    assert 'data-journal-open="history"' in html
    assert 'id="journal-sidecar-close"' in html
    assert 'id="journal-history-list"' in html
    assert 'id="journal-review-question"' in html
    assert "/static/js/focus-journal.js" in html

    assert ".journal-dock" in css
    assert ".journal-sidecar" in css
    assert "[data-journal-sidecar] .journal-dock" in css
    assert "[data-journal-sidecar] .focus-deck" in css
    assert ".journal-review-question" in css

    assert "/api/journal/entries" in js
    assert "/api/journal/reviews" in js
    assert "journalSidecar" in js
    assert "togglePanel" in js
    assert "mouseleave" in js
    assert "journal-sidecar-close" in js
    assert "vta_bearer_token" in js
    assert "NO_TOKEN" in js

    assert "/static/js/focus-journal.js" in sw
