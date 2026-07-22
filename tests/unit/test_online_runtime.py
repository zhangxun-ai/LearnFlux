from __future__ import annotations

import os

import pytest

from video_transcript_api.transcriber.online_runtime import (
    OnlineRuntimeConfigError,
    OnlineRuntimeSettings,
    load_project_dotenv,
)


_ONLINE_NAMES = {
    "LEARNFLUX_PERSISTENCE_BACKEND",
    "DATABASE_URL",
    "LEARNFLUX_OBJECT_BACKEND",
    "LEARNFLUX_S3_ENDPOINT_URL",
    "LEARNFLUX_S3_BUCKET",
    "LEARNFLUX_S3_REGION",
    "LEARNFLUX_S3_ACCESS_KEY_ID",
    "LEARNFLUX_S3_SECRET_ACCESS_KEY",
    "LEARNFLUX_S3_PRESIGN_TTL_SECONDS",
    "LEARNFLUX_SOURCE_RETENTION_DAYS",
}


def _valid_saas_environ() -> dict[str, str]:
    return {
        "LEARNFLUX_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://runtime-user:secret-value@db.invalid/app",
        "LEARNFLUX_OBJECT_BACKEND": "s3",
        "LEARNFLUX_S3_ENDPOINT_URL": "https://account.invalid",
        "LEARNFLUX_S3_BUCKET": "private-media",
        "LEARNFLUX_S3_REGION": "auto",
        "LEARNFLUX_S3_ACCESS_KEY_ID": "access-id",
        "LEARNFLUX_S3_SECRET_ACCESS_KEY": "secret-value",
    }


def test_online_runtime_defaults_to_local() -> None:
    settings = OnlineRuntimeSettings.from_environ({})

    assert settings.persistence_backend == "sqlite"
    assert settings.object_backend == "local"
    assert settings.presign_ttl_seconds == 900
    assert settings.source_retention_days == 7


def test_postgres_s3_settings_keep_secrets_out_of_repr() -> None:
    settings = OnlineRuntimeSettings.from_environ(_valid_saas_environ())

    assert settings.persistence_backend == "postgres"
    assert settings.object_backend == "s3"
    rendered = repr(settings)
    assert "secret-value" not in rendered
    assert "access-id" not in rendered
    assert "postgresql://" not in rendered


def test_incomplete_s3_configuration_fails_closed_without_values() -> None:
    with pytest.raises(OnlineRuntimeConfigError) as raised:
        OnlineRuntimeSettings.from_environ({"LEARNFLUX_OBJECT_BACKEND": "s3"})

    assert str(raised.value) == "s3_config_incomplete"


@pytest.mark.parametrize(
    ("name", "value", "code"),
    [
        ("LEARNFLUX_PERSISTENCE_BACKEND", "mysql", "invalid_persistence_backend"),
        ("LEARNFLUX_OBJECT_BACKEND", "public", "invalid_object_backend"),
        ("LEARNFLUX_S3_PRESIGN_TTL_SECONDS", "0", "invalid_presign_ttl"),
        ("LEARNFLUX_SOURCE_RETENTION_DAYS", "false", "invalid_source_retention"),
    ],
)
def test_invalid_runtime_values_fail_closed(name: str, value: str, code: str) -> None:
    environ = {name: value}
    with pytest.raises(OnlineRuntimeConfigError, match=f"^{code}$"):
        OnlineRuntimeSettings.from_environ(environ)


def test_dotenv_does_not_override_exported_environment(tmp_path, monkeypatch) -> None:
    for name in _ONLINE_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LEARNFLUX_PERSISTENCE_BACKEND", "sqlite")
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LEARNFLUX_PERSISTENCE_BACKEND=postgres\n"
        "DATABASE_URL=postgresql://dotenv.invalid/app\n",
        encoding="utf-8",
    )

    load_project_dotenv(dotenv_path)

    assert os.environ["LEARNFLUX_PERSISTENCE_BACKEND"] == "sqlite"
    assert os.environ["DATABASE_URL"] == "postgresql://dotenv.invalid/app"


def test_postgres_runtime_shares_one_control_store_with_task_quote_and_usage(
    monkeypatch,
) -> None:
    from video_transcript_api.api import context

    settings = OnlineRuntimeSettings(
        persistence_backend="postgres",
        database_url="postgresql://not-opened.invalid/app",
    )

    class FakeStore:
        database = object()
        quote_repository = object()
        usage_repository = object()

    class FakeCacheManager:
        def __init__(self, cache_dir):
            self.cache_dir = cache_dir
            self.task_repository = None

        def set_task_status_repository(self, repository):
            self.task_repository = repository

    fake_store = FakeStore()
    monkeypatch.setattr(context, "get_online_runtime_settings", lambda: settings)
    monkeypatch.setattr(context, "get_config", lambda: {"storage": {"cache_dir": "cache"}})
    monkeypatch.setattr(context, "CacheManager", FakeCacheManager)
    monkeypatch.setattr(
        context,
        "PostgresTranscriptionControlStore",
        lambda database_url: fake_store,
    )
    context.get_transcription_control_store.cache_clear()
    context.get_cache_manager.cache_clear()
    try:
        manager = context.get_cache_manager()

        assert manager.task_repository is fake_store
        assert context.get_cloud_quote_repository() is fake_store.quote_repository
        assert context.get_usage_repository() is fake_store.usage_repository
    finally:
        context.get_transcription_control_store.cache_clear()
        context.get_cache_manager.cache_clear()
