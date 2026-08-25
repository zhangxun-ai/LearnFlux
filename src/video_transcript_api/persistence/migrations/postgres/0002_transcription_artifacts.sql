-- Parsed transcript and LLM outputs belong in PostgreSQL.
-- Raw source media remains external and is referenced by path/hash only.

CREATE TABLE transcription_artifacts (
    cache_id BIGINT NOT NULL REFERENCES video_cache(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    content BYTEA NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cache_id, artifact_type)
);

CREATE INDEX idx_transcription_artifacts_type
    ON transcription_artifacts(artifact_type);
