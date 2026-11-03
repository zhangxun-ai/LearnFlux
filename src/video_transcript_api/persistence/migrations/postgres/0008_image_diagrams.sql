-- Private source snapshots and versioned manually requested image diagrams.
CREATE TABLE image_diagram_jobs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    view_token TEXT NOT NULL,
    request_key TEXT NOT NULL UNIQUE,
    recipe_key TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    request_json TEXT NOT NULL,
    source_json TEXT NOT NULL,
    plan_json TEXT,
    review_json TEXT,
    usage_json TEXT,
    image_key TEXT,
    error_code TEXT,
    parent_id TEXT,
    generation_token TEXT NOT NULL DEFAULT '',
    submitted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_image_diagram_source_created
    ON image_diagram_jobs(owner_user_id, view_token, created_at);
CREATE INDEX idx_image_diagram_recipe
    ON image_diagram_jobs(owner_user_id, view_token, recipe_key, created_at);
CREATE INDEX idx_image_diagram_queue
    ON image_diagram_jobs(status, created_at);
CREATE UNIQUE INDEX ux_image_diagram_active_source
    ON image_diagram_jobs(owner_user_id, view_token)
    WHERE status IN ('queued', 'planning', 'generating', 'reviewing');
