"""Regression tests for the standalone LearnFlux Agent Skill CLI."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path
from urllib import error as urlerror

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "skill" / "scripts" / "videotranscript.py"
EVALS_PATH = ROOT / "skill" / "evals" / "evals.json"

SPEC = importlib.util.spec_from_file_location("learnflux_skill_cli", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

ENV_NAMES = (
    "LEARNFLUX_AGENT_CONFIG",
    "VIDEO_TRANSCRIPT_API_BASE_URL",
    "VIDEO_TRANSCRIPT_API_TOKEN",
    "VIDEO_TRANSCRIPT_API_PUBLIC_URL",
    "VIDEO_TRANSCRIPT_API_WECHAT_WEBHOOK",
    "VIDEO_TRANSCRIPT_API_FEISHU_WEBHOOK",
)


@pytest.fixture(autouse=True)
def _reset_skill_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    cli._env_loaded = False


def test_loads_agent_config_without_overwriting_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".learnflux"
    config_dir.mkdir()
    (config_dir / "agent.env").write_text(
        "VIDEO_TRANSCRIPT_API_BASE_URL=http://from-file:8000\n"
        "VIDEO_TRANSCRIPT_API_TOKEN=file-token\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_BASE_URL", "http://explicit:8000")

    cli._load_env_files()

    assert cli._base_url() == "http://explicit:8000"
    assert cli._auth_headers() == {"Authorization": "Bearer file-token"}


def test_request_can_return_an_expected_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_BASE_URL", "http://learnflux.test")

    def raise_failed_task(*_args, **_kwargs):
        raise urlerror.HTTPError(
            "http://learnflux.test/view/private-token?raw=summary",
            500,
            "Internal Server Error",
            {},
            io.BytesIO("task failed".encode()),
        )

    monkeypatch.setattr(cli.urlrequest, "urlopen", raise_failed_task)

    status, body = cli._request(
        "GET",
        "/view/private-token",
        auth=False,
        accept_text=True,
        passthrough_statuses=(500,),
    )

    assert status == 500
    assert body == "task failed"


def test_result_reports_failed_task_as_business_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: (500, "failed"))

    exit_code = cli.main(["result", "private-token"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "任务处理失败" in captured.err
    assert "private-token" not in captured.err


def test_result_does_not_echo_invalid_view_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: (404, "missing"))

    exit_code = cli.main(["result", "private-view-token"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "view_token 无效或已过期" in captured.err
    assert "private-view-token" not in captured.err


def test_submit_preserves_queue_full_error_classification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: (503, {"detail": "full"}))

    exit_code = cli.main(["submit", "https://example.com/video"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "任务队列已满" in captured.err


def test_submit_json_contract_remains_backward_compatible(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_BASE_URL", "http://127.0.0.1:8000")
    captured_request = {}

    def fake_request(method: str, path: str, **kwargs):
        captured_request.update({"method": method, "path": path, **kwargs})
        return 202, {
            "code": 202,
            "data": {"task_id": "task-1", "view_token": "view-1"},
        }

    monkeypatch.setattr(cli, "_request", fake_request)

    exit_code = cli.main(
        [
            "submit",
            "https://example.com/video",
            "--speaker",
            "--title",
            "Example",
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured_request["method"] == "POST"
    assert captured_request["path"] == "/api/transcribe"
    assert captured_request["json_body"] == {
        "url": "https://example.com/video",
        "use_speaker_recognition": True,
        "metadata_override": {"title": "Example"},
    }
    assert payload["task_id"] == "task-1"
    assert payload["view_token"] == "view-1"
    assert payload["view_url"] == "http://127.0.0.1:8000/view/view-1"


def test_pending_result_has_machine_readable_state_and_exact_view_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: (202, "processing"))

    exit_code = cli.main(["result", "view-1", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "ready": False,
        "http_status": 202,
        "view_url": "http://127.0.0.1:8000/view/view-1",
        "text": "processing",
    }


def test_doctor_verifies_connectivity_without_printing_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "do-not-print-this-token"
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_TOKEN", secret)

    def fake_request(_method: str, path: str, **_kwargs):
        if path == "/health":
            return 200, {"status": "healthy"}
        if path == "/api/users/profile":
            return 200, {
                "code": 200,
                "data": {
                    "user_info": {"user_id": "legacy_user", "api_key": "masked***"},
                    "is_multi_user_mode": False,
                },
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(cli, "_request", fake_request)

    exit_code = cli.main(["doctor", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert any(check["name"] == "authentication" for check in payload["checks"])
    assert any(warning["code"] == "legacy_admin_token" for warning in payload["warnings"])
    assert secret not in captured.out
    assert secret not in captured.err


def test_doctor_rejects_base_url_without_http_scheme(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_BASE_URL", "localhost:8000")
    monkeypatch.setenv("VIDEO_TRANSCRIPT_API_TOKEN", "configured")

    exit_code = cli.main(["doctor", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["ready"] is False
    assert payload["checks"][0]["status"] == "error"


def test_eval_manifest_targets_installed_skill_name() -> None:
    manifest = json.loads(EVALS_PATH.read_text(encoding="utf-8"))

    assert manifest["skill_name"] == "learnflux"
    assert len({case["id"] for case in manifest["evals"]}) == len(manifest["evals"])


def test_existing_cli_commands_remain_available() -> None:
    parser = cli._build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert {
        "submit",
        "status",
        "result",
        "history",
        "filter-options",
        "profile",
        "health",
    }.issubset(subparsers.choices)
