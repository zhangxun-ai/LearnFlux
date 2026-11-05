-- History visibility is independent of shared results, task state and audit logs.
CREATE TABLE IF NOT EXISTS task_history_hidden (
    user_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, task_id)
);
