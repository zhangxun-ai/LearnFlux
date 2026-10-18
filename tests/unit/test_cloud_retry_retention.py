"""Cloud handoff keeps retry audio independent of provider attempt cleanup."""

import hashlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_transcript_api.api import context
from video_transcript_api.transcriber import cloud_runtime
from video_transcript_api.transcriber.asr_retry_repository import ASRRetryRepository
from video_transcript_api.transcriber.control_database import SQLiteControlDatabase
from video_transcript_api.transcriber.media_preparer import PreparedASRMedia


@pytest.mark.parametrize("retained", [True, False])
def test_provider_cleanup_preserves_only_retained_retry_audio(tmp_path, monkeypatch, retained):
    media = tmp_path / "quote-audio.m4a"
    media.write_bytes(b"test audio")
    prepared = PreparedASRMedia(
        path=media, media_format="m4a", duration_seconds=Decimal("2"),
        size_bytes=media.stat().st_size,
        sha256=hashlib.sha256(media.read_bytes()).hexdigest(), preparation="demuxed",
    )
    database = SQLiteControlDatabase(tmp_path / "control.db")
    if retained:
        ASRRetryRepository(database).save("task-1", media.name, prepared.sha256, "{}")
    repository = SimpleNamespace(
        database=database, find_recoverable_event_by_task_id=lambda task: None,
        reserve_attempt=lambda *a: None,
    )
    monkeypatch.setattr(context, "get_temp_manager", lambda: SimpleNamespace(get_temp_dir=lambda: tmp_path))
    monkeypatch.setattr(context, "get_transcription_control_store", lambda: SimpleNamespace(usage_repository=repository))
    monkeypatch.setattr(context, "get_transcription_concurrency_controller", lambda: object())
    monkeypatch.setattr(context, "get_cloud_submission_guard", lambda: object())
    monkeypatch.setattr(context, "get_cloud_pricing_service", lambda: SimpleNamespace(apply_cached_price=lambda cfg: cfg))
    monkeypatch.setattr(cloud_runtime, "AliyunFunASRProvider", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(cloud_runtime, "ASRMediaPreparer", lambda root: SimpleNamespace(
        verify_existing=lambda *args: prepared, cleanup=lambda verified: verified.path.unlink(),
    ))
    provider = cloud_runtime.build_aliyun_provider(
        config={"cloud_asr": {
            "enabled": True, "provider": "aliyun", "model": "fun-asr-2025-11-07",
            "price_cny_per_second": "0.00022", "price_verified_at": "2026-08-23",
        }}, output_dir=str(tmp_path),
        context=SimpleNamespace(task_id="task-1", accepted_max_cost=None),
    )
    provider.prepared_media_cleanup(prepared)
    assert media.exists() is retained
