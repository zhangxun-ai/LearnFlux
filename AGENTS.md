过程中请使用中文和我沟通，但 console 里请优先使用英文。
# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/video_transcript_api`: `api/server.py` hosts FastAPI, `downloaders/` contains platform adapters, `transcriber/` wraps CapsWriter and FunASR clients, and `utils/` now splits into focused subpackages (`logging/`, `cache/`, `llm/`, `rendering/`, `notifications/`, `accounts/`, `timeutil/`, `risk_control/`). Templates remain in `src/web/templates`. Tests are separated within `tests/` by scope (unit, integration, performance, manual, llm, cache, features, platforms). Configuration examples sit in `config/*.example.json`, while live secrets stay in `config/config.json`. Runtime caches, SQLite stores, and logs go to `data/`; automation helpers live in `scripts/`. Launch the API through `main.py`.

## Build, Test, and Development Commands

Use uv for dependency management and command execution.

```bash
# Install project and test dependencies
uv sync --extra dev

# Start/manage the API in the background (default port 8000)
bash server.sh start
bash server.sh status
bash server.sh log
bash server.sh restart
bash server.sh stop

# Foreground troubleshooting, after stopping the background service
uv run python main.py --start

# verify-fast: fast unit suite
uv run --extra dev pytest tests/unit

# verify-full: all default offline tests
uv run --extra dev pytest

# Add new dependencies
uv add <package-name>

# Update lockfile
uv lock
```

Feature, integration, LLM, platform, manual, and performance checks are opt-in because they may require credentials, reachable services, network access, local media, or data writes. Run only the specific file needed:

```bash
uv run --extra dev pytest tests/integration/<test_file>.py -s
uv run python tests/performance/test_concurrent.py
uv run python tests/manual/test_transcribe.py <audio_path>
```

## Coding Style & Naming Conventions
Target Python 3.11+, keep PEP 8 spacing (4-space indents), and use snake_case for modules, functions, and variables. Follow the established Google-style docstrings on public APIs. Route logging through `video_transcript_api.utils.logging.setup_logger` so loguru manages stdout and rotation in `logs/`. Keep console and test output in English ASCII; communicate with the user in Chinese. Prefer type hints and build on helpers inside the relevant `utils.*` subpackages to keep features modular.

## Time and Date Rules
Use Beijing time (UTC+8 / `Asia/Shanghai`) for user-facing timestamps and calendar-day filters. Persist instants in UTC; legacy database timestamps without an offset are UTC. Use `utils.timeutil` on the backend and `src/web/static/js/time.js` in the browser. API timestamps must include an explicit offset. Do not parse naive database timestamps as the browser's local time.

## Document Sources

Local daily reports live in `briefings/` and `api/routes/briefings.py`; read [daily briefings](docs/guides/daily-briefings.md). `/briefings` only reads published artifacts, with owner/local-host checks and current source policy/hash validation. GET/preview must never sync or generate. Group and select reports by edition date, never file modification or rebuild time; preserve legacy WeChat content-day identities and Feishu deduplication keys. An explicitly requested missing edition must show an empty state, not an older report. Reuse existing destinations only after explicit preview confirmation; do not copy private source pages/media or overwrite edited notes. Verify with `uv run --extra dev pytest tests/unit/test_briefings.py -q` and `uv run python scripts/sync_product_navigation.py --check`.
Feishu Wiki/Docx links use `document_sources/feishu.py` and the text-learning path, never media download/ASR. Gate the local CLI identity by the configured task owner before reading even cached private content. Preserve full source responses and disclose unexpanded visuals. See `docs/guides/feishu-documents.md`.

When a transcription control store is installed, use its `updated_at` as the progress heartbeat for runtime timeout recovery. The legacy `last_heartbeat_at` column may retain the task creation time. Compare instants with explicit timezone semantics.

Ordinary URL recovery uses persisted non-secret `task_requests` and `api/services/task_recovery.py`; never blindly replay cloud requests, disabled owners or canceled work. Evidence retrieval lives in `study/evidence.py` and `study/body_search.py`: authorize all selected sources before loading private text, keep model context bounded and preserve real source positions. Feishu delivery and revision protection are described in `docs/guides/feishu-archive.md`.

## Testing Guidelines
Use pytest. `verify-fast` covers unit tests; `verify-full` covers the default offline suite. Feature, integration, LLM, platform, manual, and performance tests must be run explicitly. Mock CapsWriter, FunASR, TikHub, and notification clients in fast feedback tests. Redirect transient media into `tests/cache/` and clean up afterward to avoid polluting `data/`. Update `tests/README.md` when you add new suites or flags.

## Commit & Pull Request Guidelines
Commit messages follow the current log style: concise, imperative Chinese summaries (`修复 API 并发重试`). Group related edits before opening a PR. PR descriptions should outline scope, note config or schema touchpoints, reference issues with `#123`, and attach evidence (pytest output, manual steps, API samples). Flag any follow-up actions such as restarting services or updating `config/config.json`.

## Security & Configuration Notes

User-specific secrets, endpoints, model IDs and paths belong in private environment/config files, never source code or public fixtures. `main.py` loads root `.env`; `config_env.py` applies nonempty environment overrides after JSONC and saved settings. Environment-managed settings are read-only and must not be persisted by the settings API. `server.sh` shares dotenv port validation without sourcing shell code or importing the app. On macOS, put private values in `.env`; LaunchAgent does not copy terminal credentials into its plist.

Both new-user prompts and the environment template default to SQLite; preserve existing PostgreSQL deployments. SQLite compatibility is covered by the isolated HTTP/worker/export/restart flow in `tests/integration/test_sqlite_learning_flow.py`. The copyable beginner prompt lives near the top of README; keep it aligned with the expanded prompt. New-user success requires actual selected-platform URLs, real content acquisition, the selected ASR when needed, real model output and view/export/persistence checks; sample text, subtitles, image-post extraction, cache hits or offline mocks do not prove ASR/platform readiness. Keep model, TikHub and cloud-ASR credentials distinct, respect spending approval and current MLX platform limits. Follow `docs/guides/postgresql.md`: create a dedicated database/role, then startup applies checked-in versioned SQL migrations automatically. Validate the migration ledger and required tables; never run write/delete integration checks against an actual user's database. Enterprise-WeChat notifications are retired: do not restore old channels or expose legacy audit webhook values. Inert import/argument compatibility and old schema columns remain for existing data; never rewrite applied SQL migrations or remove user ownership fields. Feishu notifications and document archives remain separate features. Explicit real Feishu notification tests use `LEARNFLUX_TEST_FEISHU_WEBHOOK` and skip without it. See `docs/security/configuration-secrets-review.md` for the credential review and outstanding historical rotation requirements.
Do not commit live credentials; extend `config.example.json` and document defaults instead. Keep generated artifacts in `data/` and `logs/` out of patches unless troubleshooting. When working with remote transcription servers, load tokens from environment variables and clear `data/temp` via `scripts/cleanup_cache.py` after tests so sensitive media does not linger.

## Social Data & TikHub Usage
For new social-media data features, first evaluate TikHub REST APIs for deterministic product flows such as video/detail extraction, comments, search, account posts, rankings, and monitoring. Keep TikHub calls centralized, configurable by base URL (`api.tikhub.io` or `api.tikhub.dev`), cached where reasonable, and covered by mocked fast tests. Treat TikHub MCP as an agent research tool for Codex/Claude Code exploration, not as the default synchronous API path.

## Web Shell

History cleanup uses `POST /api/audit/history/remove` and per-user `task_history_hidden` entries. Remove only selected task IDs from recent/history lists, counts and filters; preserve shared results, original files and audit logs. Never wire history cleanup to the destructive task/cache deletion endpoint. Offline checks are listed under history cleanup in `tests/README.md`.

New-install setup uses `scripts/init_config.py`: preserve existing configuration, generate a unique token, and default to loopback. Bootstrap defaults to text learning; media, local Whisper, OCR and dev dependencies are optional. Public documentation captures use `scripts/capture_readme.py` and the isolated public-source and authored fixtures in `scripts/readme_demo.py` and `scripts/readme_cases.py`, never the live application database or configuration. Capture provenance is in `docs/images/readme-20261103-cases/README.md`; user-provided local screenshots are documented separately in `docs/images/readme-20261103-real/README.md` and must not be overwritten by demo captures.

Product navigation data comes from `src/web/product-navigation.json`; synchronize with `uv run python scripts/sync_product_navigation.py` and verify with `--check`. Every product shell uses the shared `app-shell.js`, `app-shell.css`, and `workbench-wildwood.css`; Jinja pages inherit the theme from `base.html`, with page finishing styles in `page_styles`. Page adapters must not override sidebar dimensions, brand, navigation spacing or active states. `api/assets.py` owns CSS/JS content versions for both runtime pages and the generator: do not add per-route asset lists. Static HTML/CSS/JS must revalidate, and Service Worker network reads must bypass HTTP cache while retaining offline fallback. Verify regressions with `uv run --extra dev pytest tests/unit/test_frontend_asset_cache.py tests/unit/test_unified_product_shell.py tests/unit/test_product_linear_ui.py tests/unit/test_transcript_mobile_layout.py -q`; report any unrelated failures without hiding them.

## GitNexus Impact Checks

Manual GPT Image diagrams live in `image_diagrams/` and `api/routes/image_diagrams.py`; read `docs/guides/image-diagrams.md`. Page loads and GETs must never trigger paid work. Images complete as soon as they are saved: no post-generation model review or review entry points. Short sources go directly to image generation; long sources use one planning call when within budget, and reuse unchanged briefs. Do not replay ambiguous image submissions, overwrite older images or log secrets. Source ownership (including Feishu CLI identity) must be checked before reading snapshots. Persistent image files must stay outside ASR temporary cleanup.
Before modifying shared functions, classes, FastAPI handlers, downloader/transcriber/cache logic, task queues, webhooks, authentication, authorization, storage, or other high-impact code, inspect the target with GitNexus `context` and run GitNexus `impact` upstream when this repository is indexed. If the index is missing or stale, run `gitnexus analyze --skip-agents-md --skip-skills --workers 1` from the repository root before relying on graph results. After edits to indexed code, run GitNexus `detect_changes` plus the relevant verification command above.
