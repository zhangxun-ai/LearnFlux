import json
import subprocess
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


def test_study_asset_version_tracks_player_runtime_changes(tmp_path, monkeypatch):
    from video_transcript_api.api.routes import views

    (tmp_path / "study.html").write_text(
        '<script src="/static/js/study-player-runtime.js?v=__ASSET_VERSION__"></script>'
    )
    runtime = tmp_path / "js/study-player-runtime.js"
    runtime.parent.mkdir()
    runtime.write_text("const version = 1;")
    monkeypatch.setattr(views, "static_dir", tmp_path)
    before = views._render_study_page(page_mode="library").body
    runtime.write_text("const version = 2;")
    after = views._render_study_page(page_mode="library").body
    assert before != after
    assert b"__ASSET_VERSION__" not in before + after


def test_production_navigation_targets_real_study_picker():
    shell = APP_SHELL_JS.read_text(encoding="utf-8")
    navigation = json.loads(
        (REPO_ROOT / "src/web/product-navigation.json").read_text(encoding="utf-8")
    )
    history = APP_JS.read_text(encoding="utf-8")
    collections_html = COLLECTIONS_HTML.read_text(encoding="utf-8")
    collections_js = COLLECTIONS_JS.read_text(encoding="utf-8")

    assert navigation["items"]["study_player"]["href"] == "/study"
    assert "replaceChildren" not in shell
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


def test_collection_player_action_follows_source_availability():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('    function renderStudyPlayerAction(source) {');
const end = source.indexOf('    function renderSourceSummaryAction(', start);
const classes = new Set();
const link = {href: '', classList: {toggle(name, on) {if (on) classes.add(name); else classes.delete(name);}}};
const context = {els: {openStudyPlayer: link}};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
for (const item of [null, {study_available: false, study_url: '/study/not-ready'}]) {
    context.renderStudyPlayerAction(item);
    assert.equal(link.href, '/study');
    assert.equal(classes.has('hidden'), true);
}
context.renderStudyPlayerAction({study_available: true, study_url: '/study/collections/demo/sources/lesson-1'});
assert.equal(link.href, '/study/collections/demo/sources/lesson-1');
assert.equal(classes.has('hidden'), false);
"""
    result = subprocess.run(
        ["node", "-e", script, str(COLLECTIONS_JS)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
