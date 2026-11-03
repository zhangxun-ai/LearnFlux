-- Durable, non-secret options for ordinary local URL task recovery.
CREATE TABLE IF NOT EXISTS task_requests (
    task_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    recovery_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
