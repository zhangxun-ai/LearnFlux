from pathlib import Path
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATED_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "docs/README.md",
    "tests/README.md",
    "pyproject.toml",
)
CANONICAL_COMMANDS = (
    "uv sync --extra dev",
    "uv run --extra dev pytest tests/unit",
    "uv run --extra dev pytest",
)
AUDIENCE_DOC_COMMANDS = (
    ("README.md", ("uv sync --extra dev",)),
    (
        "tests/README.md",
        (
            "uv run --extra dev pytest tests/unit",
            "uv run --extra dev pytest",
        ),
    ),
)
LEGACY_WORKFLOW_TEXT = (
    "scripts/run_tests.py",
    "requirements.txt",
    "--skip-embeddings",
    "python -m pytest",
    "bundled unittest runner",
    "使用 unittest",
)


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_standalone_commands(relative_path: str, commands: tuple[str, ...]) -> None:
    documented_lines = {line.strip() for line in _read(relative_path).splitlines()}
    missing = [command for command in commands if command not in documented_lines]

    assert not missing, (
        f"{relative_path} is missing canonical standalone command lines: "
        f"{', '.join(missing)}"
    )


def test_agents_md_defines_all_canonical_workflow_commands():
    _assert_standalone_commands("AGENTS.md", CANONICAL_COMMANDS)


@pytest.mark.parametrize(
    ("relative_path", "commands"),
    AUDIENCE_DOC_COMMANDS,
    ids=("project-readme-setup", "tests-readme-test-commands"),
)
def test_audience_docs_show_relevant_canonical_commands(relative_path, commands):
    _assert_standalone_commands(relative_path, commands)


def test_pytest_norecursedirs_lists_non_default_suites():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    excluded = set(pyproject["tool"]["pytest"]["ini_options"]["norecursedirs"])
    required = {
        "features",
        "integration",
        "llm",
        "manual",
        "performance",
        "platforms",
    }

    assert required <= excluded, (
        "pyproject.toml [tool.pytest.ini_options].norecursedirs is missing: "
        f"{', '.join(sorted(required - excluded))}"
    )


@pytest.mark.parametrize("relative_path", MIGRATED_FILES)
def test_migrated_files_omit_known_legacy_workflow_text(relative_path):
    contents = _read(relative_path)
    remaining = [text for text in LEGACY_WORKFLOW_TEXT if text in contents]

    assert not remaining, (
        f"{relative_path} still contains legacy workflow text: "
        f"{', '.join(remaining)}"
    )


def test_legacy_test_runner_has_been_removed():
    legacy_runner = PROJECT_ROOT / "scripts/run_tests.py"

    assert not legacy_runner.exists(), (
        "scripts/run_tests.py must be removed after the pytest workflow migration"
    )
