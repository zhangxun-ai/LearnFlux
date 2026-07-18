# Codex Workflow Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a smaller, enforceable Codex operating contract and one valid verification path for VideoTranscriptAPI.

**Architecture:** Global behavior lives in `~/.codex/AGENTS.md`; repository-specific facts stay in the repository. The project uses existing uv extras and pytest directly, avoiding a new task runner or dependency.

**Tech Stack:** Markdown, Python 3.11, uv, pytest, Codex thread tools.

---

### Task 1: Lock the project workflow contract with a failing test

**Files:**
- Create: `tests/unit/test_project_workflow_docs.py`

- [ ] Add assertions that the canonical setup command is `uv sync --extra dev`, `uv run --extra dev pytest tests/unit` and `uv run --extra dev pytest` are documented, features/integration/llm/manual/performance/platforms suites are excluded by default, and stale `requirements.txt`, `scripts/run_tests.py`, and `--skip-embeddings` instructions are absent.
- [ ] Run `uv run --extra dev pytest tests/unit/test_project_workflow_docs.py -q` and confirm failure against the current documentation.

### Task 2: Make project documentation one consistent source of truth

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `tests/README.md`
- Modify: `pyproject.toml`
- Delete: `scripts/run_tests.py`

- [ ] Replace setup instructions with `uv sync --extra dev`.
- [ ] Define `uv run --extra dev pytest tests/unit` as fast verification and `uv run --extra dev pytest` as the default offline full verification.
- [ ] Exclude features, integration, llm, manual, performance, and platforms suites from default pytest discovery; document explicit per-file invocation for them.
- [ ] Remove the broken unittest wrapper, nonexistent `requirements.txt` path, and obsolete GitNexus flag.
- [ ] Reduce `CLAUDE.md` to tool-specific deltas that defer project facts to `AGENTS.md`.
- [ ] Run the workflow contract test and confirm it passes.

### Task 3: Add the global Codex execution contract

**Files:**
- Modify: `/Users/zhanghanting/.codex/AGENTS.md`

- [ ] Add the five-field task contract: mode, goal, out of scope, done condition, verification budget.
- [ ] Add one-deliverable-per-thread, scope-change, WIP, worktree, title, and completion rules.
- [ ] Add a short default tool route and prohibit installing skills during unrelated product work.
- [ ] Remove duplicated closing rules where the new contract makes them redundant.
- [ ] Verify the required headings and rules with `rg`.

### Task 4: Apply the task lifecycle safely

**State changes:**
- Rename the current task to `[Codex] 简化工作流`.
- Review stale task candidates without changing uncertain tasks.

- [ ] Rename the current task using the Codex thread title tool.
- [ ] Archive only candidates that have direct evidence of completion and at least 90 days of inactivity.
- [ ] If completion cannot be verified, report the limitation instead of archiving.

### Task 5: Verify the integrated result

**Verification:**

- [ ] Run `uv run --extra dev pytest tests/unit/test_project_workflow_docs.py -q`.
- [ ] Run `uv run --extra dev pytest tests/unit -q`.
- [ ] Run `uv run --extra dev pytest --collect-only -q`; fail the verification if output contains any opt-in suite directory.
- [ ] Only after the collection gate passes, run `uv run --extra dev pytest -q`.
- [ ] Run documentation searches for stale commands.
- [ ] Review `git diff --check`, `git status --short`, and `git diff --stat`.
- [ ] Confirm no files under `src/` changed.

No commit is included because the repository instructions require explicit user authorization before committing.
