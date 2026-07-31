# WeChat Analysis Intent Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WeChat Official Account articles entered from single-study create stable deep-learning tasks while keeping post insight explicit and WeChat Channels on the video path.

**Architecture:** Split browser source classification from the workbench-selected analysis intent. Carry both through the transcription request/queue, fetch Official Account article text without comments, and feed it into the existing cached deep-learning LLM pipeline. Keep `/api/post-insight` independent and remove query-string auto-execution.

**Tech Stack:** Vanilla JavaScript, FastAPI/Pydantic, pytest, Node.js syntax/runtime checks, GitNexus.

---

### Task 1: URL extraction and browser source classification

**Files:**
- Modify: `src/web/static/js/app.js`
- Test: `tests/unit/test_home_content_routing.py`

- [x] Write a Node-backed failing test that extracts `URLExtractor` and asserts one input `https://mp.weixin.qq.com/s/example` produces exactly one URL.
- [x] Run `uv run --extra dev pytest tests/unit/test_home_content_routing.py -v` and confirm failure contains the extra `https://qq.com/s/example`.
- [x] Change `URLExtractor.extractURLs()` to retain match spans and discard lower-priority matches contained in an accepted URL span.
- [x] Add failing classification assertions for `wechat_mp_article` and `wechat_channels_video`.
- [x] Add `classifySource()` and make `classifyContent()` derive display data for explicit `deep_learning` intent without routing公众号 to `post`.
- [x] Run the focused test and confirm green.

### Task 2: Workbench intent and UI continuity

**Files:**
- Modify: `src/web/static/index.html`
- Modify: `src/web/static/js/app.js`
- Modify: `src/web/static/css/workbench.css`
- Test: `tests/unit/test_home_content_routing.py`

- [x] Add failing assertions that the link strategy container has `id="video-options"`,公众号 submission sends `analysis_intent=deep_learning`, and no branch redirects a detected公众号 to `/post`.
- [x] Add `source_type` and `analysis_intent` to `APIManager.submitTranscription()` and its request body.
- [x] Make `submitTranscription()` always keep supported sources in the current deep-learning task flow.
- [x] Add a secondary “切换到帖子洞察” link only to the公众号 detection banner.
- [x] Hide `#video-options` for article sources and keep it visible for video/video号/unknown sources.
- [x] Run the focused test and `node --check src/web/static/js/app.js`.

### Task 3: Explicit request/queue contract

**Files:**
- Modify: `src/video_transcript_api/api/services/transcription.py`
- Modify: `src/video_transcript_api/api/routes/tasks.py`
- Test: `tests/unit/test_api_routes.py`

- [x] Write a failing route test posting `source_type=wechat_mp_article` and `analysis_intent=deep_learning`, asserting both fields reach the task queue.
- [x] Add failing contract tests for old-client defaults and invalid intent returning validation error/HTTP 422.
- [x] Extend `TranscribeRequest` with constrained backward-compatible fields.
- [x] Carry both values through the route task payload, `process_task_queue`, and keyword-only `process_transcription` parameters.
- [x] Add an async worker forwarding test that captures `executor.submit` and proves neither field is dropped between queue and `process_transcription`.
- [x] Validate that the only transcription intent accepted by `/api/transcribe` is `deep_learning`; post insight remains on its own endpoint.
- [x] Run the focused route test.

### Task 4: Official Account article source adapter

**Files:**
- Modify: `src/video_transcript_api/comments/weixin_post.py`
- Test: `tests/unit/test_weixin_post_fetcher.py`

- [x] Write a failing test for `WeixinPostFetcher.fetch_article()` asserting it calls article detail but never comments.
- [x] Add a public `fetch_article()` method that reuses the configured V2 adapter and downloader.
- [x] Keep `fetch()` behavior unchanged for explicit post insight, including best-effort comments.
- [x] Run `uv run --extra dev pytest tests/unit/test_weixin_post_fetcher.py -v`.

### Task 5: Official Account deep-learning queue path

**Files:**
- Modify: `src/video_transcript_api/api/services/transcription.py`
- Test: `tests/unit/test_weixin_deep_learning.py`

- [x] Write failing canonical predicate tests for a real `mp.weixin.qq.com` article plus lookalike host, userinfo, subdomain, query-form article, and `weixin.qq.com/sph/...` negatives.
- [x] Implement a `urlsplit()`-based predicate that requires hostname exactly `mp.weixin.qq.com` and a supported article path/query; never route from client `source_type` or `URLParser platform` alone.
- [x] Write a failing test for `_queue_weixin_article_deep_learning()` asserting正文 cache, LLM queue payload, progress/status, source metadata, and no comment fetch.
- [x] Implement the smallest helper mirroring the proven Xiaohongshu article path while accepting an injectable article fetcher.
- [x] Add a failing worker-path test proving canonical公众号 predicate true plus `analysis_intent=deep_learning` invokes the helper before downloader/ASR.
- [x] Add an end-to-end worker negative test proving that a forged `source_type=wechat_mp_article` and even `URLParser platform=weixin` cannot invoke the helper when the canonical predicate is false.
- [x] Wire the helper after cache miss and before downloader creation.
- [x] Add a boundary test proving `weixin.qq.com/sph/...` stays outside the helper.
- [x] Add a failing empty-body test proving a title-only article is rejected with `无法获取公众号文章正文`, writes no cache, enqueues no LLM work, and ends in `FAILED`; keep title-only support unchanged for explicit post insight.
- [x] Add cold-cache, partial-cache, and full-cache tests proving `include_comments=true` is normalized to `effective_include_comments=False` before `_should_use_cached_llm_results` and every LLM payload; the full cache returns without article fetch or new LLM work.
- [x] Add a serial resubmission test proving a completed cache is reused; document that concurrent in-flight coalescing is out of scope.
- [x] Add an article-specific summary profile covering the learning-output contract and carry it through initial LLM work, partial-cache recomputation, and summary-only retries without changing legacy callers.
- [x] Run the focused tests and existing Xiaohongshu deep-learning tests.

### Task 6: Explicit post-insight cost boundary

**Files:**
- Modify: `src/web/templates/post_insight.html`
- Test: `tests/unit/test_post_insight_routes.py`

- [x] Add a failing template test asserting prefilled `?url=` does not call `analyze()` on load, page refresh does not issue a POST, and the UI includes a re-analysis cost warning.
- [x] Remove query-string auto-analysis; retain `?view=` local-result rendering for compatibility and show a recoverable message when unavailable.
- [x] Add explicit copy explaining TikHub/LLM work starts only after clicking “分析”.
- [x] Run the focused route/template tests.

### Task 7: Verification and impact audit

**Files:**
- Inspect all changed files; do not commit.

- [x] Run focused tests for routing, API request propagation, Weixin fetcher/deep learning, post insight, downloader factory, and existing TikHub regression.
- [x] Run `node --check src/web/static/js/app.js`.
- [x] Run the relevant UI/Playwright smoke check if the repository has a deterministic local fixture; do not touch the service in the other checkout.
- [x] Run `uv run --extra dev pytest tests/unit` if focused checks are green and time/risk budget permits.
- [x] Run GitNexus `detect_changes(scope="all", worktree=<current>)` and inspect high-risk symbols.
- [x] Review `git diff` to confirm pre-existing app.js/accessibility/TikHub V2/token-redaction edits are preserved and no secrets or runtime artifacts were added.

**Verification note:** The task-focused regression set passed 194 tests, and the
three offline LLM compatibility files passed 18 tests. The full unit run reached
the repository-wide suite and reported 11 failures in unrelated app-shell,
collection, settings, study-player, and generated-navigation contracts; none of
their implementation files were changed by this plan.
