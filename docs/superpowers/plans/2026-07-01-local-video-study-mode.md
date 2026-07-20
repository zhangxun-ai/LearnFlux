# Local Video Study Mode MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit unless the user explicitly asks.

**Goal:** Build one polished local-video learning workspace based on the version A layout: play the local video, read the transcript, review AI interpretation, write timestamped notes, and export the learning result.

**Architecture:** Add a focused `study` domain beside the existing task/cache/collection code. Keep existing `/view/{view_token}` and `/api/upload-transcribe` behavior unchanged. Introduce a study-specific upload/playback path that preserves local source video files, exposes a small read model API, and keeps frontend state in a dedicated `study.js`.

**Tech Stack:** FastAPI, SQLite, existing `CacheManager`, existing local ASR/LLM pipeline, static HTML/CSS/JS, browser `<video>`, ffmpeg only when needed for later screenshot extraction.

---

## Product Boundary

First version must be small and excellent.

In scope:
- Local video upload for study mode.
- Local video playback in the browser.
- Transcript panel with seek support when timestamps exist.
- AI 看 panel using existing summary/calibrated output first.
- Timestamped personal notes.
- Markdown export for summary, transcript anchors, and notes.
- UI based only on the version A layout.

Deferred:
- B/C UI variants.
- YouTube/B 站 playback.
- Full collection learning workspace.
- Complex courseware-to-video matching.
- Automatic rich visual-note generation with many screenshots.
- Collaborative notes or multi-user sharing.

---

## Design Principles

- Keep the current transcription pipeline stable; do not change default upload cleanup behavior.
- Add a study-specific path rather than overloading existing endpoints.
- Split responsibilities into small modules:
  - source-file retention and playback;
  - transcript normalization;
  - study session read model;
  - notes persistence;
  - frontend rendering.
- Store extensible JSON payloads only at domain boundaries where future assets need room to grow.
- Make graceful degradation explicit: if a task has no retained local video, the page still shows transcript and AI content but explains that playback is unavailable.

---

## File Structure

- Create `src/video_transcript_api/study/__init__.py`
  - Package marker.
- Create `src/video_transcript_api/study/source_files.py`
  - Stable local source-file paths, safe filename/ext handling, MIME detection.
- Create `src/video_transcript_api/study/transcript.py`
  - Convert cache transcript data into UI lines with optional timestamps.
- Create `src/video_transcript_api/study/repository.py`
  - SQLite storage for playback progress and user notes.
- Create `src/video_transcript_api/study/service.py`
  - Build the study-page read model from cache, source files, transcript, AI output, and notes.
- Create `src/video_transcript_api/api/routes/study.py`
  - Study upload, data, source-file playback, notes, and export endpoints.
- Modify `src/video_transcript_api/api/app.py`
  - Register the study router.
- Modify `src/video_transcript_api/api/services/transcription.py`
  - Reuse `process_local_upload(..., preserve_source_file=True)` for study uploads.
- Modify `src/video_transcript_api/api/routes/views.py`
  - Add `GET /study/{view_token}` for the learning workspace.
- Create `src/web/static/study.html`
  - Production version A shell.
- Create `src/web/static/css/study.css`
  - Focused production styles extracted from the mockup.
- Create `src/web/static/js/study.js`
  - Fetch state, render panels, sync video/transcript, save notes.
- Add tests:
  - `tests/unit/test_study_source_files.py`
  - `tests/unit/test_study_transcript.py`
  - `tests/unit/test_study_repository.py`
  - `tests/unit/test_study_service.py`
  - `tests/unit/test_study_routes.py`

---

### Task 1: Version A-Only Study Shell

**Files:**
- Create: `src/web/static/study.html`
- Create: `src/web/static/css/study.css`
- Create: `src/web/static/js/study.js`
- Modify: `src/video_transcript_api/api/routes/views.py`

- [ ] **Step 1: Extract the shell**
  - Use the approved version A layout.
  - Remove mock data from the production shell and replace it with loading/empty containers.

- [ ] **Step 2: Add the route**
  - Add `GET /study/{view_token}`.
  - Render `study.html` with `window.STUDY_VIEW_TOKEN`.
  - Return 404 for invalid tokens.

- [ ] **Step 3: Verify**
  - Run: `uv run pytest tests/unit/test_api_routes.py tests/unit/test_views_export_path.py -q`
  - Manual: open `/study/{view_token}` and confirm the shell renders.

---

### Task 2: Study Upload And Local Video Playback

**Files:**
- Create: `src/video_transcript_api/study/source_files.py`
- Create/Modify: `src/video_transcript_api/api/routes/study.py`
- Modify: `src/video_transcript_api/api/app.py`
- Test: `tests/unit/test_study_source_files.py`
- Test: `tests/unit/test_study_routes.py`

- [ ] **Step 1: Add source-file helper tests**
  - Verify safe extension handling.
  - Verify stable storage path under `storage.source_files_dir/study_uploads`.
  - Verify video MIME detection for `.mp4`, `.mov`, `.mkv`, `.webm`.

- [ ] **Step 2: Implement `POST /api/study/upload`**
  - Stream the file to disk.
  - Compute or assign `media_id`.
  - Create a normal task through `cache_manager.create_task`.
  - Submit `process_local_upload(..., preserve_source_file=True)`.
  - Do not alter `/api/upload-transcribe`.

- [ ] **Step 3: Implement `GET /api/study/{view_token}/source-file`**
  - Resolve retained local source file.
  - Return `FileResponse` with the correct media type.
  - If manual seeking fails, add Range response support before moving on.

- [ ] **Step 4: Verify**
  - Unit: upload route preserves source file flag.
  - Unit: missing source file returns 404.
  - Manual: upload a short MP4, open the study page, and play/seek the video.

---

### Task 3: Study Read Model API

**Files:**
- Create: `src/video_transcript_api/study/transcript.py`
- Create: `src/video_transcript_api/study/repository.py`
- Create: `src/video_transcript_api/study/service.py`
- Modify: `src/video_transcript_api/api/routes/study.py`
- Test: `tests/unit/test_study_transcript.py`
- Test: `tests/unit/test_study_repository.py`
- Test: `tests/unit/test_study_service.py`

- [ ] **Step 1: Transcript normalizer**
  - Support timed FunASR-like JSON when present.
  - Support plain text fallback as untimed lines.
  - Return a consistent shape: `id`, `start_seconds`, `end_seconds`, `text`, `seekable`.

- [ ] **Step 2: Notes repository**
  - Table: `study_notes(id, view_token, time_seconds, body, created_at, updated_at)`.
  - Keep it independent from cache tables.

- [ ] **Step 3: Study service**
  - `get_session(view_token)` returns:
    - metadata;
    - playback source availability;
    - transcript lines;
    - AI overview from existing `llm_summary` / `llm_calibrated`;
    - notes.

- [ ] **Step 4: API**
  - `GET /api/study/{view_token}` returns the read model.
  - Include explicit states: `processing`, `ready`, `failed`, `source_missing`.

- [ ] **Step 5: Verify**
  - Unit: timed transcript is seekable.
  - Unit: plain transcript is readable but not seekable.
  - Unit: service handles missing source file without failing.

---

### Task 4: Frontend Interaction Quality

**Files:**
- Modify: `src/web/static/study.html`
- Modify: `src/web/static/css/study.css`
- Modify: `src/web/static/js/study.js`

- [ ] **Step 1: Load state**
  - Fetch `/api/study/{view_token}`.
  - Render loading, processing, ready, failed, and source-missing states.

- [ ] **Step 2: Video and transcript sync**
  - Bind browser video time to transcript highlighting.
  - Click transcript lines to seek only when `seekable=true`.
  - Persist last playback time only after notes API is stable.

- [ ] **Step 3: Right-side panels**
  - `AI 看`: overview and section summary.
  - `文稿`: full transcript.
  - `笔记`: user notes.
  - `图文` and `课件` stay as minimal empty/coming-next panels in V1 unless backed by real data.

- [ ] **Step 4: Notes**
  - Add note at current video time.
  - Edit and delete notes.
  - Notes should survive reload.

- [ ] **Step 5: Verify**
  - Playwright desktop viewport `1440x1100`.
  - Playwright mobile viewport `390x1200`.
  - Confirm no text overlap, panel switching works, and transcript seeking works.

---

### Task 5: Export And Polish

**Files:**
- Modify: `src/video_transcript_api/api/routes/study.py`
- Modify: `src/web/static/js/study.js`
- Test: `tests/unit/test_study_routes.py`

- [ ] **Step 1: Markdown export**
  - Add `GET /api/study/{view_token}/export/markdown`.
  - Export title, AI overview, transcript anchors where available, and personal notes.

- [ ] **Step 2: Polish empty states**
  - Old tasks without source file must clearly say playback is unavailable.
  - Tasks still processing must poll status without blocking the page.

- [ ] **Step 3: Regression checks**
  - `/view/{view_token}` still works.
  - `/api/upload-transcribe` still cleans temporary source files by default.
  - Collection upload behavior remains unchanged.

- [ ] **Step 4: Final verification**
  - Run:
    - `uv run pytest tests/unit/test_study_source_files.py tests/unit/test_study_transcript.py tests/unit/test_study_repository.py tests/unit/test_study_service.py tests/unit/test_study_routes.py -q`
    - `uv run pytest tests/unit/test_api_routes.py tests/unit/test_transcriber.py -q`
  - Manual E2E: upload short MP4 -> task completes -> study page plays video -> transcript visible -> AI overview visible -> note saved -> export downloads Markdown.

---

## Confirmation Gate

Do not start implementation until the user confirms this MVP scope.

Recommended first implementation batch after confirmation:
1. Task 1 shell route.
2. Task 2 study upload and source-file playback.
3. Task 3 read model API.

Only after those are stable should we improve `图文` and `课件`.
