-- The cloud/local control store records every task transition timestamp.
-- Legacy SQLite task_status rows predate this column, so backfill first.

ALTER TABLE task_status ADD COLUMN updated_at TEXT;

UPDATE task_status
SET updated_at = COALESCE(
    completed_at::text,
    created_at::text,
    CURRENT_TIMESTAMP::text
)
WHERE updated_at IS NULL;

ALTER TABLE task_status
    ALTER COLUMN updated_at SET DEFAULT (CURRENT_TIMESTAMP::text),
    ALTER COLUMN updated_at SET NOT NULL;
