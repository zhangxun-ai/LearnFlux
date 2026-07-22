"""Unit tests for the offline remote ASR benchmark rules."""

from decimal import Decimal
import hashlib
from io import BytesIO
from importlib import import_module
import json
import os
from pathlib import Path

import pytest
import requests


def _lib():
    try:
        return import_module("tests.performance.remote_asr_benchmark_lib")
    except ModuleNotFoundError:
        pytest.fail("remote ASR benchmark library is not implemented")


def _cli():
    try:
        return import_module("tests.performance.remote_asr_benchmark")
    except ModuleNotFoundError:
        pytest.fail("remote ASR benchmark CLI is not implemented")


def _manifest():
    manifest_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "remote_asr_benchmark"
        / "manifest.json"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _call(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get(self, url, **kwargs):
        return self._call("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._call("POST", url, **kwargs)


def test_chinese_normalization_and_cer():
    lib = _lib()

    assert lib.normalize_chinese(" 你，好！ＡI 2026。") == "你好ai2026"
    assert lib.character_error_rate("你好世界", "你好世") == pytest.approx(0.25)


def test_english_normalization_and_wer():
    lib = _lib()

    assert lib.normalize_english("  Hello,   WORLD! It's 2026. ") == "hello world it's 2026"
    assert lib.word_error_rate("one two three", "one too three") == pytest.approx(1 / 3)


@pytest.mark.parametrize("metric_name", ["character_error_rate", "word_error_rate"])
def test_error_rates_reject_empty_normalized_reference(metric_name):
    metric = getattr(_lib(), metric_name)

    with pytest.raises(ValueError, match="reference"):
        metric(" ... ", "hypothesis")


def test_terms_are_reported_individually_after_language_normalization():
    lib = _lib()

    assert lib.term_hits(["大模型", "语音识别", "缺席术语"], "大模型，语音识别！", "zh") == [
        True,
        True,
        False,
    ]
    assert lib.term_hits(["ASR", "speech to text", "text"], "An ASR speech-to-text result", "en") == [
        True,
        True,
        True,
    ]


def test_funasr_cost_uses_full_audio_for_reservation_and_usage_for_settlement():
    lib = _lib()

    assert lib.funasr_worst_case_cost_cny(125.5) == Decimal("0.027610")
    assert lib.funasr_terminal_cost_cny(100) == Decimal("0.02200")


def test_groq_applies_ten_second_minimum_to_every_request_and_chunk():
    lib = _lib()

    assert lib.groq_request_cost_usd(3) == Decimal("0.0001111111111111111111111111111")
    assert lib.groq_chunked_cost_usd([3, 12, 1]) == Decimal("0.0003555555555555555555555555555")


def test_manifest_builds_stable_full_action_matrix_and_exact_worst_case_budget():
    lib = _lib()

    actions = lib.build_action_matrix(_manifest())
    aliyun = [action for action in actions if action.provider == "aliyun"]
    groq = [action for action in actions if action.provider == "groq"]

    assert len(aliyun) == 14
    assert len(groq) == 15
    assert len({action.action_id for action in actions}) == len(actions)
    assert all(action.attempt_id and action.action_id for action in actions)
    assert sum((action.duration_seconds for action in aliyun), Decimal("0")) == Decimal(
        "2442.106313"
    )
    assert sum((action.worst_case_cost for action in aliyun), Decimal("0")) == Decimal(
        "0.53726338886"
    )
    assert sum((action.duration_seconds for action in groq), Decimal("0")) == Decimal(
        "2146.106313"
    )
    groq_cost = sum((action.worst_case_cost for action in groq), Decimal("0"))
    assert groq_cost == lib.groq_chunked_cost_usd(
        action.duration_seconds for action in groq
    )
    assert float(groq_cost) == pytest.approx(0.0238456257)
    assert [
        action.duration_seconds
        for action in groq
        if action.sample_id == "long_natural_20_60m"
    ] == [Decimal("600"), Decimal("600"), Decimal("256.106313")]

    smoke_actions = lib.build_action_matrix(
        _manifest(),
        providers="aliyun,groq",
        sample_ids="zh_terms_clean_15s",
        repeats=1,
        variants="main",
    )
    assert len(smoke_actions) == 2
    assert [action.provider for action in smoke_actions] == ["aliyun", "groq"]
    assert {action.variant for action in smoke_actions} == {"main"}


def test_run_gate_blocks_without_touching_credentials_or_executor():
    lib = _lib()
    awaiting_manifest = {**_manifest(), "status": "awaiting_reference_review"}
    confirmed_manifest = {**awaiting_manifest, "status": "confirmed"}
    scenarios = [
        {
            "manifest": awaiting_manifest,
            "execute_paid": False,
            "max_cny": "1",
            "max_usd": "0.1",
        },
        {
            "manifest": awaiting_manifest,
            "execute_paid": True,
            "max_cny": "1",
            "max_usd": "0.1",
        },
        {
            "manifest": confirmed_manifest,
            "execute_paid": True,
            "max_cny": None,
            "max_usd": "0.1",
        },
        {
            "manifest": confirmed_manifest,
            "execute_paid": True,
            "max_cny": "invalid",
            "max_usd": "0.1",
        },
        {
            "manifest": confirmed_manifest,
            "execute_paid": True,
            "max_cny": "0.5",
            "max_usd": "0.1",
        },
        {
            "manifest": confirmed_manifest,
            "execute_paid": True,
            "max_cny": "1",
            "max_usd": "0.1",
            "providers": ("unknown",),
        },
        {
            "manifest": {"schema_version": 99, "status": "confirmed", "samples": []},
            "execute_paid": True,
            "max_cny": "1",
            "max_usd": "0.1",
        },
    ]

    for scenario in scenarios:
        calls = {"credentials": 0, "executor": 0}

        def read_credentials():
            calls["credentials"] += 1
            return {"api_key": "must-not-be-read"}

        def execute(*_args):
            calls["executor"] += 1

        summary = lib.run_action_matrix(
            credential_reader=read_credentials,
            external_executor=execute,
            **scenario,
        )

        assert summary["status"] == "blocked"
        assert summary["required_budget"]
        assert summary["blocked_reasons"]
        assert calls == {"credentials": 0, "executor": 0}


def test_execute_paid_reserves_each_action_before_injected_executor():
    lib = _lib()
    manifest = {**_manifest(), "status": "confirmed"}
    actions = lib.build_action_matrix(manifest)
    observed = []
    credential_calls = 0

    def read_credentials():
        nonlocal credential_calls
        credential_calls += 1
        return object()

    def execute(action, _credentials, ledger):
        assert ledger.reserved == action.worst_case_cost
        observed.append(action.action_id)
        return {"actual_cost": action.worst_case_cost / 2}

    summary = lib.run_action_matrix(
        manifest=manifest,
        execute_paid=True,
        max_cny="1",
        max_usd="0.1",
        credential_reader=read_credentials,
        external_executor=execute,
    )

    assert summary["status"] == "completed"
    assert credential_calls == 1
    assert observed == [action.action_id for action in actions]
    for currency in ("CNY", "USD"):
        expected_spent = sum(
            (
                action.worst_case_cost / 2
                for action in actions
                if action.currency == currency
            ),
            Decimal("0"),
        )
        assert summary["budget_state"][currency]["spent"] == str(expected_spent)
        assert Decimal(summary["budget_state"][currency]["reserved"]) == 0


def test_aliyun_timeout_persists_unknown_blocks_new_run_and_resumes_same_task(
    tmp_path,
):
    lib = _lib()
    sample_id = "zh_terms_clean_15s"
    audio = b"fLaC\x00resume-smoke-audio"
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    (samples_dir / f"{sample_id}.flac").write_bytes(audio)
    manifest = json.loads(json.dumps(_manifest()))
    manifest["status"] = "confirmed"
    for sample in manifest["samples"]:
        if sample["id"] == sample_id:
            sample["size_bytes"] = len(audio)
            sample["sha256"] = hashlib.sha256(audio).hexdigest()

    recovery_store = lib.RecoveryStore(tmp_path / "recovery.json")
    results_path = tmp_path / "results.json"
    calls = {"credentials": 0, "clients": 0, "upload": 0, "submit": 0, "poll": 0}
    task_id = "aliyun-task-resume-1"

    class FakeAliyunClient:
        def upload_audio(self, audio_file, filename, content_type):
            calls["upload"] += 1
            assert audio_file.read() == audio
            return "oss://temporary-object"

        def submit(self, staged_uri, language_hints):
            calls["submit"] += 1
            return {"task_id": task_id, "status": "PENDING"}

        def poll(self, supplied_task_id):
            calls["poll"] += 1
            assert supplied_task_id == task_id
            if calls["poll"] == 1:
                raise lib.PollTimeoutError("poll_timeout")
            return {
                "task_id": task_id,
                "status": "SUCCEEDED",
                "usage_seconds": 12.5,
                "results": [
                    {
                        "status": "SUCCEEDED",
                        "transcript": {
                            "text": "Resumed Aliyun text",
                            "sentences": [
                                {
                                    "text": "Resumed Aliyun text",
                                    "start_time": 0,
                                    "end_time": 1.25,
                                }
                            ],
                        },
                    }
                ],
            }

    client = FakeAliyunClient()

    def client_factory(provider, credentials):
        calls["clients"] += 1
        assert provider == "aliyun"
        assert credentials == {"api_key": "aliyun-secret"}
        return client

    def read_credentials():
        calls["credentials"] += 1
        return {"aliyun": {"api_key": "aliyun-secret"}}

    executor = lib.BenchmarkSmokeExecutor(
        manifest=manifest,
        samples_dir=samples_dir,
        recovery_store=recovery_store,
        results_path=results_path,
        budgets={"CNY": "1", "USD": "0.1"},
        client_factory=client_factory,
        clock=lambda: 1234.5,
    )

    summary = lib.run_action_matrix(
        manifest=manifest,
        execute_paid=True,
        max_cny="1",
        max_usd="0.1",
        providers="aliyun",
        sample_ids=sample_id,
        repeats=1,
        variants="main",
        credential_reader=read_credentials,
        external_executor=executor,
    )

    assert summary["status"] == "unknown"
    assert summary["actions"][-1]["status"] == "unknown"
    pending = recovery_store.load()["attempts"]
    assert len(pending) == 1
    assert pending[0]["state"] == "unknown"
    assert pending[0]["task_id"] == task_id
    assert pending[0]["sample_id"] == sample_id

    calls_after_timeout = dict(calls)
    blocked = lib.run_action_matrix(
        manifest=manifest,
        execute_paid=True,
        max_cny="1",
        max_usd="0.1",
        providers="aliyun",
        sample_ids=sample_id,
        repeats=1,
        variants="main",
        credential_reader=read_credentials,
        external_executor=executor,
    )
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reasons"] == ["pending_recovery"]
    assert calls == calls_after_timeout

    resumed = executor.resume_pending_aliyun(read_credentials)

    assert resumed["status"] == "completed"
    assert calls == {
        "credentials": 2,
        "clients": 2,
        "upload": 1,
        "submit": 1,
        "poll": 2,
    }
    assert not recovery_store.path.exists()
    result = json.loads(results_path.read_text(encoding="utf-8"))["results"][0]
    assert result["sample_id"] == sample_id
    assert result["provider_id_sha256"] == hashlib.sha256(
        task_id.encode("utf-8")
    ).hexdigest()
    rendered = json.dumps(
        {"summary": summary, "resumed": resumed, "result": result}
    ).casefold()
    for forbidden in (
        "aliyun-secret",
        task_id,
        "authorization",
        "https://",
        "api_key",
        "path",
    ):
        assert forbidden not in rendered


def test_cli_parser_exposes_benchmark_subcommands_and_paid_run_flags():
    cli = _cli()
    parser = cli.build_parser()

    for command in ("prepare", "resume-task", "report", "cleanup"):
        assert parser.parse_args([command]).command == command

    args = parser.parse_args(
        [
            "run",
            "--provider",
            "aliyun,groq",
            "--samples",
            "zh_terms_clean_15s,en_clean_90s",
            "--repeats",
            "2",
            "--max-cny",
            "1",
            "--max-usd",
            "0.1",
            "--execute-paid",
            "--retry-unknown",
        ]
    )
    assert args.command == "run"
    assert args.execute_paid is True
    assert args.retry_unknown is True


@pytest.mark.parametrize("provider", ["aliyun", "groq"])
def test_smoke_executor_runs_verified_local_main_action_and_persists_safe_result(
    provider,
    tmp_path,
    monkeypatch,
):
    lib = _lib()
    sample_id = "zh_terms_clean_15s"
    audio = b"fLaC\x00offline-smoke-audio"
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    audio_path = samples_dir / f"{sample_id}.flac"
    audio_path.write_bytes(audio)
    sample_sha256 = hashlib.sha256(audio).hexdigest()
    manifest = json.loads(json.dumps(_manifest()))
    manifest["status"] = "confirmed"
    for sample in manifest["samples"]:
        if sample["id"] == sample_id:
            sample["size_bytes"] = len(audio)
            sample["sha256"] = sample_sha256

    secrets = {
        "DASHSCOPE_API_KEY": "aliyun-key-secret",
        "DASHSCOPE_WORKSPACE_ID": "workspace-1",
        "DASHSCOPE_API_HOST": (
            "https://workspace-1.cn-beijing.maas.aliyuncs.com"
        ),
        "GROQ_API_KEY": "groq-key-secret",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    recovery_path = tmp_path / "recovery.json"
    results_path = tmp_path / "results.json"
    events = []
    provider_id = f"{provider}-raw-provider-id"

    class TrackingRecoveryStore(lib.RecoveryStore):
        def settle_terminal(self, action_id, actual_cost, currency):
            assert results_path.exists()
            events.append("recovery_settle")
            return super().settle_terminal(action_id, actual_cost, currency)

    recovery_store = TrackingRecoveryStore(recovery_path)

    class FakeAliyunClient:
        def upload_audio(self, audio_file, filename, content_type):
            assert recovery_path.exists()
            assert audio_file.read() == audio
            assert filename == f"{sample_id}.flac"
            assert content_type == "audio/flac"
            events.append("upload")
            return "oss://temporary-staged-object"

        def submit(self, staged_uri, language_hints):
            assert staged_uri == "oss://temporary-staged-object"
            assert language_hints == ["zh"]
            events.append("submit")
            return {
                "task_id": provider_id,
                "request_id": "aliyun-submit-request-id",
                "status": "PENDING",
            }

        def poll(self, task_id):
            assert task_id == provider_id
            recovery = recovery_store.load()
            assert recovery["attempts"][0]["task_id"] == provider_id
            events.append("poll")
            return {
                "task_id": provider_id,
                "request_id": "aliyun-terminal-request-id",
                "status": "SUCCEEDED",
                "usage_seconds": 12.5,
                "results": [
                    {
                        "status": "SUCCEEDED",
                        "transcript": {
                            "text": "Aliyun smoke text",
                            "sentences": [
                                {
                                    "text": "Aliyun smoke text",
                                    "start_time": 0,
                                    "end_time": 1.25,
                                }
                            ],
                        },
                    }
                ],
            }

    class FakeGroqClient:
        def transcribe(self, audio_file, filename, language, **kwargs):
            assert recovery_path.exists()
            assert audio_file.read() == audio
            assert filename == f"{sample_id}.flac"
            assert language == "zh"
            assert kwargs == {"content_type": "audio/flac"}
            events.append("transcribe")
            return {
                "request_id": provider_id,
                "text": "Groq smoke text",
                "duration": 99,
                "segments": [
                    {"start": 0, "end": 1.25, "text": "Groq smoke text"}
                ],
                "words": [{"start": 0, "end": 0.5, "word": "Groq"}],
            }

    def client_factory(selected_provider, credentials):
        snapshot = recovery_store.load()
        assert snapshot["attempts"][0]["state"] == "reserved"
        assert selected_provider == provider
        if provider == "aliyun":
            assert credentials == {
                "api_key": secrets["DASHSCOPE_API_KEY"],
                "workspace_id": secrets["DASHSCOPE_WORKSPACE_ID"],
                "api_host": secrets["DASHSCOPE_API_HOST"],
            }
            return FakeAliyunClient()
        assert credentials == {"api_key": secrets["GROQ_API_KEY"]}
        return FakeGroqClient()

    executor = lib.BenchmarkSmokeExecutor(
        manifest=manifest,
        samples_dir=samples_dir,
        recovery_store=recovery_store,
        results_path=results_path,
        budgets={"CNY": "1", "USD": "0.1"},
        client_factory=client_factory,
        clock=lambda: 1234.5,
    )
    summary = lib.run_action_matrix(
        manifest=manifest,
        execute_paid=True,
        max_cny="1",
        max_usd="0.1",
        providers=provider,
        sample_ids=sample_id,
        repeats=1,
        variants="main",
        credential_reader=lib.read_remote_credentials_from_environment,
        external_executor=executor,
    )

    assert summary["status"] == "completed"
    assert summary["action_count"] == 1
    assert events == (
        ["upload", "submit", "poll", "recovery_settle"]
        if provider == "aliyun"
        else ["transcribe", "recovery_settle"]
    )
    assert not recovery_path.exists()
    assert oct(os.stat(results_path).st_mode & 0o777) == "0o600"
    result = json.loads(results_path.read_text(encoding="utf-8"))["results"][0]
    assert set(result) == {
        "action_id",
        "completed_at",
        "cost",
        "model",
        "provider",
        "provider_id_sha256",
        "sample_id",
        "text_chars",
        "text_sha256",
        "timestamp_summary",
        "usage",
    }
    assert result["provider"] == provider
    assert result["sample_id"] == sample_id
    assert result["action_id"].startswith(f"{provider}:{sample_id}:main:")
    assert result["model"] == (
        lib.FUNASR_MODEL if provider == "aliyun" else lib.GROQ_MODEL
    )
    expected_text = (
        "Aliyun smoke text" if provider == "aliyun" else "Groq smoke text"
    )
    assert result["text_chars"] == len(expected_text)
    assert result["text_sha256"] == hashlib.sha256(
        expected_text.encode("utf-8")
    ).hexdigest()
    assert result["timestamp_summary"]
    rendered_result = json.dumps(result, ensure_ascii=False)
    assert expected_text not in rendered_result
    assert "Timestamped" not in rendered_result
    assert result["usage"] == {
        "seconds": "12.5" if provider == "aliyun" else "15.0"
    }
    expected_cost = (
        lib.funasr_terminal_cost_cny("12.5")
        if provider == "aliyun"
        else lib.groq_request_cost_usd("15.0")
    )
    assert result["cost"] == {
        "amount": str(expected_cost),
        "currency": "CNY" if provider == "aliyun" else "USD",
    }
    assert result["provider_id_sha256"] == hashlib.sha256(
        provider_id.encode("utf-8")
    ).hexdigest()
    rendered_artifacts = results_path.read_text(encoding="utf-8").casefold()
    rendered_summary = json.dumps(summary, sort_keys=True).casefold()
    for forbidden in (
        provider_id,
        "submit-request-id",
        "terminal-request-id",
        "temporary-staged-object",
        "authorization",
        "api_key",
        "https://",
        str(audio_path).casefold(),
        "key-secret",
    ):
        assert forbidden not in rendered_artifacts
        assert forbidden not in rendered_summary


def test_benchmark_executor_preflight_accepts_verified_multi_speaker_main_action(
    tmp_path,
):
    lib = _lib()
    sample_id = "multi_speaker_5m"
    audio = b"fLaC\x00verified-multi-speaker-audio"
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    (samples_dir / f"{sample_id}.flac").write_bytes(audio)
    manifest = json.loads(json.dumps(_manifest()))
    manifest["status"] = "confirmed"
    for sample in manifest["samples"]:
        if sample["id"] == sample_id:
            sample["size_bytes"] = len(audio)
            sample["sha256"] = hashlib.sha256(audio).hexdigest()
    action = lib.build_action_matrix(
        manifest,
        providers="aliyun",
        sample_ids=sample_id,
        repeats=1,
        variants="main",
    )[0]
    executor = lib.BenchmarkSmokeExecutor(
        manifest=manifest,
        samples_dir=samples_dir,
        recovery_store=lib.RecoveryStore(tmp_path / "recovery.json"),
        results_path=tmp_path / "results.json",
        budgets={"CNY": "1", "USD": "0.1"},
    )

    executor.preflight([action])


def test_recovery_store_is_private_sanitized_and_restores_unknown_budget(tmp_path):
    lib = _lib()
    recovery_path = tmp_path / "remote_asr_benchmark" / "recovery.json"
    store = lib.RecoveryStore(recovery_path)
    store.write_snapshot(
        budgets={"CNY": "2", "USD": "0.1"},
        price_snapshot={
            "funasr_cny_per_second": "0.00022",
            "groq_usd_per_hour": "0.04",
        },
        spent={"CNY": "0", "USD": "0"},
        attempts=[
            {
                "attempt_id": "aliyun:sample:main:r01",
                "action_id": "aliyun:sample:main:r01:a01",
                "sample_sha256": "a" * 64,
                "provider": "aliyun",
                "model": "fun-asr-2025-11-07",
                "task_id": "task-1",
                "request_id": "request-1",
                "state": "unknown",
                "amount": "0.6",
                "currency": "CNY",
                "api_key": "must-not-persist",
                "url": "https://signed.example/?token=secret",
                "headers": {"Authorization": "Bearer secret"},
                "media_path": "/private/audio.flac",
            }
        ],
    )

    assert oct(os.stat(recovery_path).st_mode & 0o777) == "0o600"
    rendered = recovery_path.read_text(encoding="utf-8").casefold()
    for forbidden in ("api_key", "authorization", "https://", "media_path", "secret"):
        assert forbidden not in rendered

    ledgers = store.load_ledgers()
    assert ledgers["CNY"].committed_unknown == Decimal("0.6")
    assert ledgers["CNY"].reserve("retry", "1.5", "CNY") is False
    store.abandon("aliyun:sample:main:r01:a01")
    assert recovery_path.exists()
    assert store.load_ledgers()["CNY"].committed_unknown == Decimal("0.6")

    store.settle_terminal("aliyun:sample:main:r01:a01", "0.25", "CNY")
    assert not recovery_path.exists()


def test_cleanup_is_narrow_idempotent_and_preserves_adjacent_recovery(tmp_path):
    lib = _lib()
    benchmark_root = tmp_path / "data" / "temp" / "remote_asr_benchmark"
    run_dir = benchmark_root / "run-001"
    run_dir.mkdir(parents=True)
    (run_dir / "media.flac").write_bytes(b"audio")
    (run_dir / "raw-response.json").write_text("{}", encoding="utf-8")
    recovery_path = benchmark_root / "recovery.json"
    recovery_path.write_text("{}", encoding="utf-8")

    lib.cleanup_run_artifacts(run_dir, recovery_path=recovery_path)
    lib.cleanup_run_artifacts(run_dir, recovery_path=recovery_path)

    assert not run_dir.exists()
    assert recovery_path.exists()
    with pytest.raises(lib.PreflightError, match="run directory"):
        lib.cleanup_run_artifacts(tmp_path, recovery_path=recovery_path)
    decoy_run_dir = tmp_path / "other" / "remote_asr_benchmark" / "run-decoy"
    decoy_run_dir.mkdir(parents=True)
    with pytest.raises(lib.PreflightError, match="run directory"):
        lib.cleanup_run_artifacts(decoy_run_dir, recovery_path=recovery_path)
    assert decoy_run_dir.exists()


@pytest.mark.parametrize("bad_duration", [-1, float("nan"), float("inf"), None])
def test_cost_functions_reject_invalid_durations(bad_duration):
    lib = _lib()

    with pytest.raises(ValueError, match="duration"):
        lib.funasr_worst_case_cost_cny(bad_duration)


def test_budget_gate_counts_all_commitment_buckets_and_is_currency_isolated():
    lib = _lib()
    ledger = lib.BudgetLedger(limit="1.00", currency="CNY")
    ledger.spent = Decimal("0.20")
    ledger.reserved = Decimal("0.30")
    ledger.committed_unknown = Decimal("0.10")

    assert ledger.can_reserve("0.40", "CNY") is True
    assert ledger.can_reserve("0.400001", "CNY") is False
    assert ledger.can_reserve("0.01", "USD") is False


@pytest.mark.parametrize("bad_limit", [None, "0", "-1", "not-a-number", float("nan")])
def test_missing_invalid_or_nonpositive_budget_fails_closed(bad_limit):
    lib = _lib()
    ledger = lib.BudgetLedger(limit=bad_limit, currency="CNY")

    assert ledger.can_reserve("0.01", "CNY") is False
    assert ledger.reserve("request-1", "0.01", "CNY") is False


def test_budget_ledger_restores_decimal_buckets_from_json_strings():
    lib = _lib()
    ledger = lib.BudgetLedger(
        limit="10.0",
        currency="USD",
        spent="1.2",
        reserved="2.3",
        committed_unknown="3.4",
        recovered_commitments={
            "reserved-request": {"amount": "2.3", "state": "reserved"},
            "unknown-request": {"amount": "3.4", "state": "unknown"},
        },
    )

    assert ledger.spent == Decimal("1.2")
    assert ledger.reserved == Decimal("2.3")
    assert ledger.committed_unknown == Decimal("3.4")
    assert ledger.available == Decimal("3.1")
    assert ledger.reserve("new-request", "3.1", "USD") is True


def test_restored_unknown_commitment_can_settle_and_release_difference():
    lib = _lib()
    ledger = lib.BudgetLedger(
        limit="1.00",
        currency="USD",
        spent="0.10",
        committed_unknown="0.60",
        recovered_commitments={
            "unknown-request": {"amount": "0.60", "state": "unknown"},
        },
    )

    ledger.settle("unknown-request", "0.25", "USD")

    assert ledger.spent == Decimal("0.35")
    assert ledger.committed_unknown == Decimal("0")
    assert ledger.available == Decimal("0.65")


def test_restored_reservation_can_move_to_unknown_and_then_settle():
    lib = _lib()
    ledger = lib.BudgetLedger(
        limit="1.00",
        currency="USD",
        reserved="0.60",
        recovered_commitments={
            "reserved-request": {"amount": "0.60", "state": "reserved"},
        },
    )

    ledger.mark_unknown("reserved-request")
    assert ledger.reserved == Decimal("0")
    assert ledger.committed_unknown == Decimal("0.60")

    ledger.settle("reserved-request", "0.20", "USD")
    assert ledger.spent == Decimal("0.20")
    assert ledger.committed_unknown == Decimal("0")


@pytest.mark.parametrize(
    "reserved, committed_unknown, recovered",
    [
        pytest.param(
            "0.50",
            "0",
            {"request": {"amount": "0.60", "state": "reserved"}},
            id="reserved-mismatch",
        ),
        pytest.param(
            "0",
            "0.50",
            {"request": {"amount": "0.60", "state": "unknown"}},
            id="unknown-mismatch",
        ),
    ],
)
def test_restored_commitment_aggregates_must_match_request_records(
    reserved,
    committed_unknown,
    recovered,
):
    lib = _lib()

    with pytest.raises(ValueError, match="aggregate"):
        lib.BudgetLedger(
            limit="1.00",
            currency="USD",
            reserved=reserved,
            committed_unknown=committed_unknown,
            recovered_commitments=recovered,
        )


def test_nonzero_aggregate_without_request_records_fails_closed():
    lib = _lib()

    with pytest.raises(ValueError, match="commitment"):
        lib.BudgetLedger(
            limit="1.00",
            currency="USD",
            committed_unknown="0.60",
        )


@pytest.mark.parametrize(
    "recovered, message",
    [
        pytest.param(
            {"   ": {"amount": "0", "state": "reserved"}},
            "request ID",
            id="empty-id",
        ),
        pytest.param(
            {"request": {"amount": "NaN", "state": "reserved"}},
            "amount",
            id="invalid-amount",
        ),
        pytest.param(
            {"request": {"amount": "-0.1", "state": "unknown"}},
            "amount",
            id="negative-amount",
        ),
        pytest.param(
            {"request": {"amount": "0", "state": "settled"}},
            "state",
            id="invalid-state",
        ),
    ],
)
def test_invalid_recovered_commitment_records_are_rejected(recovered, message):
    lib = _lib()

    with pytest.raises(ValueError, match=message):
        lib.BudgetLedger(
            limit="1.00",
            currency="USD",
            recovered_commitments=recovered,
        )


@pytest.mark.parametrize(
    "bucket,bad_value",
    [
        pytest.param("spent", "-0.01", id="negative-spent"),
        pytest.param("reserved", "not-a-number", id="invalid-reserved"),
        pytest.param("committed_unknown", "NaN", id="nonfinite-unknown"),
        pytest.param("spent", None, id="missing-spent"),
        pytest.param("reserved", float("inf"), id="infinite-reserved"),
    ],
)
def test_budget_ledger_rejects_invalid_restored_buckets(bucket, bad_value):
    lib = _lib()
    restored = {bucket: bad_value}

    with pytest.raises(ValueError, match=bucket):
        lib.BudgetLedger(limit="10", currency="USD", **restored)


def test_unknown_acceptance_moves_reservation_without_releasing_commitment():
    lib = _lib()
    ledger = lib.BudgetLedger(limit="1.00", currency="USD")

    assert ledger.reserve("first", "0.60", "USD") is True
    ledger.mark_unknown("first")
    assert ledger.reserved == Decimal("0")
    assert ledger.committed_unknown == Decimal("0.60")

    ledger.abandon("first")
    assert ledger.committed_unknown == Decimal("0.60")
    assert ledger.reserve("retry", "0.50", "USD") is False


def test_only_settlement_releases_unknown_commitment_difference():
    lib = _lib()
    ledger = lib.BudgetLedger(limit="1.00", currency="USD")
    assert ledger.reserve("request-1", "0.60", "USD") is True
    ledger.mark_unknown("request-1")

    ledger.settle("request-1", "0.25", "USD")

    assert ledger.spent == Decimal("0.25")
    assert ledger.committed_unknown == Decimal("0")
    assert ledger.available == Decimal("0.75")


def test_reserved_settlement_cannot_exceed_its_worst_case_or_mutate_buckets():
    lib = _lib()
    ledger = lib.BudgetLedger(limit="1.00", currency="USD")
    assert ledger.reserve("request-1", "0.60", "USD") is True
    before = (ledger.spent, ledger.reserved, ledger.committed_unknown, ledger.available)

    with pytest.raises(ValueError, match="worst-case"):
        ledger.settle("request-1", "0.61", "USD")

    assert (ledger.spent, ledger.reserved, ledger.committed_unknown, ledger.available) == before
    ledger.mark_unknown("request-1")
    assert ledger.committed_unknown == Decimal("0.60")


def test_unknown_settlement_cannot_exceed_its_worst_case_or_mutate_buckets():
    lib = _lib()
    ledger = lib.BudgetLedger(limit="1.00", currency="USD")
    assert ledger.reserve("request-1", "0.60", "USD") is True
    ledger.mark_unknown("request-1")
    before = (ledger.spent, ledger.reserved, ledger.committed_unknown, ledger.available)

    with pytest.raises(ValueError, match="worst-case"):
        ledger.settle("request-1", "0.61", "USD")

    assert (ledger.spent, ledger.reserved, ledger.committed_unknown, ledger.available) == before
    ledger.settle("request-1", "0.25", "USD")
    assert ledger.spent == Decimal("0.25")


def test_state_machine_allows_only_the_declared_linear_path():
    lib = _lib()
    machine = lib.BenchmarkStateMachine()

    for state in (
        lib.BenchmarkState.AUDIO_READY,
        lib.BenchmarkState.STAGED,
        lib.BenchmarkState.ASR_STARTED,
        lib.BenchmarkState.TERMINAL,
    ):
        machine.transition(state)
        assert machine.state is state

    with pytest.raises(lib.InvalidTransition):
        machine.transition(lib.BenchmarkState.ASR_STARTED)


def test_state_machine_rejects_skipped_and_backward_transitions():
    lib = _lib()
    machine = lib.BenchmarkStateMachine()

    with pytest.raises(lib.InvalidTransition):
        machine.transition(lib.BenchmarkState.STAGED)
    machine.transition(lib.BenchmarkState.AUDIO_READY)
    with pytest.raises(lib.InvalidTransition):
        machine.transition(lib.BenchmarkState.DISCOVERED)


@pytest.mark.parametrize(
    "locator, duration, actual_hash, expected_hash",
    [
        pytest.param(None, None, None, "a" * 64, id="missing-audio"),
        pytest.param("audio.wav", None, "a" * 64, "a" * 64, id="missing-duration"),
        pytest.param("audio.wav", 30, "b" * 64, "a" * 64, id="hash-mismatch"),
        pytest.param("audio.wav", 30, "abc", "abc", id="short-hash"),
        pytest.param("audio.wav", 30, "g" * 64, "g" * 64, id="nonhex-hash"),
        pytest.param("audio.wav", 30, "a" * 63, "a" * 63, id="wrong-length-hash"),
    ],
)
def test_preflight_rejects_before_credentials_upload_or_provider(
    locator,
    duration,
    actual_hash,
    expected_hash,
):
    lib = _lib()
    calls = {"credentials": 0, "upload": 0, "provider": 0}

    def counted(name, result):
        def call(*_args):
            calls[name] += 1
            return result

        return call

    metadata = (
        None
        if locator is None
        else lib.AudioMetadata(locator, duration, actual_hash)
    )

    with pytest.raises(lib.PreflightError):
        lib.guarded_start_asr(
            lib.BenchmarkStateMachine(),
            metadata,
            expected_hash,
            counted("credentials", "secret"),
            counted("upload", "upload-id"),
            counted("provider", "provider-id"),
        )

    assert calls == {"credentials": 0, "upload": 0, "provider": 0}


def test_valid_preflight_runs_hooks_only_after_staging():
    lib = _lib()
    machine = lib.BenchmarkStateMachine()
    observed_states = []

    def hook(result):
        def call(*_args):
            observed_states.append(machine.state)
            return result

        return call

    result = lib.guarded_start_asr(
        machine,
        lib.AudioMetadata("audio.wav", 30, "A" * 64),
        "a" * 64,
        hook("credentials"),
        hook("upload-id"),
        hook("provider-id"),
    )

    assert observed_states == [
        lib.BenchmarkState.STAGED,
        lib.BenchmarkState.STAGED,
        lib.BenchmarkState.ASR_STARTED,
    ]
    assert machine.state is lib.BenchmarkState.ASR_STARTED
    assert result == "provider-id"


def test_provider_exception_leaves_started_state_for_unknown_reconciliation():
    lib = _lib()
    machine = lib.BenchmarkStateMachine()
    calls = {"credentials": 0, "upload": 0, "provider": 0}
    provider_observed_states = []

    def read_credentials():
        calls["credentials"] += 1
        return "credentials"

    def upload(*_args):
        calls["upload"] += 1
        return "upload-id"

    def provider_start(*_args):
        calls["provider"] += 1
        provider_observed_states.append(machine.state)
        raise RuntimeError("provider acceptance is unknown")

    with pytest.raises(RuntimeError, match="acceptance is unknown"):
        lib.guarded_start_asr(
            machine,
            lib.AudioMetadata("audio.wav", 30, "a" * 64),
            "a" * 64,
            read_credentials,
            upload,
            provider_start,
        )

    assert calls == {"credentials": 1, "upload": 1, "provider": 1}
    assert provider_observed_states == [lib.BenchmarkState.ASR_STARTED]
    assert machine.state is lib.BenchmarkState.ASR_STARTED


def test_sanitizer_only_emits_valid_whitelisted_scalar_fields():
    lib = _lib()
    unsafe = {
        "provider": "groq",
        "state": "TERMINAL",
        "duration_seconds": 42,
        "usage_seconds": 39,
        "cost": "0.001",
        "currency": "USD",
        "status_code": 200,
        "url": "https://host/path?token=signed-secret",
        "authorization": "Bearer secret",
        "api_key": "secret-key",
        "headers": {"X-Signature": "secret-signature"},
        "exception": RuntimeError("request failed at https://secret-url"),
    }

    sanitized = lib.sanitize_result(unsafe)

    assert sanitized == {
        "provider": "groq",
        "state": "TERMINAL",
        "duration_seconds": 42,
        "usage_seconds": 39,
        "cost": "0.001",
        "currency": "USD",
        "status_code": 200,
    }
    rendered = repr(sanitized).lower()
    for forbidden in ("https://", "token", "secret", "authorization", "api_key", "headers", "exception"):
        assert forbidden not in rendered


def test_sanitizer_drops_url_shaped_or_invalid_values_even_under_safe_keys():
    lib = _lib()

    assert lib.sanitize_result(
        {
            "provider": "https://signed.example/?token=secret",
            "state": "failed: Authorization Bearer secret",
            "currency": "secret-key",
            "duration_seconds": float("nan"),
            "cost": object(),
        }
    ) == {}


def test_sanitizer_converts_decimal_metrics_to_exact_json_safe_strings():
    lib = _lib()
    sanitized = lib.sanitize_result(
        {
            "provider": "funasr",
            "duration_seconds": Decimal("42.1234567890123456789012345678"),
            "usage_seconds": Decimal("39.0000000000000000000000000001"),
            "cost": Decimal("0.008580000000000000000000000001"),
            "currency": "CNY",
            "headers": {"Authorization": "Bearer secret"},
        }
    )

    assert sanitized == {
        "provider": "funasr",
        "duration_seconds": "42.1234567890123456789012345678",
        "usage_seconds": "39.0000000000000000000000000001",
        "cost": "0.008580000000000000000000000001",
        "currency": "CNY",
    }
    assert json.loads(json.dumps(sanitized)) == sanitized
    assert "secret" not in json.dumps(sanitized).lower()


def test_long_audio_timestamps_must_be_monotonic_and_well_formed():
    lib = _lib()
    segment = lib.TranscriptSegment

    assert lib.timestamps_are_monotonic([segment(0, 2, "a"), segment(2, 3, "b")]) is True
    assert lib.timestamps_are_monotonic([segment(2, 3, "a"), segment(1, 4, "b")]) is False
    assert lib.timestamps_are_monotonic([segment(3, 2, "a")]) is False


def test_long_audio_hole_requires_five_second_vad_and_no_nearby_text():
    lib = _lib()
    segment = lib.TranscriptSegment
    vad = [lib.TimeRange(20, 26), lib.TimeRange(40, 44)]

    assert lib.find_empty_speech_holes(vad, [segment(0, 10, "intro")]) == [lib.TimeRange(20, 26)]
    assert lib.find_empty_speech_holes(vad, [segment(14.5, 15.5, "nearby")]) == []
    assert lib.find_empty_speech_holes(vad, [segment(20, 21, "   ")]) == [lib.TimeRange(20, 26)]


def test_last_timestamp_must_be_within_five_seconds_of_registered_speech_end():
    lib = _lib()
    segment = lib.TranscriptSegment

    assert lib.last_timestamp_within_limit([segment(0, 95, "tail")], 100) is True
    assert lib.last_timestamp_within_limit([segment(0, 105, "tail")], 100) is True
    assert lib.last_timestamp_within_limit([segment(0, 94.999, "tail")], 100) is False
    assert lib.last_timestamp_within_limit([], 100) is False


def test_aliyun_upload_gets_policy_and_posts_exact_oss_multipart_fields():
    lib = _lib()
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "data": {
                        "policy": "encoded-policy",
                        "signature": "signed-value",
                        "upload_dir": "benchmark/uploads",
                        "upload_host": "https://oss-upload.example",
                        "oss_access_key_id": "temporary-access-id",
                        "x_oss_object_acl": "private",
                        "x_oss_forbid_overwrite": "true",
                    }
                }
            ),
            _FakeResponse({}, status_code=200),
        ]
    )
    client = lib.AliyunASRClient(
        api_key="api-secret",
        workspace_id="workspace-1",
        session=session,
        timeouts={"upload_policy": 3, "upload": 7},
    )
    audio = BytesIO(b"RIFF-audio")

    staged_uri = client.upload_audio(audio, "sample.wav", "audio/wav")

    assert staged_uri == "oss://benchmark/uploads/sample.wav"
    assert session.calls[0] == {
        "method": "GET",
        "url": "https://dashscope.aliyuncs.com/api/v1/uploads",
        "params": {"action": "getPolicy", "model": "fun-asr-2025-11-07"},
        "headers": {
            "Authorization": "Bearer api-secret",
            "Content-Type": "application/json",
        },
        "timeout": 3,
    }
    upload_call = session.calls[1]
    assert upload_call["method"] == "POST"
    assert upload_call["url"] == "https://oss-upload.example"
    assert upload_call["timeout"] == 7
    assert upload_call["data"] == {
        "OSSAccessKeyId": "temporary-access-id",
        "Signature": "signed-value",
        "policy": "encoded-policy",
        "x-oss-object-acl": "private",
        "x-oss-forbid-overwrite": "true",
        "key": "benchmark/uploads/sample.wav",
        "success_action_status": "200",
    }
    assert upload_call["files"] == {
        "file": ("sample.wav", audio, "audio/wav")
    }


@pytest.mark.parametrize(
    "diarization_enabled,speaker_count,optional_parameters",
    [
        pytest.param(None, None, {}, id="defaults"),
        pytest.param(
            True,
            2,
            {"diarization_enabled": True, "speaker_count": 2},
            id="diarization",
        ),
    ],
)
def test_aliyun_submit_uses_workspace_async_headers_and_parses_identity(
    diarization_enabled,
    speaker_count,
    optional_parameters,
):
    lib = _lib()
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {"task_id": "task-1", "task_status": "PENDING"},
                    "request_id": "request-1",
                }
            )
        ]
    )
    client = lib.AliyunASRClient(
        api_key="api-secret",
        workspace_id="workspace-1",
        api_host="https://workspace-1.cn-beijing.maas.aliyuncs.com",
        session=session,
        timeouts={"submit": 11},
    )

    result = client.submit(
        "oss://benchmark/uploads/sample.wav",
        ["zh", "en"],
        diarization_enabled=diarization_enabled,
        speaker_count=speaker_count,
    )

    assert result == {
        "task_id": "task-1",
        "request_id": "request-1",
        "status": "PENDING",
    }
    assert session.calls == [
        {
            "method": "POST",
            "url": "https://workspace-1.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription",
            "headers": {
                "Authorization": "Bearer api-secret",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
                "X-DashScope-OssResourceResolve": "enable",
                "X-DashScope-WorkSpace": "workspace-1",
            },
            "json": {
                "model": "fun-asr-2025-11-07",
                "input": {"file_urls": ["oss://benchmark/uploads/sample.wav"]},
                "parameters": {
                    "language_hints": ["zh", "en"],
                    **optional_parameters,
                },
            },
            "timeout": 11,
        }
    ]


@pytest.mark.parametrize(
    "api_host",
    [
        "http://workspace-1.cn-beijing.maas.aliyuncs.com",
        "https://other-workspace.cn-beijing.maas.aliyuncs.com",
        "https://workspace-1.cn-beijing.maas.aliyuncs.com/path",
        "https://workspace-1.cn-beijing.maas.aliyuncs.com?token=value",
        "https://workspace-1.cn-beijing.maas.aliyuncs.com:8443",
    ],
)
def test_aliyun_rejects_unsafe_api_host_before_any_request(api_host):
    lib = _lib()
    session = _FakeSession([])

    with pytest.raises(lib.PreflightError, match="host"):
        lib.AliyunASRClient(
            "api-secret",
            "workspace-1",
            api_host=api_host,
            session=session,
        )

    assert session.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"output": {"task_status": "PENDING"}, "request_id": "request-1"},
            id="missing-task-id",
        ),
        pytest.param(
            {
                "output": {"task_id": "task-1", "task_status": "UNKNOWN"},
                "request_id": "request-1",
            },
            id="unknown-submit-status",
        ),
    ],
)
def test_aliyun_submit_rejects_missing_identity_or_unknown_status(payload):
    lib = _lib()
    client = lib.AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=_FakeSession([_FakeResponse(payload)]),
    )

    with pytest.raises(lib.RemoteASRError) as error:
        client.submit("oss://benchmark/uploads/sample.wav", ["zh"])

    assert error.value.safe_details == {
        "code": "invalid_response",
        "status_code": 200,
    }


def test_aliyun_poll_queries_same_task_and_normalizes_downloaded_transcript():
    lib = _lib()
    transcript_url = "https://signed.example/transcript.json?token=secret"
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {"task_id": "task-1", "task_status": "RUNNING"},
                    "request_id": "poll-request",
                }
            ),
            _FakeResponse(
                {
                    "output": {
                        "task_id": "task-1",
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "subtask_status": "SUCCEEDED",
                                "transcription_url": transcript_url,
                            }
                        ],
                    },
                    "usage": {"duration": 12.5},
                    "request_id": "terminal-request",
                }
            ),
            _FakeResponse(
                {
                    "transcripts": [
                        {
                            "text": "Hello world",
                            "sentences": [
                                {
                                    "text": "Hello world",
                                    "begin_time": 0,
                                    "end_time": 900,
                                    "speaker_id": 1,
                                    "words": [
                                        {
                                            "text": "Hello",
                                            "begin_time": 0,
                                            "end_time": 400,
                                            "speaker_id": 1,
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
        ]
    )
    sleeps = []
    client = lib.AliyunASRClient(
        api_key="api-secret",
        workspace_id="workspace-1",
        session=session,
        sleep=sleeps.append,
        clock=lambda: 0,
        timeouts={"poll": 5, "download": 13},
    )

    result = client.poll("task-1", poll_interval_seconds=0.25, timeout_seconds=30)

    assert result == {
        "task_id": "task-1",
        "request_id": "terminal-request",
        "status": "SUCCEEDED",
        "usage_seconds": 12.5,
        "results": [
            {
                "status": "SUCCEEDED",
                "transcript": {
                    "text": "Hello world",
                    "sentences": [
                        {
                            "text": "Hello world",
                            "start_time": 0,
                            "end_time": 0.9,
                            "speaker": 1,
                            "words": [
                                {
                                    "text": "Hello",
                                    "start_time": 0,
                                    "end_time": 0.4,
                                    "speaker": 1,
                                }
                            ],
                        }
                    ],
                },
            }
        ],
    }
    task_url = "https://workspace-1.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-1"
    assert [call["url"] for call in session.calls[:2]] == [task_url, task_url]
    assert [call["method"] for call in session.calls] == ["GET", "GET", "GET"]
    assert session.calls[2]["url"] == transcript_url
    assert sleeps == [0.25]
    rendered = repr(result).lower()
    for forbidden in ("https://", "authorization", "api-secret", "token=secret"):
        assert forbidden not in rendered


@pytest.mark.parametrize("status", [None, "", "UNKNOWN", "PAUSED"])
def test_aliyun_poll_rejects_missing_or_unknown_task_status(status):
    lib = _lib()
    client = lib.AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=_FakeSession(
            [
                _FakeResponse(
                    {
                        "output": {"task_id": "task-1", "task_status": status},
                        "request_id": "request-1",
                    }
                )
            ]
        ),
    )

    with pytest.raises(lib.RemoteASRError) as error:
        client.poll("task-1")

    assert error.value.safe_details == {
        "code": "invalid_response",
        "status_code": 200,
    }


def test_aliyun_poll_timeout_never_resubmits_the_task():
    lib = _lib()
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {"task_id": "task-1", "task_status": "RUNNING"},
                    "request_id": "poll-request",
                }
            )
        ]
    )
    clock_values = iter([0.0, 2.0])
    client = lib.AliyunASRClient(
        api_key="api-secret",
        workspace_id="workspace-1",
        session=session,
        sleep=lambda _seconds: None,
        clock=lambda: next(clock_values),
    )

    with pytest.raises(lib.PollTimeoutError) as error:
        client.poll("task-1", timeout_seconds=1)

    assert error.value.safe_details == {
        "code": "poll_timeout",
        "status_code": None,
    }
    assert [(call["method"], call["url"]) for call in session.calls] == [
        (
            "GET",
            "https://workspace-1.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-1",
        )
    ]


def test_aliyun_poll_sleep_crossing_deadline_stops_before_another_request():
    lib = _lib()
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "output": {"task_id": "task-1", "task_status": "RUNNING"},
                    "request_id": "poll-request",
                }
            )
        ]
    )
    clock_values = iter([0.0, 0.5, 1.1])
    sleeps = []
    client = lib.AliyunASRClient(
        "api-secret",
        "workspace-1",
        session=session,
        sleep=sleeps.append,
        clock=lambda: next(clock_values),
        timeouts={"poll": 30},
    )

    with pytest.raises(lib.PollTimeoutError):
        client.poll("task-1", poll_interval_seconds=0.75, timeout_seconds=1)

    assert len(session.calls) == 1
    assert session.calls[0]["timeout"] == 1
    assert sleeps == [0.5]


def test_groq_sends_verbose_timestamp_multipart_and_parses_safe_result():
    lib = _lib()
    session = _FakeSession(
        [
            _FakeResponse(
                {
                    "text": "Hello world",
                    "duration": 1.25,
                    "segments": [{"start": 0, "end": 1.25, "text": "Hello world"}],
                    "words": [{"start": 0, "end": 0.5, "word": "Hello"}],
                },
                headers={
                    "x-request-id": "groq-request-1",
                    "Authorization": "Bearer response-secret",
                },
            )
        ]
    )
    client = lib.GroqASRClient(
        api_key="groq-secret",
        api_host="https://groq.test/openai/v1",
        session=session,
        timeouts={"groq": 17},
    )
    audio = BytesIO(b"RIFF-audio")

    result = client.transcribe(
        audio,
        "sample.wav",
        "en",
        prompt="Names: DashScope",
        content_type="audio/wav",
    )

    assert result == {
        "request_id": "groq-request-1",
        "text": "Hello world",
        "duration": 1.25,
        "segments": [{"start": 0, "end": 1.25, "text": "Hello world"}],
        "words": [{"start": 0, "end": 0.5, "word": "Hello"}],
    }
    assert session.calls == [
        {
            "method": "POST",
            "url": "https://groq.test/openai/v1/audio/transcriptions",
            "headers": {"Authorization": "Bearer groq-secret"},
            "files": {"file": ("sample.wav", audio, "audio/wav")},
            "data": {
                "model": "whisper-large-v3-turbo",
                "language": "en",
                "response_format": "verbose_json",
                "timestamp_granularities[]": ["segment", "word"],
                "prompt": "Names: DashScope",
            },
            "timeout": 17,
        }
    ]
    rendered = repr(result).lower()
    assert "authorization" not in rendered
    assert "secret" not in rendered


@pytest.mark.parametrize("operation", ["aliyun-upload", "aliyun-submit", "groq"])
def test_mutating_request_timeout_is_unknown_and_is_never_retried(operation):
    lib = _lib()
    timeout = requests.exceptions.Timeout("secret raw timeout detail")
    if operation == "aliyun-upload":
        session = _FakeSession(
            [
                _FakeResponse(
                    {
                        "data": {
                            "policy": "policy",
                            "signature": "signature",
                            "upload_dir": "uploads",
                            "upload_host": "https://oss.example",
                            "oss_access_key_id": "access-id",
                            "x_oss_object_acl": "private",
                            "x_oss_forbid_overwrite": "true",
                        }
                    }
                ),
                timeout,
            ]
        )
        client = lib.AliyunASRClient("secret-key", "workspace", session=session)
        invoke = lambda: client.upload_audio(BytesIO(b"audio"), "sample.wav")
        expected_calls = 2
    elif operation == "aliyun-submit":
        session = _FakeSession([timeout])
        client = lib.AliyunASRClient("secret-key", "workspace", session=session)
        invoke = lambda: client.submit("oss://secret-key", ["zh"])
        expected_calls = 1
    else:
        session = _FakeSession([timeout])
        client = lib.GroqASRClient("secret-key", session=session)
        invoke = lambda: client.transcribe(BytesIO(b"audio"), "sample.wav", "en")
        expected_calls = 1

    with pytest.raises(lib.PotentiallyAcceptedError) as error:
        invoke()

    assert len(session.calls) == expected_calls
    assert error.value.code == "timeout"
    assert error.value.status_code is None
    assert set(error.value.safe_details) == {"code", "status_code"}
    rendered = repr(error.value).lower()
    for forbidden in ("secret", "authorization", "https://", "headers"):
        assert forbidden not in rendered


@pytest.mark.parametrize("provider", ["aliyun", "groq"])
def test_http_errors_expose_only_safe_code_and_status(provider):
    lib = _lib()
    unsafe_response = _FakeResponse(
        {"error": "api-key=secret-key", "url": "https://signed.example"},
        status_code=503,
        headers={"Authorization": "Bearer secret-key"},
        text="raw body secret-key https://signed.example",
    )
    session = _FakeSession([unsafe_response])
    if provider == "aliyun":
        client = lib.AliyunASRClient("secret-key", "workspace", session=session)
        invoke = lambda: client.submit("oss://signed-secret", ["zh"])
    else:
        client = lib.GroqASRClient("secret-key", session=session)
        invoke = lambda: client.transcribe(BytesIO(b"audio"), "sample.wav", "en")

    with pytest.raises(lib.RemoteASRError) as error:
        invoke()

    assert error.value.safe_details == {"code": "http_error", "status_code": 503}
    assert set(vars(error.value)) == {"code", "status_code"}
    rendered = repr(error.value).lower()
    for forbidden in ("secret", "authorization", "https://", "headers", "raw body"):
        assert forbidden not in rendered
