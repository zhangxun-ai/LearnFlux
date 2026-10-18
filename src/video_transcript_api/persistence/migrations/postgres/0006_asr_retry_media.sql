CREATE TABLE IF NOT EXISTS asr_retry_media (
    task_id TEXT PRIMARY KEY,
    media_ref TEXT NOT NULL,
    media_sha256 TEXT NOT NULL,
    continuation_json TEXT NOT NULL,
    state TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
