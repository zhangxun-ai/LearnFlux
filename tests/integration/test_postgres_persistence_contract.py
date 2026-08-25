"""PostgreSQL persistence contracts for parsed transcription artifacts."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta

import pytest

from video_transcript_api.cache.cache_manager import CacheManager
from video_transcript_api.persistence.schema import migrate_postgres_schema
from video_transcript_api.reading.repository import ReadingRepository
from video_transcript_api.transcriber.control_database import (
    PostgresControlDatabase,
)


pytestmark = pytest.mark.integration

PLATFORM = "postgres_contract"
MEDIA_ID = "artifact-roundtrip"


@pytest.fixture
def database():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("temporary PostgreSQL DSN not provided")
    value = PostgresControlDatabase(dsn)
    migrate_postgres_schema(value)
    with value.transaction() as connection:
        connection.execute(
            "DELETE FROM video_cache WHERE platform = ? AND media_id = ?",
            (PLATFORM, MEDIA_ID),
        )
    try:
        yield value
    finally:
        with value.transaction() as connection:
            connection.execute(
                "DELETE FROM video_cache WHERE platform = ? AND media_id = ?",
                (PLATFORM, MEDIA_ID),
            )
        value.close()


def test_parsed_artifacts_round_trip_without_cache_files(database, tmp_path) -> None:
    cache_root = tmp_path / "cache"
    transcript = {
        "speakers": ["Speaker 1"],
        "segments": [{"speaker": "Speaker 1", "text": "Exact transcript"}],
    }
    first = CacheManager(cache_dir=str(cache_root), database=database)

    saved = first.save_cache(
        platform=PLATFORM,
        url="local://existing/original.mp4",
        media_id=MEDIA_ID,
        use_speaker_recognition=True,
        transcript_data=transcript,
        transcript_type="funasr",
        title="Persistence contract",
        source_language="en",
    )
    assert saved is not None
    assert saved["storage_backend"] == "postgres"
    assert not list(cache_root.rglob("*.json"))
    assert not list(cache_root.rglob("*.txt"))

    assert first.save_llm_result(
        PLATFORM, MEDIA_ID, True, "calibrated", "Calibrated transcript"
    )
    assert first.save_llm_result(
        PLATFORM, MEDIA_ID, True, "summary", "Durable summary"
    )
    assert first.save_llm_result(
        PLATFORM,
        MEDIA_ID,
        True,
        "structured",
        {"chapters": [{"title": "Chapter 1"}]},
    )
    first.save_zh_translation(PLATFORM, MEDIA_ID, "Chinese translation")
    assert first.save_json_artifact(
        PLATFORM,
        MEDIA_ID,
        "speaker_mapping",
        "speaker_mapping.json",
        {"Speaker 1": "Teacher"},
    )
    first.close()

    recreated = CacheManager(cache_dir=str(cache_root), database=database)
    restored = recreated.get_cache(
        platform=PLATFORM,
        media_id=MEDIA_ID,
        use_speaker_recognition=True,
        exact_speaker_match=True,
    )
    recreated.close()

    assert restored is not None
    assert restored["storage_backend"] == "postgres"
    assert restored["file_path"] is None
    assert restored["transcript_data"] == transcript
    assert restored["source_language"] == "en"
    assert restored["llm_calibrated"] == "Calibrated transcript"
    assert restored["llm_summary"] == "Durable summary"
    assert restored["zh_translation"] == "Chinese translation"
    assert restored["llm_processed"]["format_version"] == "v2"
    assert restored["speaker_mapping"] == {"Speaker 1": "Teacher"}

    connection = database.connect()
    try:
        row = connection.execute(
            """
            SELECT content, content_sha256, byte_size
            FROM transcription_artifacts
            WHERE cache_id = ? AND artifact_type = 'llm_summary'
            """,
            (saved["id"],),
        ).fetchone()
    finally:
        connection.close()
    raw = bytes(row["content"])
    assert row["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["byte_size"] == len(raw)


def test_reading_text_timestamps_support_recovery_queries(database) -> None:
    owner = "postgres-reading-contract"
    repository = ReadingRepository(database)
    try:
        repository._connection.execute(
            "DELETE FROM reading_documents WHERE owner_user_id = ?", (owner,)
        )
        repository._connection.commit()
        document = repository.create_document(
            owner_user_id=owner,
            title="Reading contract",
            author=None,
            format="pdf",
            source_path="/external/original.pdf",
            file_sha256="f" * 64,
            file_size=100,
            status="processing",
        )

        recovered = repository.recover_interrupted_pdf_ocr(
            older_than=datetime.now(UTC) + timedelta(minutes=1)
        )
        restored = repository.get_document(owner, document.id)

        assert recovered == 1
        assert restored is not None
        assert restored.status == "needs_ocr"
    finally:
        repository._connection.execute(
            "DELETE FROM reading_documents WHERE owner_user_id = ?", (owner,)
        )
        repository._connection.commit()
        repository.close()
