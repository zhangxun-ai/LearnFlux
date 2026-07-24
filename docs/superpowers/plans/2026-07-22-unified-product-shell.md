# LearnFlux Unified Product Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Directly unify the existing LearnFlux production pages around the approved brand-cool A+ sidebar, shared design tokens, and code-level UI feature switches without changing backend API behavior.

**Architecture:** Keep the current server-rendered/Jinja/static HTML stack and preserve every business DOM/API contract. Add one static UI-feature configuration, make the existing HTML navigation the progressively enhanced baseline, centralize all shell behavior in `app-shell.js`, and make `app-shell.css` plus `product-linear*.css` the only owners of global shell and product visual vocabulary. Existing product pages are edited in place; no prototype or template page is created.

**Tech Stack:** HTML, scoped CSS custom properties, vanilla JavaScript, Jinja2, pytest static-contract tests, Node-based DOM behavior tests, browser computed-style and responsive checks.

**Execution note:** The worktree already contains user-owned changes in the target UI files. Apply surgical patches, inspect each diff, and do not commit, push, or deploy without explicit authorization.

---

## File map and ownership

- Create `src/web/static/js/ui-features.js`: the only `true / false` UI-entry configuration; `trend_radar` defaults to `false`.
- Create `src/web/product-navigation.json`: the only navigation group/item/icon/route/feature definition.
- Create `src/web/templates/partials/product_navigation.html`: generated shared Jinja partial consumed by both `base.html` and `flywheel.html`.
- Create `scripts/sync_product_navigation.py`: deterministic generator that writes the Jinja partial and rewrites marked navigation blocks in static HTML and `views.py::_HOME_HTML`, with per-target active-state rendering. It also stamps direct-static shell/config references with deterministic content hashes.
- Modify `src/web/static/js/app-shell.js`: active-route fallback, UI-feature filtering, group collapse, 280/72 desktop modes, mobile drawer, focus management, persistence migration, dynamic-entry observer.
- Modify `src/web/static/css/app-shell.css`: the only owner of sidebar/topbar/navigation/brand/drawer geometry and state styling.
- Modify `src/web/static/css/product-linear.css`: the brand-cool light/dark token source and shared product component vocabulary; it must not redefine shell geometry.
- Modify `src/web/static/css/editorial.css`: compatibility tokens only; remove competing shell/product ownership.
- Modify `src/web/static/css/trend-radar.css`: scope naked element rules to the trend content root so they cannot leak into the shell.
- Modify `src/web/static/css/styles.css`, `workbench.css`, `collections.css`, `study.css`, `visual-learning.css`, `focus-studio.css`, `reading.css`, `trend-radar.css`, and `floating-toc.css` only where global selectors can reach shared shell elements; scope those rules under the owning page/content root.
- Modify `src/web/static/css/product-linear-core.css`, `product-linear-insights.css`, `product-linear-system.css`, `home-linear.css`: page-content adapters only; remove shell overrides and normalize page backgrounds/components.
- Modify existing production HTML/Jinja files in place: `index.html`, `collections.html`, `study.html`, `visual-learning.html`, `focus-studio.html`, `reading.html`, `trend-radar.html`, `history.html`, `settings.html`, `templates/base.html`, and `templates/flywheel.html`. Add feature markers, collapsible group controls, consistent script order and ARIA without changing business IDs.
- Modify existing Jinja content templates in place: `templates/post_insight.html`, `transcript.html`, `processing.html`, `error.html`, and `cleaned.html`; preserve their business IDs/blocks and remove only conflicting late inline visual overrides.
- Modify `src/video_transcript_api/api/routes/views.py`: synchronize the real `/` shell/navigation and add `ui-features.js` to the existing `/add_task_by_web` and study asset-version lists; do not change route/API behavior.
- Modify `src/video_transcript_api/api/routes/reading.py`: add the existing HTML response to the shared asset-version replacement pattern, without changing reading API behavior.
- Modify `src/video_transcript_api/api/context.py`, `api/routes/collections.py`, `api/routes/settings.py`, `api/routes/trend_radar.py`, and `api/routes/visual_learning.py`: add the configuration/navigation resources to their existing version-file lists only.
- Modify `src/web/static/service-worker.js`: version/cache `ui-features.js` and invalidate the old cache once; do not add feature gates or change API behavior.
- Create `tests/unit/test_unified_product_shell.py`: cross-page markup, token, feature-config and progressive-enhancement contracts.
- Create `tests/features/test_unified_product_shell_browser.py`: repeatable Playwright checks against a running local production app; installed ephemerally with `uv run --with` so `pyproject.toml` and `uv.lock` remain untouched.
- Modify directly conflicting legacy assertions in `tests/unit/test_reading_page_contract.py`, `test_product_linear_ui.py`, `test_app_shell_noise.py`, and `test_home_page.py` to describe the new shell rather than the removed JS navigation reconstruction.

### Task 1: Lock the cross-page and UI-feature contracts

**Files:**
- Create: `tests/unit/test_unified_product_shell.py`
- Modify: `tests/unit/test_reading_page_contract.py`
- Modify: `tests/unit/test_product_linear_ui.py`

- [ ] **Step 1: Write failing static contracts**

Add tests that enumerate every production shell source and assert:

```python
OPTIONAL_FEATURES = {
    "collections", "visual_learning", "study_player", "reading",
    "focus_studio", "post_insight", "trend_radar", "flywheel", "history",
}

assert '/static/js/ui-features.js?v=' in html
assert html.index('ui-features.js') < html.index('app-shell.js')
assert 'data-feature="trend_radar"' in html
assert re.search(r'data-feature="trend_radar"[^>]*\shidden(?:\s|>)', html)
```

Also assert shared nav labels/hrefs/order, SVG-only icons, group button ARIA, a 44px interaction target, no page adapter shell selectors, exact brand-cool tokens, and preservation of the current favicon/logo asset paths. Organize the file into independently selectable classes: `TestFeatureConfig`, `TestNavigationMarkup`, `TestShellBehaviorSource`, `TestProductTokens`, `TestCssOwnership`, and `TestAssetVersions` so each TDD phase can run only the contracts it is making green.

Add generator contracts that load `src/web/product-navigation.json`, run `scripts/sync_product_navigation.py --check`, and compare every marked output block. Include `src/video_transcript_api/api/routes/views.py::_HOME_HTML` and the `/` route in the inventory.

- [ ] **Step 2: Write failing JavaScript contracts**

Use Node subprocess tests to load `ui-features.js` and `app-shell.js`, then verify strict boolean behavior, invalid/missing fail-closed behavior, old `expanded/collapsed` state migration, group preference preservation, active-route matching, and dynamically inserted feature nodes.

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
uv run --extra dev pytest tests/unit/test_unified_product_shell.py tests/unit/test_reading_page_contract.py tests/unit/test_product_linear_ui.py -q
```

Expected: failures for missing `ui-features.js`, old navigation reconstruction, missing feature markers/group buttons, and token/shell ownership drift.

### Task 2: Add the code-level UI feature configuration

**Files:**
- Create: `src/web/static/js/ui-features.js`
- Modify: `src/web/static/js/app-shell.js`
- Modify: `src/web/static/service-worker.js`
- Modify: `src/video_transcript_api/api/context.py`
- Modify: `src/video_transcript_api/api/routes/views.py`
- Modify: `src/video_transcript_api/api/routes/collections.py`
- Modify: `src/video_transcript_api/api/routes/settings.py`
- Modify: `src/video_transcript_api/api/routes/trend_radar.py`
- Modify: `src/video_transcript_api/api/routes/visual_learning.py`
- Modify: `src/video_transcript_api/api/routes/reading.py`

- [ ] **Step 1: Implement the frozen boolean map**

Create the approved nine-key object with `trend_radar: false` and the other values `true`. Export through `module.exports` when loaded by Node tests and assign the same frozen object to `window.LEARNFLUX_UI_FEATURES` in browsers.

- [ ] **Step 2: Implement one visibility handler**

Add an exported strict predicate and `applyFeatureVisibility(root)` function. Only remove `hidden` when the configured value is exactly `true`; otherwise set `hidden`. Do not access localStorage or call any API.

- [ ] **Step 3: Cover dynamic entries**

Install one `MutationObserver` on `.main-area` (or `body` fallback) after the initial scan. Process only added nodes and their `[data-feature]` descendants; business scripts only add `data-feature` and `hidden`.

- [ ] **Step 4: Version the configuration resource everywhere**

Add `ui-features.js`, and the canonical navigation file where route mtime calculation needs it, to every existing `asset_files`/`version_files` list serving a shell page. Add `__ASSET_VERSION__` replacement to the existing `/reading` HTML response. For `/static/focus-studio.html` and `/static/history.html`, which bypass route replacement, make the sync script stamp `ui-features.js` and shared shell asset query strings with a deterministic 12-character SHA-256 digest; `--check` fails when the stamped value is stale. Apply the same deterministic stamp to `_HOME_HTML` only if it remains outside a route replacement path. Replace hard-coded `20260712`, `20260722-blue`, small integers and unversioned shared-shell references with the appropriate dynamic or deterministic mechanism. Add `ui-features.js` to the service-worker static resource set and bump the cache name once. Do not change navigation/API fetch behavior.

- [ ] **Step 5: Run focused feature tests and confirm GREEN**

Run `pytest tests/unit/test_unified_product_shell.py::TestFeatureConfig -q`. Expect feature-config tests to pass while navigation, asset-version and token classes remain red; deterministic static stamping is intentionally implemented in Task 3 with the sync script.

### Task 3: Convert the existing sidebar to the A+ interaction model

**Files:**
- Modify: `src/web/static/js/app-shell.js`
- Modify: `src/web/static/css/app-shell.css`
- Modify in place: all production HTML/Jinja shell sources listed in the file map
- Create: `src/web/product-navigation.json`
- Create: `scripts/sync_product_navigation.py`
- Create: `src/web/templates/partials/product_navigation.html`
- Modify: `src/video_transcript_api/api/routes/views.py`

- [ ] **Step 1: Establish one navigation source**

Move group labels, item labels, hrefs, aliases, SVG path markup and feature IDs into `src/web/product-navigation.json`. Generate `templates/partials/product_navigation.html` once from that data and replace the duplicated blocks in `base.html` and `flywheel.html` with `{% include "partials/product_navigation.html" %}`. Add `<!-- PRODUCT_NAV_START -->` / `<!-- PRODUCT_NAV_END -->` markers to each static production shell and to the `_HOME_HTML` string. Implement `scripts/sync_product_navigation.py` with an explicit target map for static active IDs and `_HOME_HTML`; `--check` exits non-zero on partial/output/hash drift. Run it once to update the existing product files in place.

- [ ] **Step 2: Stop rebuilding navigation**

Remove `NAV_GROUPS` DOM reconstruction and make active-route reconciliation annotate the existing links only. Preserve the HTML SVG icons and accessible names.

- [ ] **Step 3: Mark optional entries and load config first**

Add `data-feature` plus baseline `hidden` to every optional nav/home/shortcut entry. Add versioned `ui-features.js` before `app-shell.js` in every production source. Leave single-task and settings core links unhidden.

- [ ] **Step 4: Make groups real controls**

Replace each passive group heading with a 44px button containing label, current-group indicator and chevron, with `aria-expanded` and `aria-controls`. Keep group contents in stable containers; hidden groups must leave the tab order.

- [ ] **Step 5: Implement state and accessibility behavior**

Persist `{mode, groups}` in `vta_app_shell_sidebar`; migrate legacy strings; respect explicit `false`; use 280px expanded/72px rail; show all enabled links in rail; add tooltips for hover/focus; make mobile a `min(86vw, 320px)` focus-managed drawer; restore focus and close with Escape/overlay/link.

- [ ] **Step 6: Preserve no-JS access**

Only apply off-canvas mobile rules under `html.shell-enhanced`; without script, core navigation stays in normal document flow and optional entries remain fail-closed.

- [ ] **Step 7: Run shell behavior tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_unified_product_shell.py::TestNavigationMarkup tests/unit/test_unified_product_shell.py::TestShellBehaviorSource tests/unit/test_app_shell_noise.py tests/unit/test_reading_page_contract.py -q
```

Then run `pytest tests/unit/test_unified_product_shell.py::TestAssetVersions -q` after the sync script has stamped direct-static files. Expected: sidebar behavior, markup, mobile baseline, accessibility and asset-version contracts pass.

### Task 4: Install the brand-cool token system and remove shell overrides

**Files:**
- Modify: `src/web/static/css/product-linear.css`
- Modify: `src/web/static/css/app-shell.css`
- Modify: `src/web/static/css/home-linear.css`
- Modify: `src/web/static/css/product-linear-core.css`
- Modify: `src/web/static/css/product-linear-insights.css`
- Modify: `src/web/static/css/product-linear-system.css`
- Modify: `src/web/static/css/editorial.css`
- Modify: `src/web/static/css/trend-radar.css`
- Modify as required for boundary leaks: `src/web/static/css/styles.css`, `workbench.css`, `collections.css`, `study.css`, `visual-learning.css`, `focus-studio.css`, `reading.css`, and `floating-toc.css`

- [ ] **Step 1: Replace the light/dark token values**

Implement the approved cool-neutral palette (`#F6F8FB`, `#EEF2F7`, `#FFFFFF`, `#172033`, `#596579`, `#2868D8`) and complete dark/semantic/on-accent pairs from the design spec.

- [ ] **Step 2: Give shell geometry one owner**

Remove sidebar/nav/brand/topbar selectors from `editorial.css`, `product-linear.css`, `home-linear.css` and page adapters. Audit every listed feature CSS file; scope global element or `body` rules under its owning page/content root when they can match shell descendants, while leaving intentional global resets only in `editorial.css`/`app-shell.css`. Map product tokens into shell variables, but keep all shell dimensions, typography, states and transitions in `app-shell.css`.

- [ ] **Step 3: Normalize product components**

Use one 8px spacing rhythm, 8px controls, 12px–16px surfaces, restrained borders/shadows, fixed product type scale, 44px controls, visible focus and 180ms ease-out motion. Remove page-level warm, purple or glass shell styling and banned wide border-plus-shadow decoration.

- [ ] **Step 4: Keep the existing brand assets**

Use the existing icon/logo files with `object-fit: contain`; expanded sidebar shows mark + `LearnFlux`, rail shows the mark. Do not edit or generate image assets.

- [ ] **Step 5: Restamp changed shared assets**

Run `python scripts/sync_product_navigation.py` after the final CSS/JS edits, then `python scripts/sync_product_navigation.py --check`; this refreshes the direct-static SHA query strings invalidated by Task 4.

- [ ] **Step 6: Run CSS ownership and contrast contracts**

Run `pytest tests/unit/test_unified_product_shell.py::TestProductTokens tests/unit/test_unified_product_shell.py::TestCssOwnership tests/unit/test_product_linear_ui.py tests/unit/test_home_workbench_accessibility.py -q` and expect token, selector-scope and interaction-size assertions to pass.

### Task 5: Converge the actual product pages by archetype

**Files:**
- Modify existing page-content adapters and, only where required, the existing product HTML/Jinja files listed in the file map
- Modify: `src/web/templates/post_insight.html`
- Modify: `src/web/templates/transcript.html`
- Modify: `src/web/templates/processing.html`
- Modify: `src/web/templates/error.html`
- Modify: `src/web/templates/cleaned.html`
- Preserve all business IDs asserted in `tests/unit/test_product_linear_ui.py`

- [ ] **Step 1: Core workspaces**

Normalize collections, study, visual learning, focus writing and reading around the same page background, heading scale, controls, surfaces and state colors. Keep focus atmosphere inside its canvas; never recolor the shared shell.

- [ ] **Step 2: Insight workspaces**

Normalize post insight, trend radar and flywheel metrics/forms/panels without changing their data visualization semantics. Scope every rule below the page class/content root.

- [ ] **Step 3: System and result pages**

Normalize history, settings, result, processing, error and cleaned views around the same toolbar, form, card and status vocabulary.

- [ ] **Step 4: Run focused page-contract tests**

Run:

```bash
uv run --extra dev pytest tests/unit/test_product_linear_ui.py tests/unit/test_home_page.py tests/unit/test_reading_page_contract.py tests/unit/test_study_production_assets.py tests/unit/test_visual_learning_page.py tests/unit/test_trend_radar_ui.py -q
```

Expected: all existing business anchors and the new visual contracts pass.

### Task 6: Real-route browser and regression verification

**Files:**
- Modify only defects found by verification in the already listed production files
- Create: `tests/features/test_unified_product_shell_browser.py`
- Write verification artifacts: `docs/superpowers/reports/unified-product-shell/` (JSON computed-style results and route screenshots only; no HTML/template artifacts)

- [ ] **Step 1: Run the complete focused unit slice**

Run all shell/product UI unit files plus any route asset-version tests. Record exact pass/fail totals; do not conceal unrelated existing failures.

- [ ] **Step 2: Add and run the repeatable browser contract**

Create a data-driven Playwright test with route/viewport/theme/state matrices. For each of the nine feature IDs, use Playwright request routing to fulfill `/static/js/ui-features.js` with an in-memory configuration where that feature is first `false` and then `true`; reload without editing the worktree and assert every matching entry hides then returns. In both configurations, insert a dynamic `[data-feature][hidden]` link after load and assert the observer result. Also assert computed shell styles, 44×44 targets, drawer/focus/Escape behavior, group persistence, old-state migration, no horizontal overflow, no-JS core navigation, the default `trend_radar: false`, direct `/trend-radar` response unchanged, and the existing API response status before/after UI-only overrides.

Add a PWA upgrade case: establish a controlled page, create an old-named cache containing a stale `ui-features.js` response, install/activate the current `/service-worker.js`, wait for `controllerchange`, then assert the old cache is removed and the next config request has the current content/version. Save screenshots and a JSON computed-style/cache report under `docs/superpowers/reports/unified-product-shell/` only on the verification run.

Run the app and test in two terminals:

```bash
uv run uvicorn video_transcript_api.api.server:app --host 127.0.0.1 --port 8765
uv run --with pytest --with playwright python -m playwright install chromium
LEARNFLUX_TEST_BASE_URL=http://127.0.0.1:8765 uv run --with pytest --with playwright pytest tests/features/test_unified_product_shell_browser.py -q
```

Expected: all matrix cases pass. If the environment cannot download Chromium, use the already connected in-app browser for equivalent assertions, record that fallback explicitly, and do not claim the repeatable test passed.

- [ ] **Step 3: Inspect real production routes**

At 1440×1000, 1024×768 and 390×844, verify `/`, `/add_task_by_web`, `/collections`, `/study`, `/visual-learning`, `/reading`, `/static/focus-studio.html`, `/post`, `/flywheel`, `/static/history.html`, `/settings` and a representative result page. Verify light/dark, expanded/rail, group collapse, mobile drawer, focus order and overflow. `trend_radar` must be absent from all discoverable UI because its code setting is `false`, while direct `/trend-radar` remains unchanged.

- [ ] **Step 4: Compare computed shell styles across routes**

Capture the computed background, width, font size, line height, padding, icon size and active state of shared shell elements. Assert equality at the same theme/viewport instead of relying only on screenshots.

- [ ] **Step 5: Run accessibility and reduced-motion checks**

Keyboard-operate every control, verify focus return, 44×44 targets, WCAG AA color pairs, 200% text zoom, reduced motion and no horizontal overflow.

- [ ] **Step 6: Inspect the final diff and report**

Confirm no backend API behavior changed, no image asset changed, no prototype/template page was added, and only in-scope user-modified lines were touched. Report exact test/browser evidence and remaining limitations. Do not commit or deploy.
