# Unified Media Study Player Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static “边播边学” preview with a real `/study` content picker and production player for owned single media and collections on the existing `localhost:8000` service.

**Architecture:** Reuse `study.html`, `study.js`, `StudyService`, the audit history, and learning-collection storage. Add focused access/library/media-grant helpers so the UI never scans all tasks, native media elements receive short-lived signed URLs instead of API keys, and collection context is explicit in the route. Keep `/view/{view_token}` and the current collection workbench intact.

**Tech Stack:** FastAPI, SQLite, vanilla JavaScript, HTML/CSS, pytest, Starlette `FileResponse`, Python stdlib HMAC.

**Execution note:** The repository rule forbids commits unless the user explicitly requests them, so this plan deliberately omits commit steps. Work stays on the existing `ui-gemini-polish` feature branch that backs the running `8000` service.

---

### Task 1: Production page routes and navigation

**Files:**
- Modify: `src/video_transcript_api/api/routes/views.py`
- Modify: `src/web/static/study.html`
- Modify: `src/web/static/js/app-shell.js`
- Modify: `src/web/static/js/app.js`
- Modify: `src/web/static/collections.html`
- Modify: `src/web/static/js/collections.js`
- Test: `tests/unit/test_study_production_assets.py`

- [ ] **Step 1: Write failing asset/route-contract tests**

Assert that navigation uses `/study`, no production navigation points to `study-player-preview.html`, `study.html` contains picker and player roots, and the view router declares both `/study` and `/study/collections/{collection_id}/sources/{source_id}`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/unit/test_study_production_assets.py -q`

Expected: FAIL because `/study` and the production picker do not exist and navigation still targets the preview.

- [ ] **Step 3: Add production page modes**

Add server-rendered globals:

```js
window.STUDY_VIEW_TOKEN = '__VIEW_TOKEN__';
window.STUDY_COLLECTION_ID = '__COLLECTION_ID__';
window.STUDY_SOURCE_ID = '__SOURCE_ID__';
window.STUDY_PAGE_MODE = '__PAGE_MODE__';
```

Serve `study.html` in `library`, `single`, or `collection` mode. Both player routes use the same HTML and validate only structural existence at page-render time; authenticated APIs own data authorization.

- [ ] **Step 4: Replace all preview links**

Sidebar → `/study`; eligible history/source links use server-provided `study_url`. Remove the four preview-state links from production navigation.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run: `uv run pytest tests/unit/test_study_production_assets.py -q`

Expected: PASS.

### Task 2: Owned Study library and upload audit

**Files:**
- Create: `src/video_transcript_api/study/library.py`
- Modify: `src/video_transcript_api/api/routes/study.py`
- Modify: `src/video_transcript_api/api/routes/audit.py`
- Test: `tests/unit/test_study_library.py`
- Test: `tests/unit/test_study_routes.py`

- [ ] **Step 1: Write failing library tests**

Cover:

```python
items = service.list_single(user_id="user-a", q="lesson", limit=20, offset=0)
assert [item["view_token"] for item in items["items"]] == [owned_playable_token]
assert missing_source_token not in {item["view_token"] for item in items["items"]}
assert other_user_token not in {item["view_token"] for item in items["items"]}
```

Also assert `POST /api/study/upload` writes audit ownership with its new `task_id`.
Add a route-level assertion that `GET /api/study/library` reaches the library handler rather than `get_study_session(view_token="library")`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_study_library.py tests/unit/test_study_routes.py -q`

Expected: FAIL because the library service/route and Study upload audit call do not exist.

- [ ] **Step 3: Implement the smallest library query**

Add `GET /api/study/library?kind=single|collection&q=&limit=&offset=` **before** the dynamic `/{view_token}` declaration in `routes/study.py`, so FastAPI never consumes `library` as a view token. Single items come from audit rows joined by `task_id` to cache tasks and are filtered through the source resolver. Collection items are supplied by the owned collection service in Task 4. Return `{items, total}` only; browser progress is merged client-side.

- [ ] **Step 4: Add audit writes for Study uploads and retry**

Use the existing audit logger contract with `user_id`, masked API key, endpoint, display URL, status `202`, and `task_id`. Extend `/api/audit/history` with additive `study_available` and `study_url` fields computed server-side.

- [ ] **Step 5: Verify GREEN**

Run: `uv run pytest tests/unit/test_study_library.py tests/unit/test_study_routes.py tests/unit/test_history_routes.py -q`

Expected: PASS.

### Task 3: Safe source resolution and signed media URLs

**Files:**
- Create: `src/video_transcript_api/study/media_access.py`
- Modify: `src/video_transcript_api/study/source_files.py`
- Modify: `src/video_transcript_api/study/service.py`
- Modify: `src/video_transcript_api/api/routes/study.py`
- Test: `tests/unit/test_study_media_access.py`
- Test: `tests/unit/test_study_service.py`
- Test: `tests/unit/test_study_routes.py`

- [ ] **Step 1: Write failing grant and resolver tests**

Assert a signed grant round-trips only for its bound user/context, rejects expiry/tampering/cross-content reuse, and resolved paths stay under approved source roots. Assert session playback URLs contain `media_token` and never the API key.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_study_media_access.py tests/unit/test_study_service.py tests/unit/test_study_routes.py -q`

Expected: FAIL because signed media grants and the unified resolver do not exist.

- [ ] **Step 3: Implement stdlib HMAC grants**

Encode a compact payload `{user_id, kind, view_token|collection_id+source_id, exp}` using URL-safe base64 and HMAC-SHA256. Derive the signing key from the configured server auth secret; never serialize the API key. Validate signature with `hmac.compare_digest`.

- [ ] **Step 4: Issue and consume signed media URLs**

Authenticated session endpoints authorize first and then return a signed `playback.source_url`. Media endpoints validate the grant and safe path, respond with the detected MIME type and `Cache-Control: private, no-store`, and preserve Range behavior through `FileResponse`.

- [ ] **Step 5: Verify GREEN**

Run: `uv run pytest tests/unit/test_study_media_access.py tests/unit/test_study_service.py tests/unit/test_study_routes.py -q`

Expected: PASS.

### Task 4: Collection ownership and explicit collection sessions

**Files:**
- Modify: `src/video_transcript_api/collections/repository.py`
- Modify: `src/video_transcript_api/collections/service.py`
- Modify: `src/video_transcript_api/api/routes/collections.py`
- Modify: `src/video_transcript_api/api/routes/study.py`
- Modify: `src/video_transcript_api/study/repository.py`
- Modify: `src/video_transcript_api/study/service.py`
- Test: `tests/unit/test_learning_collections.py`
- Test: `tests/unit/test_study_routes.py`

- [ ] **Step 1: Write failing ownership/context tests**

Cover new collection owner persistence, single-user legacy backfill, multi-user hiding of ownerless rows, owner filtering for list/filter-options, and 404 on cross-owner detail/upload/retry/cancel/summary/knowledge-map/export/file/reveal. Cover two collections sharing one `view_token` and assert the collection route resolves the requested `collection_id/source_id`.

For collection Study APIs, test both allowed and cross-owner requests for session, notes create/update/delete, AI, Markdown export, and signed media. Create two owners/collections that deliberately share one `view_token`; assert notes and exports remain isolated by `owner_user_id + collection_id + source_id`.

Assert `GET /api/collections/{collection_id}/sources/{source_id}` adds `study_available` and `study_url` only when the owned source is audio/video and its safe file exists; `study_url` must be `/study/collections/{collection_id}/sources/{source_id}`. Missing files and document sources return `study_available: false` and an empty URL.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_learning_collections.py tests/unit/test_study_routes.py -q`

Expected: FAIL because collections have no owner and collection Study session routes do not exist.

- [ ] **Step 3: Add owner migration and repository filters**

Add nullable `owner_user_id`. New creates receive owner from `verify_token`, never request JSON. In fallback single-user mode backfill null owner to `legacy_user`; in multi-user mode leave unknown legacy rows hidden. Thread owner through list/filter/detail/mutation checks while preserving response shapes.

- [ ] **Step 4: Add explicit collection Study APIs**

Implement `/api/study/collections/{collection_id}/sources/{source_id}` plus notes, AI, export, and signed source-file routes. Resolve `view_token` from the exact source. Extend notes with owner/context columns so shared tokens do not share notes.

Decorate collection source detail server-side with `study_available` and the explicit `study_url` after owner and safe-file checks. Keep the existing source-detail response fields unchanged so `/collections` consumers only receive additive fields.

- [ ] **Step 5: Verify GREEN**

Run: `uv run pytest tests/unit/test_learning_collections.py tests/unit/test_study_routes.py tests/unit/test_study_service.py -q`

Expected: PASS.

### Task 5: Real picker UI and immediate local single playback

**Files:**
- Modify: `src/web/static/study.html`
- Modify: `src/web/static/css/study.css`
- Modify: `src/web/static/js/study.js`
- Test: `tests/unit/test_study_production_assets.py`

- [ ] **Step 1: Add failing DOM/source-contract tests**

Assert the page has two tabs, real search, single file input, folder/multi-file inputs, empty/loading/error regions, a hidden player root, transcript beside media, and no sample titles/transcripts. Assert JS calls `/api/study/library`, creates/revokes object URLs, uploads with `FormData`, and replaces history with the real Study route.

Assert JS defines one context-aware Study API-base resolver: single mode returns `/api/study/{view_token}`; collection mode returns `/api/study/collections/{collection_id}/sources/{source_id}`. Session, notes create/update/delete, AI chat, Markdown export, retry eligibility, and media refresh must all build from that base rather than hard-code the single route.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_study_production_assets.py -q`

Expected: FAIL because `study.html/js` only support a pre-existing token.

- [ ] **Step 3: Implement library mode**

When `STUDY_PAGE_MODE === 'library'`, render the approved compact picker. Debounce server search, merge `localStorage` progress, and render only API items. Missing token shows the existing settings guidance; empty results keep local import visible.

Introduce `studyApiBase()` and route every Study read/write through it. Changing collection episodes updates `collection_id/source_id`, recomputes the base, and then reloads session/notes/AI/export using the collection endpoints; standalone mode continues using the existing token endpoints.

- [ ] **Step 4: Implement immediate single playback**

On file select, validate MIME/extension, create an object URL, switch the same page to player mode and begin playback before upload completes. Upload in the background; on `view_token`, replace history without reload, migrate progress, load the authenticated session, then revoke the object URL only after the server source is playable.

- [ ] **Step 5: Move transcript to the always-visible right panel**

Make “同步逐字稿” the default/right-side permanent view, add the current subtitle strip directly below media, and keep AI as an on-demand drawer/tab. Preserve existing visual-learning and note behavior.

- [ ] **Step 6: Verify GREEN and syntax**

Run:

```bash
uv run pytest tests/unit/test_study_production_assets.py -q
node --check src/web/static/js/study.js
```

Expected: PASS and no syntax errors.

### Task 6: Collection import, dropdown navigation, retry, and progress

**Files:**
- Modify: `src/web/static/js/study.js`
- Modify: `src/web/static/study.html`
- Modify: `src/web/static/css/study.css`
- Modify: `src/video_transcript_api/collections/service.py`
- Modify: `src/video_transcript_api/api/routes/study.py`
- Modify: `src/video_transcript_api/cache/cache_manager.py`
- Test: `tests/unit/test_study_production_assets.py`
- Test: `tests/unit/test_study_routes.py`
- Test: `tests/unit/test_learning_collections.py`
- Test: `tests/unit/test_view_token_dedup.py`

- [ ] **Step 1: Write failing collection-flow tests**

Assert audio extensions are accepted by the existing `video_course` media collection, collection session returns ordered episodes, and production JS natural-sorts local files, creates a collection, batch uploads, switches via the explicit route, and stores progress by `collection_id:source_id`.

Add single-retry tests before implementation:

```python
first = cache_manager.create_task(url=url, platform="generic", media_id=media_id)
retry = cache_manager.create_task(
    url=url,
    platform="generic",
    media_id=media_id,
    force_new_view_token=True,
)
assert retry["task_id"] != first["task_id"]
assert retry["view_token"] != first["view_token"]
```

Also assert the default `create_task` path still reuses tokens, and `POST /api/study/{view_token}/retry` rejects non-terminal/unowned/missing-source tasks but creates and audits a new task/token for an owned terminal failure.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_study_production_assets.py tests/unit/test_study_routes.py tests/unit/test_learning_collections.py tests/unit/test_view_token_dedup.py -q`

- [ ] **Step 3: Implement local collection flow**

Use folder name or common filename prefix for the title and `未归属` for creator display. Create object URLs for selected media, immediately play the first, create the collection, upload sources, replace temporary entries with returned source IDs, and keep uploads alive while switching episodes.

- [ ] **Step 4: Implement compact episode dropdown and progress**

Show dropdown plus previous/next only in collection mode. Navigate with `history.pushState`/`popstate`, update the context-aware API base, load the exact collection session, and keep notes/AI/export on that same context. Throttle progress writes to five seconds plus pause/switch/unload.

- [ ] **Step 5: Implement distinct failure actions**

Add `force_new_view_token: bool = False` to `CacheManager.create_task`; when true, skip both URL and `(platform, media_id)` token reuse while preserving default dedup behavior. Implement `POST /api/study/{view_token}/retry`: authorize the old task, require a terminal status and retained safe source, create the new task with `force_new_view_token=True`, write its audit row, schedule `process_local_upload`, and return the new IDs. Browser upload failure → re-upload current `File`; terminal server failure → this endpoint or existing collection source retry; missing source → choose the file again. Never show one ambiguous retry action.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
uv run pytest tests/unit/test_study_production_assets.py tests/unit/test_study_routes.py tests/unit/test_learning_collections.py tests/unit/test_view_token_dedup.py -q
node --check src/web/static/js/study.js
```

Expected: PASS.

### Task 7: Regression, production-server, and browser verification

**Files:**
- Modify only if a failing verification proves a task-local defect.

- [ ] **Step 1: Run focused and regression suites**

```bash
uv run pytest tests/unit/test_study_production_assets.py tests/unit/test_study_library.py tests/unit/test_study_media_access.py tests/unit/test_study_routes.py tests/unit/test_study_service.py tests/unit/test_learning_collections.py tests/unit/test_app_shell_noise.py -q
```

- [ ] **Step 2: Run diff and graph checks**

```bash
git diff --check
gitnexus detect-changes --scope unstaged --repo VideoTranscriptAPI
```

Review only the task-local files; keep `server.sh` and `tests/unit/test_server_script.py` unrelated.

- [ ] **Step 3: Restart/refresh the existing service safely and verify HTTP**

Confirm:

```text
GET http://localhost:8000/study -> 200
GET http://localhost:8000/static/study-player-preview.html -> may remain as isolated reference, but no production link points to it
```

Verify authenticated library APIs return real or empty data, never samples.

- [ ] **Step 4: Browser verification**

At desktop and 390px widths verify:

- sidebar opens `/study`;
- no four demo scenario buttons;
- local file chooser opens and selected media plays before analysis completes;
- existing content opens the real player;
- transcript stays visible beside media;
- collection dropdown switches exact sources;
- AI opens on demand;
- no console errors or horizontal overflow.

- [ ] **Step 5: Report completion without committing**

Summarize changed behavior, tests, HTTP/browser evidence, and any intentionally deferred item. Do not claim production UI is connected until the `8000` browser verification passes.
