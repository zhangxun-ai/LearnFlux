过程中请使用中文和我沟通，但 console 里请优先使用英文。
# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/video_transcript_api`: `api/server.py` hosts FastAPI, `downloaders/` contains platform adapters, `transcriber/` wraps CapsWriter and FunASR clients, and `utils/` now splits into focused subpackages (`logging/`, `cache/`, `llm/`, `rendering/`, `notifications/`, `accounts/`, `timeutil/`, `risk_control/`). Templates remain in `src/web/templates`. Tests are separated within `tests/` by scope (unit, integration, performance, manual, llm, cache, features, platforms). Configuration examples sit in `config/*.example.json`, while live secrets stay in `config/config.json`. Runtime caches, SQLite stores, and logs go to `data/`; automation helpers live in `scripts/`. Launch the API through `main.py`.

## Build, Test, and Development Commands

Use uv for dependency management and command execution.

```bash
# Install project and test dependencies
uv sync --extra dev

# Start the API
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

## Testing Guidelines
Use pytest. `verify-fast` covers unit tests; `verify-full` covers the default offline suite. Feature, integration, LLM, platform, manual, and performance tests must be run explicitly. Mock CapsWriter, FunASR, TikHub, and WeCom clients in fast feedback tests. Redirect transient media into `tests/cache/` and clean up afterward to avoid polluting `data/`. Update `tests/README.md` when you add new suites or flags.

## Commit & Pull Request Guidelines
Commit messages follow the current log style: concise, imperative Chinese summaries (`修复 API 并发重试`). Group related edits before opening a PR. PR descriptions should outline scope, note config or schema touchpoints, reference issues with `#123`, and attach evidence (pytest output, manual steps, API samples). Flag any follow-up actions such as restarting services or updating `config/config.json`.

## Security & Configuration Notes
Do not commit live credentials; extend `config.example.json` and document defaults instead. Keep generated artifacts in `data/` and `logs/` out of patches unless troubleshooting. When working with remote transcription servers, load tokens from environment variables and clear `data/temp` via `scripts/cleanup_cache.py` after tests so sensitive media does not linger.

## Social Data & TikHub Usage
For new social-media data features, first evaluate TikHub REST APIs for deterministic product flows such as video/detail extraction, comments, search, account posts, rankings, and monitoring. Keep TikHub calls centralized, configurable by base URL (`api.tikhub.io` or `api.tikhub.dev`), cached where reasonable, and covered by mocked fast tests. Treat TikHub MCP as an agent research tool for Codex/Claude Code exploration, not as the default synchronous API path.

## GitNexus Impact Checks
Before modifying shared functions, classes, FastAPI handlers, downloader/transcriber/cache logic, task queues, webhooks, authentication, authorization, storage, or other high-impact code, inspect the target with GitNexus `context` and run GitNexus `impact` upstream when this repository is indexed. If the index is missing or stale, run `gitnexus analyze --skip-agents-md --skip-skills --workers 1` from the repository root before relying on graph results. After edits to indexed code, run GitNexus `detect_changes` plus the relevant verification command above.
