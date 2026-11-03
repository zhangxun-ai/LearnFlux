"""Offline checks for copyable defaults and private-file Git exclusions."""

from pathlib import Path
import subprocess

from dotenv import dotenv_values
import pytest

from video_transcript_api.transcriber.online_runtime import OnlineRuntimeSettings


ROOT = Path(__file__).resolve().parents[2]


def test_environment_template_runs_locally_without_service_credentials():
    values = dotenv_values(ROOT / ".env.example", interpolate=False)
    settings = OnlineRuntimeSettings.from_environ(values)
    assert settings.persistence_backend == "sqlite"
    assert settings.object_backend == "local"
    credentials = {
        "DATABASE_URL", "POSTGRES_URL", "POSTGRES_USER", "POSTGRES_PASSWORD",
        "LEARNFLUX_S3_ACCESS_KEY_ID", "LEARNFLUX_S3_SECRET_ACCESS_KEY",
        "DASHSCOPE_API_KEY", "DASHSCOPE_WORKSPACE_ID", "DASHSCOPE_API_HOST", "GROQ_API_KEY",
        "LEARNFLUX_LLM_API_KEY", "LEARNFLUX_AUTH_TOKEN", "LEARNFLUX_TIKHUB_API_KEY",
        "LEARNFLUX_YOUTUBE_API_KEY", "LEARNFLUX_LLM_COLLECTOR_API_KEY",
        "OPENAI_API_KEY",
    }
    assert all(values[name] == "" for name in credentials)
    # Empty path overrides suppress these integrations' actual default paths.
    assert "LEARNFLUX_FEISHU_ARCHIVE_CONFIG" not in values
    assert "LEARNFLUX_BRIEFINGS_CONFIG" not in values


@pytest.mark.parametrize("path", [
    ".env", ".env.local", ".env.production", ".env.backup", "nested/.env.local",
    "config/config.json", "config/config.jsonc", "config/config.jsonc.backup",
    "config/users.json", "config/users.json.bak", "config/config.overrides.json",
    "data/config.db", "cookies.txt", "youtube_cookies.txt",
])
def test_private_configuration_and_cookie_exports_are_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"], cwd=ROOT,
        input=f"{path}\n", text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"Private path is not ignored: {path}"
    assert result.stdout.strip() == path


@pytest.mark.parametrize("path", [
    ".env.example", "config/config.example.jsonc", "config/users.example.json",
])
def test_public_templates_remain_available_to_git(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"], cwd=ROOT,
        input=f"{path}\n", text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1, f"Public template was ignored: {path}"
