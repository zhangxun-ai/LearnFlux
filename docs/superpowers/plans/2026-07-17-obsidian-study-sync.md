# Obsidian Study Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, one-click synchronization of one transcript and one continuously editable Markdown note per Study item into a locally configured Obsidian Vault, with collection-level inheritance, single-item bindings, and lossless conflict handling.

**Architecture:** Add a focused `obsidian` package for Vault paths, Markdown/frontmatter, sync state, and filesystem writes. Extend the Study repository with stable note-document, binding, and per-source sync records; expose context-specific authenticated APIs through existing Study routes; add one Markdown note editor and binding/conflict dialogs to the existing Study page. All filesystem tests use temporary Vaults.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest, vanilla JavaScript/HTML/CSS, Markdown/YAML-compatible frontmatter.

---

## File structure

- Create `src/video_transcript_api/obsidian/__init__.py`: public sync types and service exports.
- Create `src/video_transcript_api/obsidian/markdown.py`: frontmatter parsing/merging and transcript/note rendering.
- Create `src/video_transcript_api/obsidian/paths.py`: Vault containment, directory listing/creation, safe filenames, identity lookup, and atomic writes.
- Create `src/video_transcript_api/obsidian/service.py`: binding resolution, note reconciliation, conflict state machine, and one-click sync orchestration.
- Modify `src/video_transcript_api/study/repository.py`: schema/migrations and CRUD for note documents, bindings, and sync state.
- Modify `src/video_transcript_api/study/service.py`: stable Study context and legacy-note migration integration.
- Create `src/video_transcript_api/api/routes/obsidian.py`: Vault status and safe relative-directory APIs under `/api/obsidian`.
- Modify `src/video_transcript_api/api/app.py`: mount the independent Obsidian router.
- Modify `src/video_transcript_api/api/routes/study.py`: note, binding, directory, sync, and conflict APIs with existing ownership gates.
- Modify `src/web/static/study.html`: note tab, binding dialog, and conflict dialog.
- Modify `src/web/static/js/study.js`: note draft lifecycle, autosave, binding selection, sync, and conflict actions.
- Modify `src/web/static/css/study.css`: accessible note editor and dialogs using existing design tokens.
- Modify `config/config.example.jsonc`: generic Obsidian config keys without the user's path.
- Modify local ignored `config/config.jsonc`: enable the provided Vault only after tests pass; never stage or print its secrets.
- Create `tests/unit/test_obsidian_paths.py`, `tests/unit/test_obsidian_markdown.py`, `tests/unit/test_obsidian_sync.py`.
- Extend `tests/unit/test_study_repository.py`, `tests/unit/test_study_routes.py`, `tests/unit/test_study_frontend_assets.py`.

No commit step is included because repository instructions require explicit commit authorization.

### Task 1: Stable Study note documents and sync persistence

**Files:**
- Modify: `src/video_transcript_api/study/repository.py`
- Modify: `src/video_transcript_api/study/service.py`
- Test: `tests/unit/test_study_repository.py`
- Test: `tests/unit/test_study_service.py`

- [ ] **Step 1: Write failing repository tests**

Cover stable context keys, one note document per collection source across `view_token` changes, independent single-item documents, optimistic revision conflicts, binding inheritance, binding revision conflicts, per-source sync state, and binding-change state reset.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --extra dev pytest tests/unit/test_study_repository.py tests/unit/test_study_service.py -q
```

Expected: failures because note-document/binding/sync APIs do not exist.

- [ ] **Step 3: Implement schema and CRUD minimally**

Add `study_note_documents`, `obsidian_bindings`, and `obsidian_source_sync` migrations and methods. Use one shared helper whose exact stable keys are:

```python
def build_study_context_key(view_token: str, collection_id: str = "", source_id: str = "") -> str:
    if collection_id and source_id:
        return _length_encoded("collection", collection_id, source_id)
    return _length_encoded("single", view_token)
```

Implement optimistic `revision` checks without changing existing note CRUD.

- [ ] **Step 4: Add legacy note migration behavior**

For an absent note document, aggregate existing rows with the exact ordering and owner rules from the spec. Preserve legacy rows.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Task 1 command and require zero failures.

### Task 2: Vault path and Markdown primitives

**Files:**
- Create: `src/video_transcript_api/obsidian/__init__.py`
- Create: `src/video_transcript_api/obsidian/paths.py`
- Create: `src/video_transcript_api/obsidian/markdown.py`
- Test: `tests/unit/test_obsidian_paths.py`
- Test: `tests/unit/test_obsidian_markdown.py`

- [ ] **Step 1: Write failing path tests**

Cover relative-path validation, traversal rejection, absolute-path rejection, symlink escape rejection, dot-directory filtering, explicit directory creation, Unicode safe filenames, same-name collision suffixes, stable identity lookup, zero/one/multiple matches, and same-directory atomic replace.

- [ ] **Step 2: Run path tests and verify RED**

```bash
uv run --extra dev pytest tests/unit/test_obsidian_paths.py -q
```

Expected: import failure for the new package.

- [ ] **Step 3: Implement minimal path primitives**

All public functions accept a configured Vault root plus relative paths. Resolve real paths and verify containment after following symlinks. Atomic writes use a temporary file in the target directory followed by `os.replace`.

- [ ] **Step 4: Run path tests and verify GREEN**

- [ ] **Step 5: Write failing Markdown tests**

Cover transcript rendering, managed identities for single/collection contexts, no-timestamp fallback, note-body extraction, empty note bodies, user `tags`/`aliases` preservation, managed-field updates, malformed frontmatter handling, and hashes that exclude `synced_at`.

- [ ] **Step 6: Run Markdown tests and verify RED**

```bash
uv run --extra dev pytest tests/unit/test_obsidian_markdown.py -q
```

- [ ] **Step 7: Implement minimal Markdown helpers and verify GREEN**

Avoid a new YAML dependency unless the existing environment already provides a safe parser. If a parser is available, use safe-load/safe-dump; otherwise implement only the restricted frontmatter forms required and reject unsupported malformed content rather than silently rewriting it.

### Task 3: Reconciliation and one-click sync service

**Files:**
- Create: `src/video_transcript_api/obsidian/service.py`
- Modify: `src/video_transcript_api/obsidian/__init__.py`
- Test: `tests/unit/test_obsidian_sync.py`

- [ ] **Step 1: Write the conflict-state tests first**

Cover clean, app-only dirty, Obsidian-only dirty, converged, dual conflict, first sync, existing empty file, newly empty draft, clearing an existing file, external deletion, and stale conflict preconditions.

For `external_deleted`, explicitly cover both permitted resolutions: recreate the note from the current app body, or accept deletion without converting absence into an empty file.

- [ ] **Step 2: Run and verify RED**

```bash
uv run --extra dev pytest tests/unit/test_obsidian_sync.py -q
```

- [ ] **Step 3: Implement reconciliation minimally**

Represent file absence separately from the empty-body hash. Recover identity paths before reading file content. Use a per-context lock and re-read database revision, Obsidian hash, and baseline during conflict resolution.

Implement the two external-deletion transitions independently from ordinary dual-conflict resolution: `recreate_from_app` preserves the app body, allocates/writes the note in the current binding directory, and refreshes path/body/file baselines; `accept_external_deletion` explicitly clears the database note body, note file path, note body baseline, and note managed-file hash without creating a file. Both require the same stale preconditions and per-context lock as other resolutions.

- [ ] **Step 4: Add failing end-to-end service tests**

Use `tmp_path` Vaults for collection inheritance, single binding, same view in different collections, stable collection source after retry, idempotent repeated sync, external rename recovery, unknown same-name file protection, partial write status, and retry convergence.

- [ ] **Step 5: Implement one-click sync and verify GREEN**

Prepare both rendered files before replacing either. Persist each successful file state immediately. Return HTTP-neutral result objects with `overall` plus `created|updated|unchanged|skipped_empty|failed` per file so the route layer can map 200/207/500.

### Task 4: Authenticated FastAPI integration

**Files:**
- Create: `src/video_transcript_api/api/routes/obsidian.py`
- Modify: `src/video_transcript_api/api/app.py`
- Modify: `src/video_transcript_api/api/routes/study.py`
- Modify: `src/video_transcript_api/api/context.py` only if dependency construction requires it
- Test: `tests/unit/test_study_routes.py`
- Test: `tests/unit/test_study_collection_context.py`

- [ ] **Step 1: Run GitNexus context/impact before shared route changes**

Inspect `get_study_service`, `_require_owned_single`, `_get_owned_collection_context`, and Study route consumers.

- [ ] **Step 2: Write failing route tests**

Cover `GET /api/obsidian/status`, directory listing restrictions, note GET/PUT, single/collection binding scope, sync response status mapping, 409 conflict payloads, stale ordinary-conflict resolution, both external-deletion resolution actions, 401 authentication, 404 cross-owner access, and no absolute Vault path leakage. Route-test app factories must mount both `study.router` and `obsidian.router` when exercising global endpoints.

- [ ] **Step 3: Run and verify RED**

```bash
uv run --extra dev pytest tests/unit/test_study_routes.py tests/unit/test_study_collection_context.py -q
```

- [ ] **Step 4: Add request/response models and service dependencies**

Create an independent `APIRouter(prefix="/api/obsidian")` for status and directory APIs and mount it from `api/app.py`; keep single and collection note/binding/sync APIs under their context-specific Study routes from the spec. Reuse existing authentication and ownership checks before all service calls.

- [ ] **Step 5: Run focused route tests and verify GREEN**

### Task 5: Study note editor, binding, and conflict UI

**Files:**
- Modify: `src/web/static/study.html`
- Modify: `src/web/static/js/study.js`
- Modify: `src/web/static/css/study.css`
- Test: `tests/unit/test_study_frontend_assets.py`
- Test: `tests/unit/test_study_player_runtime.py` only for extracted pure helpers

- [ ] **Step 1: Read and apply the `ui-styling` skill before UI edits**

- [ ] **Step 2: Write failing asset/behavior tests**

Assert the note tab, editor, save/sync states, binding dialog, transcript/note directory controls, conflict choices, and current context-specific API construction.

- [ ] **Step 3: Run and verify RED**

```bash
uv run --extra dev pytest tests/unit/test_study_frontend_assets.py tests/unit/test_study_player_runtime.py -q
```

- [ ] **Step 4: Implement the minimal accessible UI**

Add a Markdown textarea with debounced optimistic autosave, visible state text, one sync button, binding dialog, and conflict dialog. Do not add timestamp-linked notes or a second note model.

- [ ] **Step 5: Implement front-end state transitions**

Load the note on each session/source change, cancel stale requests, save with revision, load binding only when needed, map 207 partial results, and require explicit conflict choices.

- [ ] **Step 6: Run frontend tests and verify GREEN**

### Task 6: Configuration and temporary-Vault integration

**Files:**
- Modify: `config/config.example.jsonc`
- Modify: local ignored `config/config.jsonc` without staging it
- Extend: `tests/unit/test_obsidian_sync.py`
- Extend: `tests/unit/test_study_routes.py`

- [ ] **Step 1: Add example configuration test or parsed-config assertion**

The example contains `enabled`, empty `vault_id`, and empty `vault_path`, never the user path.

- [ ] **Step 2: Add the real local configuration only after code tests are green**

Set Vault ID `faccc16bf91c3d30` and path `/Users/zhanghanting/Obsidian` in the ignored live `config/config.jsonc`, which is the file read by `load_config()`. Do not write any Vault content during verification.

- [ ] **Step 3: Run temporary-Vault integration tests**

```bash
uv run --extra dev pytest tests/unit/test_obsidian_paths.py tests/unit/test_obsidian_markdown.py tests/unit/test_obsidian_sync.py tests/unit/test_study_repository.py tests/unit/test_study_service.py tests/unit/test_study_routes.py tests/unit/test_study_collection_context.py tests/unit/test_study_frontend_assets.py tests/unit/test_study_player_runtime.py -q
```

### Task 7: Impact checks and final verification

**Files:**
- Inspect all changed files only

- [ ] **Step 1: Run GitNexus detect_changes**

Review affected Study, collection, cache, and route flows. Address only regressions within this feature scope.

- [ ] **Step 2: Run fast unit suite**

```bash
uv run --extra dev pytest tests/unit
```

- [ ] **Step 3: Run syntax/diff checks**

```bash
uv run python -m compileall -q src/video_transcript_api
git diff --check
```

- [ ] **Step 4: Inspect final diff and real-Vault safety**

Confirm tests reference only temporary Vaults, no test or migration writes `/Users/zhanghanting/Obsidian`, no absolute Vault path appears in API output/log assertions, and unrelated `src/web/static/css/app-shell.css` remains untouched.

- [ ] **Step 5: Report verification evidence and user test steps**

Do not claim completion until all commands have fresh passing output. Do not commit, push, or write real Vault files without separate explicit authorization.
