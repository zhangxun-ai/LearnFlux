from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = REPO_ROOT / "src" / "web" / "static"
STUDY_HTML = STATIC_ROOT / "study.html"
APP_SHELL_JS = STATIC_ROOT / "js" / "app-shell.js"
APP_JS = STATIC_ROOT / "js" / "app.js"
COLLECTIONS_HTML = STATIC_ROOT / "collections.html"
COLLECTIONS_JS = STATIC_ROOT / "js" / "collections.js"
STUDY_JS = STATIC_ROOT / "js" / "study.js"
VIEWS_PY = REPO_ROOT / "src" / "video_transcript_api" / "api" / "routes" / "views.py"


def test_production_study_routes_cover_library_single_and_collection_modes():
    source = VIEWS_PY.read_text(encoding="utf-8")

    assert '@router.get("/study",' in source
    assert '@router.get("/study/{view_token}",' in source
    assert (
        '@router.get("/study/collections/{collection_id}/sources/{source_id}",'
        in source
    )
    assert '"__PAGE_MODE__"' in source
    assert '"__COLLECTION_ID__"' in source
    assert '"__SOURCE_ID__"' in source


def test_study_asset_version_tracks_player_runtime_changes():
    source = VIEWS_PY.read_text(encoding="utf-8")

    assert 'static_dir / "js" / "study-player-runtime.js"' in source
    assert "f.stat().st_mtime_ns for f in asset_files" in source


def test_production_navigation_targets_real_study_picker():
    shell = APP_SHELL_JS.read_text(encoding="utf-8")
    history = APP_JS.read_text(encoding="utf-8")
    collections_html = COLLECTIONS_HTML.read_text(encoding="utf-8")
    collections_js = COLLECTIONS_JS.read_text(encoding="utf-8")

    assert "const studyPlayerHref = '/study';" in shell
    assert "task.study_available" in history
    assert "task.study_url" in history
    assert 'id="open-study-player"' in collections_html
    assert "source.study_available" in collections_js
    assert "source.study_url" in collections_js
    assert "open-study-preview" not in collections_html


def test_study_page_has_distinct_picker_and_player_roots():
    html = STUDY_HTML.read_text(encoding="utf-8")

    assert 'id="study-library"' in html
    assert 'id="study-player"' in html
    assert "window.STUDY_PAGE_MODE = '__PAGE_MODE__';" in html
    assert "window.STUDY_COLLECTION_ID = '__COLLECTION_ID__';" in html
    assert "window.STUDY_SOURCE_ID = '__SOURCE_ID__';" in html


def test_study_picker_and_player_use_real_production_controls():
    html = STUDY_HTML.read_text(encoding="utf-8")
    javascript = STUDY_JS.read_text(encoding="utf-8")

    for marker in (
        'data-library-kind="single"',
        'data-library-kind="collection"',
        'id="study-library-search"',
        'id="study-single-file"',
        'id="study-collection-folder"',
        'id="study-collection-files"',
        'id="study-collection-select"',
        'id="current-caption"',
    ):
        assert marker in html

    assert "/api/study/library?kind=" in javascript
    assert "URL.createObjectURL(file)" in javascript
    assert "URL.revokeObjectURL(state.localObjectUrl)" in javascript
    assert "function studyApiBase()" in javascript
    assert "`${studyApiBase()}/ai-chat`" in javascript
    assert "`${studyApiBase()}/export/markdown`" in javascript
    assert "acceptedMediaFiles" in javascript
    assert "localeCompare" in javascript
    assert "els.aiOverview.innerHTML = overviewHtml" in javascript
    assert "els.aiReadingContent.innerHTML = overviewHtml" in javascript


def test_entry_pages_cache_bust_the_shared_shell():
    for page in (STATIC_ROOT / "index.html", COLLECTIONS_HTML):
        html = page.read_text(encoding="utf-8")
        assert '/static/js/app-shell.js?v=__ASSET_VERSION__' in html


def test_completed_single_media_cards_expose_a_contextual_player_entry():
    script = APP_JS.read_text(encoding="utf-8")

    assert "task.study_available && task.study_url" in script
    assert "escapeHtml(task.study_url)" in script
    assert ">边播边学</a>" in script


def test_completed_collection_media_sources_expose_a_contextual_player_entry():
    html = COLLECTIONS_HTML.read_text(encoding="utf-8")
    script = COLLECTIONS_JS.read_text(encoding="utf-8")

    assert 'id="open-study-player"' in html
    assert 'href="/study"' in html
    assert "openStudyPlayer: document.getElementById('open-study-player')" in script
    assert "source.study_available" in script
    assert "source.study_url" in script
