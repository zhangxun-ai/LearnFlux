# Reading Toolbar Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the heart-flow reader toolbar to its useful reading controls while keeping background audio easy to switch.

**Architecture:** The reading page remains a static HTML/CSS/JavaScript feature. Remove unsupported toolbar controls from the markup and their dead browser-state code, retain the existing audio panel as a standalone toolbar panel, and add an explicit accessible playback state to that toolbar entry. No FastAPI route, reading repository, parsing process, or preference payload changes.

**Tech Stack:** Static HTML, CSS, vanilla browser JavaScript, pytest static-asset contracts, Node.js for existing reading-flow checks.

---

### Task 1: Define the revised toolbar contract

**Files:**
- Modify: `tests/unit/test_reading_page_contract.py`
- Modify: `src/web/static/reading.html:218-271`
- Modify: `src/web/static/js/reading.js:5-65, 579-613, 720-840`

- [ ] **Step 1: Write failing toolbar-contract tests**

Update the two-page reader contract to require:

```python
assert 'data-reading-panel="sound"' in html
assert 'id="reading-sound-shortcut"' in html
assert 'id="reading-sound-shortcut" type="button" data-reading-panel="sound" aria-pressed="false"' in html
assert 'id="reading-reprocess"' not in html
assert 'id="reading-mode-toggle"' not in html
assert 'data-reading-bookmark' not in html
assert '点击两侧或使用 ← → 翻页' not in html
assert 'aria-label="关闭目录"' in html
assert 'aria-label="关闭搜索"' in html
assert 'aria-label="关闭阅读设置"' in html
assert 'aria-label="关闭背景音"' in html
assert "elements.soundShortcut" in js
assert "elements.soundShortcut.setAttribute('aria-pressed', String(isPlaying))" in js
assert "toggleBookmark" not in js
assert "applyMode" not in js
assert "/reprocess" not in js
```

Replace the existing reprocess-control test with a test that asserts the reader does not expose reprocess from the browser script.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run --extra dev pytest tests/unit/test_reading_page_contract.py -q`

Expected: FAIL because the current reader still contains the PDF reprocess button, mode toggle, bookmark, and lacks the sound shortcut ID/playback ARIA state.

- [ ] **Step 3: Implement the minimal toolbar markup and runtime cleanup**

In `reading.html`:

- Keep return-to-library, table-of-contents, search, sound, and settings controls.
- Give the sound panel trigger `id="reading-sound-shortcut"` and initial `aria-pressed="false"`.
- Remove reprocess, reflow/original mode toggle, and bookmark markup.
- Give each remaining panel close button a contextual accessible name: close table of contents, search, reading settings, or background sound.
- Remove the footer's flip-page instruction. The spread-number element remains the only bottom reader text.

In `reading.js`:

- Remove the corresponding state fields, element lookups, functions, and event listeners.
- Extend `updateAudioUI()` so it sets the sound shortcut's `aria-pressed` value from the audio playback state.
- Call the state synchronizer after loading a saved sound source so a paused source remains unpressed.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `uv run --extra dev pytest tests/unit/test_reading_page_contract.py -q`

Expected: PASS.

### Task 2: Align the reader visual hierarchy and responsive behavior

**Files:**
- Modify: `tests/unit/test_reading_page_contract.py`
- Modify: `src/web/static/css/reading.css:636-752, 1360-1445`

- [ ] **Step 1: Write failing style-contract assertions**

Add static assertions that the CSS no longer contains `.reading-mode-toggle` or original-mode reader selectors, and that it contains an explicit pressed-state treatment for `#reading-sound-shortcut[aria-pressed="true"]`.
Also assert that the spread number is visibly rendered without relying on `:hover`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run --extra dev pytest tests/unit/test_reading_page_contract.py -q`

Expected: FAIL because the legacy mode-toggle and original-mode rules remain and the sound shortcut has no semantic active state treatment.

- [ ] **Step 3: Implement minimal CSS changes**

- Remove legacy mode-toggle and original-mode CSS.
- Add a restrained active state for the sound shortcut based on `aria-pressed="true"`; it must not depend on icon position or mobile-only selectors.
- Update the small-screen toolbar selector only as needed so search, sound, and `Aa` remain available and the centered title continues to truncate.
- Make the existing page-range indicator persistently visible and remove the hover-only rule that controlled it. It is the reader's sole bottom affordance.
- Preserve existing canvas, pagination, panels, theme, and motion-reduction rules.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `uv run --extra dev pytest tests/unit/test_reading_page_contract.py -q`

Expected: PASS.

### Task 3: Verify the delivered reader

**Files:**
- Verify: `src/web/static/reading.html`
- Verify: `src/web/static/css/reading.css`
- Verify: `src/web/static/js/reading.js`
- Verify: `tests/unit/test_reading_page_contract.py`
- Verify: `tests/unit/test_reading_mvp.py`

- [ ] **Step 1: Run focused static and reader tests**

Run: `uv run --extra dev pytest tests/unit/test_reading_page_contract.py tests/unit/test_reading_mvp.py -q`

Expected: PASS.

- [ ] **Step 2: Check JavaScript syntax and the relevant diff**

Run: `node --check src/web/static/js/reading.js && git diff --check && git diff -- src/web/static/reading.html src/web/static/css/reading.css src/web/static/js/reading.js tests/unit/test_reading_page_contract.py`

Expected: no syntax errors, whitespace errors, or unrelated changes.

- [ ] **Step 3: Inspect the running 8000 reader**

Open the existing `http://localhost:8000/reading` service and verify the source includes the revised controls. With a readable document opened, verify directory/search/settings panels still open, audio panel switches an existing track and shows its active state, and no browser-console error appears.

- [ ] **Step 4: Report exact evidence**

Report the tests and browser checks actually performed, together with anything that could not be verified without a user document or token. Do not commit, push, or deploy.
