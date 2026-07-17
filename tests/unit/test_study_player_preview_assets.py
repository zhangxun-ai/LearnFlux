import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = REPO_ROOT / "src" / "web" / "static"
PREVIEW_HTML = STATIC_ROOT / "study-player-preview.html"
PREVIEW_CSS = STATIC_ROOT / "css" / "study-player-preview.css"
PREVIEW_JS = STATIC_ROOT / "js" / "study-player-preview.js"
APP_SHELL_JS = STATIC_ROOT / "js" / "app-shell.js"
APP_JS = STATIC_ROOT / "js" / "app.js"
COLLECTIONS_HTML = STATIC_ROOT / "collections.html"
COLLECTIONS_JS = STATIC_ROOT / "js" / "collections.js"
INDEX_HTML = STATIC_ROOT / "index.html"

PREVIEW_STATES = (
    "standalone-video",
    "standalone-audio",
    "collection-video",
    "collection-audio",
)

NODE_STATE_ASSERTIONS = r"""
require('./src/web/static/js/study-player-preview.js');
const api = globalThis.StudyPlayerPreview;
const expected = {
  'standalone-video': [false, true, false],
  'standalone-audio': [false, false, true],
  'collection-video': [true, true, false],
  'collection-audio': [true, false, true],
};
for (const [name, values] of Object.entries(expected)) {
  const view = api.computePreviewView(name);
  const actual = [view.showCollection, view.showVideo, view.showAudio];
  if (JSON.stringify(actual) !== JSON.stringify(values)) process.exit(1);
  if (view.selectedState !== name) process.exit(1);
}
if (api.resolveRequestedState('?state=collection-audio') !== 'collection-audio') process.exit(1);
if (api.resolveRequestedState('?state=unknown') !== 'standalone-video') process.exit(1);
if (api.resolveRequestedState('') !== 'standalone-video') process.exit(1);
"""


def test_preview_assets_exist_and_are_linked():
    assert PREVIEW_HTML.exists()
    assert PREVIEW_CSS.exists()
    assert PREVIEW_JS.exists()

    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "/static/css/study-player-preview.css" in html
    assert "/static/js/study-player-preview.js" in html
    assert "/static/js/app-shell.js" not in html


def test_preview_exposes_four_ui_states_without_backend_calls():
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    script = PREVIEW_JS.read_text(encoding="utf-8")

    for state in PREVIEW_STATES:
        assert f'data-preview-state="{state}"' in html
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "localStorage" not in script


def test_preview_state_model_is_executable():
    completed = subprocess.run(
        ["node", "-e", NODE_STATE_ASSERTIONS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_preview_is_clearly_isolated_from_existing_pages():
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "UI 预览" in html
    assert "示例内容" in html
    assert 'href="/view/' not in html
    assert 'href="/study/' not in html


def test_preview_is_not_used_as_the_production_player_entry():
    shell_script = APP_SHELL_JS.read_text(encoding="utf-8")
    preview_html = PREVIEW_HTML.read_text(encoding="utf-8")

    assert "const studyPlayerHref = '/study';" in shell_script
    assert "/static/study-player-preview.html" not in shell_script
    assert "边播边学" in shell_script
    assert 'id="preview-player-nav"' in preview_html
    assert "边播边学" in preview_html


def test_entry_pages_cache_bust_the_shared_shell():
    for page in (INDEX_HTML, COLLECTIONS_HTML):
        html = page.read_text(encoding="utf-8")
        assert '/static/js/app-shell.js?v=__ASSET_VERSION__' in html


def test_completed_single_media_cards_expose_a_contextual_player_entry():
    script = APP_JS.read_text(encoding="utf-8")

    assert "task.study_available && task.study_url" in script
    assert "escapeHtml(task.study_url)" in script
    assert "/static/study-player-preview.html" not in script
    assert ">边播边学</a>" in script


def test_completed_collection_media_sources_expose_a_contextual_player_entry():
    html = COLLECTIONS_HTML.read_text(encoding="utf-8")
    script = COLLECTIONS_JS.read_text(encoding="utf-8")

    assert 'id="open-study-player"' in html
    assert 'href="/study"' in html
    assert "openStudyPlayer: document.getElementById('open-study-player')" in script
    assert "source.study_available" in script
    assert "source.study_url" in script
