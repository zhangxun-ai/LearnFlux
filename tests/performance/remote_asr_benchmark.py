"""Explicit, offline-safe CLI gate for the remote ASR benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

try:
    from tests.performance import remote_asr_benchmark_lib as benchmark
except ModuleNotFoundError:
    import remote_asr_benchmark_lib as benchmark


DEFAULT_MANIFEST = (
    Path(__file__).parents[1]
    / "fixtures"
    / "remote_asr_benchmark"
    / "manifest.json"
)
REPOSITORY_ROOT = Path(__file__).parents[2]
DEFAULT_SAMPLES_DIR = REPOSITORY_ROOT / "tests" / "cache" / "remote_asr_benchmark"
DEFAULT_RECOVERY = (
    REPOSITORY_ROOT / "data" / "temp" / "remote_asr_benchmark" / "recovery.json"
)
DEFAULT_RESULTS = (
    REPOSITORY_ROOT
    / "docs"
    / "superpowers"
    / "reports"
    / "2026-07-21-remote-asr-benchmark-results.json"
)


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit benchmark command parser."""
    parser = argparse.ArgumentParser(description="Remote ASR benchmark gate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")

    run = subparsers.add_parser("run")
    run.add_argument("--provider", default="aliyun,groq")
    run.add_argument("--samples", default="all")
    run.add_argument("--variants", default="all")
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--max-cny")
    run.add_argument("--max-usd")
    run.add_argument("--execute-paid", action="store_true")
    run.add_argument("--retry-unknown", action="store_true")

    subparsers.add_parser("resume-task")
    subparsers.add_parser("report")
    subparsers.add_parser("cleanup")
    return parser


def _load_manifest() -> dict:
    with DEFAULT_MANIFEST.open(encoding="utf-8") as manifest_file:
        payload = json.load(manifest_file)
    if not isinstance(payload, dict):
        raise ValueError("invalid manifest")
    return payload


def _run_summary(args: argparse.Namespace) -> dict:
    try:
        manifest = _load_manifest()
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "mode": "execute_paid" if args.execute_paid else "dry_run",
            "status": "blocked",
            "blocked_reasons": ["invalid_manifest"],
            "action_count": 0,
            "required_budget": {"CNY": None, "USD": None},
            "actions": [],
        }
    sample_ids = None if args.samples == "all" else args.samples
    variants = None if args.variants == "all" else args.variants
    if args.execute_paid:
        executor = benchmark.BenchmarkSmokeExecutor(
            manifest=manifest,
            samples_dir=DEFAULT_SAMPLES_DIR,
            recovery_store=benchmark.RecoveryStore(DEFAULT_RECOVERY),
            results_path=DEFAULT_RESULTS,
            budgets={"CNY": args.max_cny, "USD": args.max_usd},
        )
        credential_reader = benchmark.read_remote_credentials_from_environment
    else:
        executor = None
        credential_reader = None
    return benchmark.run_action_matrix(
        manifest=manifest,
        execute_paid=args.execute_paid,
        max_cny=args.max_cny,
        max_usd=args.max_usd,
        providers=args.provider,
        sample_ids=sample_ids,
        repeats=args.repeats,
        variants=variants,
        retry_unknown=args.retry_unknown,
        credential_reader=credential_reader,
        external_executor=executor,
    )


def _resume_summary() -> dict:
    try:
        manifest = _load_manifest()
        recovery_store = benchmark.RecoveryStore(DEFAULT_RECOVERY)
        snapshot = recovery_store.load()
        executor = benchmark.BenchmarkSmokeExecutor(
            manifest=manifest,
            samples_dir=DEFAULT_SAMPLES_DIR,
            recovery_store=recovery_store,
            results_path=DEFAULT_RESULTS,
            budgets=snapshot["budgets"],
        )
    except Exception:
        return {
            "mode": "resume_task",
            "status": "blocked",
            "blocked_reasons": ["invalid_recovery"],
        }
    return executor.resume_pending_aliyun(
        benchmark.read_remote_credentials_from_environment
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print an English ASCII benchmark summary."""
    args = build_parser().parse_args(argv)
    if args.command == "run":
        summary = _run_summary(args)
    elif args.command == "resume-task":
        summary = _resume_summary()
    else:
        summary = {"command": args.command, "status": "not_implemented"}
    print(json.dumps(summary, sort_keys=True, ensure_ascii=True))
    return 0 if summary["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
