# Unified Media Study Player UI Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a production-shell UI preview for the unified audio/video study player and make it discoverable from existing single-item and collection workflows without changing APIs or data flows.

**Architecture:** Keep the standalone preview page isolated with page-local CSS and JavaScript. Add only three presentation-layer entry points: shared sidebar, completed single-media history card, and completed collection-media source actions. Every entry links to the preview with a `state` query parameter; no real task data is passed, no API is called, and no state is persisted.

**Tech Stack:** Static HTML, CSS, vanilla JavaScript, existing app-shell assets, pytest asset-contract test.

---

## File Structure

- `src/web/static/study-player-preview.html`: preview-only semantic page structure and clearly labeled sample content.
- `src/web/static/css/study-player-preview.css`: preview-only responsive layout and visual states.
- `src/web/static/js/study-player-preview.js`: four-state UI toggles with no network or storage access; exports a pure state-view function for executable checks.
- `src/web/static/js/app-shell.js`: global sidebar discovery entry.
- `src/web/static/index.html`: cache-busted shared-shell loading on the single-item workbench.
- `src/web/static/js/app.js`: completed single-media history entry.
- `src/web/static/collections.html`: collection source action entry element.
- `src/web/static/js/collections.js`: collection source entry visibility.
- `tests/unit/test_study_player_preview_assets.py`: verifies assets, state controls, entry contracts, and no API calls.

### Task 1: Define the Preview Asset Contract

**Files:**
- Create: `tests/unit/test_study_player_preview_assets.py`

- [x] **Step 0: Preserve the verified pre-implementation baseline**

The exact `git status --short` output captured before preview implementation is:

```text
 M server.sh
?? docs/superpowers/plans/2026-07-16-unified-media-study-player-ui-preview.md
?? docs/superpowers/specs/2026-07-16-unified-media-study-player-ui-preview-design.md
?? tests/unit/test_server_script.py
```

Treat `server.sh` and `tests/unit/test_server_script.py` as unrelated user work. Do not edit them. At completion, every status entry not in this baseline must be one of the three preview assets or `tests/unit/test_study_player_preview_assets.py`.

- [x] **Step 1: Write the failing asset test**

Create tests that assert:

```python
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
    for state in ("standalone-video", "standalone-audio", "collection-video", "collection-audio"):
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


def test_preview_does_not_replace_existing_pages():
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "UI 预览" in html
    assert 'href="/view/' not in html
    assert 'href="/study/' not in html
```

Define the executable Node assertions in the test as:

```python
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
"""
```

- [x] **Step 2: Run the test and confirm it fails because preview assets do not exist**

Run: `uv run pytest tests/unit/test_study_player_preview_assets.py -q`

Expected: FAIL on missing preview assets.

### Task 2: Build the Isolated Preview Page

**Files:**
- Create: `src/web/static/study-player-preview.html`
- Create: `src/web/static/css/study-player-preview.css`
- Create: `src/web/static/js/study-player-preview.js`

- [x] **Step 1: Add the page shell**

Build an application-shell page containing:

- A visible `UI 预览` badge and a note that sample content is not real data.
- A preview control with four buttons using `data-preview-state`.
- The existing sidebar/topbar visual structure.
- A title/action area, optional collection selector, media stage, fixed caption bar, transcript panel, and collapsed AI dock.
- Existing project stylesheet links for `editorial.css` and `app-shell.css`.
- No shared production JavaScript; the preview must not load `app-shell.js` or any script that reads/writes application state.

- [x] **Step 2: Add preview-only styles**

Implement:

- A desktop two-column workspace with media left and transcript right.
- A fixed caption strip directly below the media stage.
- Separate video slide and audio cover/waveform presentations.
- Conditional collection context styling.
- Responsive stacking below 980px and no horizontal overflow at 390px.
- `prefers-reduced-motion` handling for transitions.

- [x] **Step 3: Add state-only JavaScript**

Implement a fixed state map:

```javascript
const previewStates = {
  'standalone-video': { collection: false, media: 'video' },
  'standalone-audio': { collection: false, media: 'audio' },
  'collection-video': { collection: true, media: 'video' },
  'collection-audio': { collection: true, media: 'audio' },
};
```

Expose `computePreviewView(stateName)` on `globalThis.StudyPlayerPreview`. It returns deterministic booleans for `showCollection`, `showVideo`, and `showAudio`, plus the selected state. The pytest Node harness must execute this function for all four states and assert those values before the browser implementation exists.

Keep the pure model and browser initialization separate:

```javascript
globalThis.StudyPlayerPreview = { previewStates, computePreviewView };

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', initPreview);
}
```

The CommonJS/Node path must export the pure model without touching `document`. On button click in `initPreview`, pass the button's state through `computePreviewView`, then update `document.body.dataset.previewState`, selected button state, media visibility, type copy, and collection-control visibility. Do not call `fetch`, use storage, or modify URLs.

- [x] **Step 4: Run the asset test**

Run: `uv run pytest tests/unit/test_study_player_preview_assets.py -q`

Expected: all tests PASS.

### Task 3: Verify the Running Preview

**Files:**
- Verify only; no production files should change.

- [x] **Step 1: Check JavaScript syntax and diff hygiene**

Run:

```bash
node --check src/web/static/js/study-player-preview.js
git diff --check
```

Expected: both commands exit 0.

- [x] **Step 2: Verify the live static URL**

Run: `curl -f http://localhost:8000/static/study-player-preview.html`

Expected: HTTP 200 and HTML contains `统一学习播放器`.

- [x] **Step 3: Verify desktop and mobile layout manually**

Open `http://localhost:8000/static/study-player-preview.html` and confirm:

- All four preview states switch.
- Standalone states hide collection controls.
- Collection states show only the compact dropdown.
- Fixed subtitle and transcript are visible together on desktop.
- At 390px width, media, subtitle, transcript, and AI dock stack without horizontal overflow.

- [x] **Step 4: Confirm isolation**

Run:

```bash
git status --short
git diff --exit-code -- src/video_transcript_api src/web/templates src/web/static/study.html src/web/static/css/study.css src/web/static/js/study.js src/web/static/collections.html src/web/static/css/collections.css src/web/static/js/collections.js
```

Expected: compared with the captured baseline, the only new status entries are:

```text
?? src/web/static/study-player-preview.html
?? src/web/static/css/study-player-preview.css
?? src/web/static/js/study-player-preview.js
?? tests/unit/test_study_player_preview_assets.py
```

The second command exits 0. Any other new or modified path fails the isolation check. This explicit baseline comparison distinguishes pre-existing user work from task-local changes across the whole repository.

### Task 4: Integrate Discoverable Entries

**Files:**
- Modify: `src/web/static/js/app-shell.js`
- Modify: `src/web/static/index.html`
- Modify: `src/web/static/js/app.js`
- Modify: `src/web/static/collections.html`
- Modify: `src/web/static/js/collections.js`
- Modify: `src/web/static/study-player-preview.html`
- Modify: `src/web/static/js/study-player-preview.js`
- Modify: `tests/unit/test_study_player_preview_assets.py`

- [x] **Step 1: Write failing entry contract tests**

Assert that the shared shell contains a sidebar link, completed single-media cards render a contextual link, collection source actions expose an element controlled by media/success/token conditions, and the preview resolves a valid `state` query parameter.

- [x] **Step 2: Add the shared and contextual entries**

Add “边播边学” after “图解生成” in the shared sidebar. Render the single-card action only for completed video history with a `view_token`. Render the collection action only for successful sources with a `view_token` and `source_type === 'video'`.

- [x] **Step 3: Honor the requested preview state**

Resolve `?state=standalone-video|standalone-audio|collection-video|collection-audio` with a safe standalone-video fallback. Do not call APIs, use storage, or mutate application data.

- [x] **Step 4: Verify tests and live click paths**

Run the focused pytest file, JavaScript syntax checks, `git diff --check`, and browser-level checks from the existing home page into the preview. Confirm the sidebar entry appears without manual URL input and all existing actions remain present.

No commit is created because the user did not request one.
