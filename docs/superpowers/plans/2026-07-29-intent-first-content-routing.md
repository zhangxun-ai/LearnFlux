# Intent-first Content Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Keep existing working-tree changes.

**Goal:** Make single-study always execute deep learning for every supported
source while keeping post insight explicit and independent.

**Architecture:** Persist analysis intent from the entry point, use source type
only for acquisition, add a comment-free X source downloader with video/text
capabilities, derive server-confirmed content kind for preprocessing, and make
analysis/history/result navigation intent-driven.

**Tech Stack:** Vanilla JavaScript, FastAPI/Pydantic, TikHub REST, pytest, Node.js,
GitNexus.

---

### Task 1: Lock the frontend intent invariant

**Files:**
- Modify: `src/web/static/js/app.js`
- Test: `tests/unit/test_home_content_routing.py`
- Test: `tests/unit/test_home_page.py`

- [ ] Add a failing Node-backed intent matrix for WeChat Official Accounts,
  Xiaohongshu, WeChat Channels, Douyin, YouTube, the exact X `/video/1?s=46`
  URL, and unknown sources.
- [ ] Assert `classifySource()` returns X source while
  `classifyContent(..., "deep_learning")` returns learning history semantics.
- [ ] Assert every matrix entry remains `deep_learning` and deep-learning
  submission contains no source-driven `/post` redirect.
- [ ] Make presentation/history type derive from `analysisIntent`, not social host.
- [ ] Remove the deep-learning comment-insight controls and submit
  `include_comments=false` for every source.
- [ ] Run the focused frontend tests and `node --check`.

### Task 2: Make history and result navigation intent-driven

**Files:**
- Modify: `src/web/static/js/app.js`
- Test: `tests/unit/test_home_content_routing.py`
- Test: `tests/unit/test_home_page.py`

- [ ] Add failing tests for X deep-learning success, failure, pending, legacy,
  server-synced, and marked entries.
- [ ] Prefer stored `analysis_intent`, `view_token`, and `result_id` over URL
  reclassification.
- [ ] Preserve local `analysis_intent` while merging audit/marked entries and
  recover audit entries with `view_token` as `deep_learning`.
- [ ] Keep post-insight navigation only for explicit `post_insight` entries.
- [ ] Ensure deep-learning retry returns to the deep-learning workbench.
- [ ] Run the focused tests.

### Task 3: Add a comment-free X source downloader

**Files:**
- Add: `src/video_transcript_api/downloaders/twitter.py`
- Modify: `src/video_transcript_api/downloaders/factory.py`
- Modify: `src/video_transcript_api/downloaders/__init__.py`
- Test: `tests/unit/test_twitter_downloader.py`
- Test: `tests/unit/test_downloader_factory.py`

- [ ] Write failing tests for canonical X/Twitter hosts and status ID extraction,
  including `/video/1?s=46`; reject lookalike hosts, userinfo, and unapproved
  subdomains.
- [ ] Write failing response-shape tests for tweet text, X Article text,
  `media_playable_url`, `data.media`, and video variants; accept only explicit
  video MIME/type or `.mp4`, and reject image/ambiguous media.
- [ ] Assert the adapter calls only `fetch_tweet_detail`, never
  `fetch_post_comments`.
- [ ] Implement `TwitterDownloader` with one per-instance detail cache.
- [ ] Prove metadata plus download info makes exactly one detail request.
- [ ] Register it before `GenericDownloader` and run focused downloader tests.

### Task 4: Route X video and X text through deep learning

**Files:**
- Modify: `src/video_transcript_api/api/services/transcription.py`
- Modify: `src/video_transcript_api/api/services/llm_ops.py`
- Test: `tests/unit/test_twitter_deep_learning.py`
- Test: `tests/unit/test_analysis_intent_queue.py`

- [ ] Add a failing worker test showing an X video uses the X download URL and
  enters existing ASR/LLM flow with tweet context.
- [ ] Add a failing worker test showing an X text/article skips ASR and queues
  text deep learning.
- [ ] Add canonical worker negative tests proving forged `source_type`, forged
  `URLParser platform`, lookalike hosts, userinfo, and unapproved subdomains
  cannot invoke the X text helper.
- [ ] Assert both paths force comments off and retain `analysis_intent`.
- [ ] Derive `content_kind` from the confirmed adapter result; never use the
  client `source_type` to select text/video handling or the summary profile.
- [ ] Add failing error tests: video download failure cannot fall back to text;
  empty text plus no video fails without cache/LLM; image media is not video;
  non-empty text without video is the only text-helper case.
- [ ] Add partial/full cache and serial resubmission tests proving no repeated X
  detail request or LLM enqueue after reusable results exist.
- [ ] Implement the smallest text-artifact queue helper and X branch.
- [ ] Select one deep-learning summary profile solely from
  `analysis_intent=deep_learning` for every source; `content_kind` affects only
  acquisition/preprocessing.
- [ ] Run focused X, WeChat, Xiaohongshu, and queue tests.

### Task 5: Prove global module independence

**Files:**
- Modify: `src/video_transcript_api/api/services/transcription.py`
- Modify: `src/video_transcript_api/api/services/llm_ops.py`
- Test: `tests/unit/test_post_insight_service.py`
- Test: `tests/unit/test_post_insight_routes.py`
- Test: `tests/unit/test_transcription_public_contract.py`

- [ ] Add or tighten tests proving `/api/transcribe` cannot accept
  `post_insight`.
- [ ] Normalize `include_comments=false` before URL parsing/cache checks for all
  deep-learning tasks, and use it in every LLM payload.
- [ ] Add a defensive `llm_ops` guard so forged deep-learning payloads cannot
  enter comment-only or comment-analysis paths.
- [ ] Cover malicious `include_comments=true` for cold/partial/full cache across
  WeChat articles, Xiaohongshu text/video, WeChat Channels, Douyin, YouTube,
  X text/video, direct media, and unknown sources, proving no comment
  fetcher/analyzer call.
- [ ] Add a contract matrix proving every supported source sent to
  `/api/transcribe` remains `deep_learning` and no source can select the
  post-insight analyzer.
- [ ] Add a `source × intent` matrix: post-insight-supported sources remain in
  post insight; unsupported sources return unsupported inside that product and
  never create a deep-learning task.
- [ ] Parameterize forged client `source_type` across all source families and
  prove it cannot change server-confirmed source, content kind, analyzer, or
  summary profile.
- [ ] Re-run post-insight service/template tests to prove explicit comment and
  social-analysis behavior is unchanged.

### Task 6: Verification and impact audit

**Files:** Inspect all changed files; do not commit.

- [ ] Run all focused tests from Tasks 1–5.
- [ ] Run `node --check src/web/static/js/app.js`.
- [ ] Run relevant UI smoke checks without touching the service in the original
  checkout.
- [ ] Run `uv run --extra dev pytest tests/unit` if focused checks are green and
  the existing unrelated baseline is accounted for.
- [ ] Run GitNexus `detect_changes(scope="all", worktree=<current>)`.
- [ ] Review `git diff` to preserve all pre-existing TikHub V2, token-redaction,
  accessibility, and workbench changes.
