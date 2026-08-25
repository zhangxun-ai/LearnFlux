-- LearnFlux personal review records and confirmation/sync lineage.

CREATE TABLE review_daily_events (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, review_date TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '',
    fact TEXT NOT NULL DEFAULT '', quick_meaning TEXT NOT NULL DEFAULT '',
    meaning_type TEXT NOT NULL DEFAULT '', meaning_custom TEXT NOT NULL DEFAULT '',
    past_json TEXT NOT NULL DEFAULT '{}', present_json TEXT NOT NULL DEFAULT '{}',
    emotions_json TEXT NOT NULL DEFAULT '[]', source_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_review_daily_user_date ON review_daily_events(user_id, review_date DESC, position);

CREATE TABLE review_weekly_reviews (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, week_start TEXT NOT NULL, week_end TEXT NOT NULL,
    focus_ids_json TEXT NOT NULL DEFAULT '[]', abstraction_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '', source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(user_id, week_start)
);
CREATE INDEX idx_review_weekly_user_start ON review_weekly_reviews(user_id, week_start DESC);

CREATE TABLE review_connections (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, period_type TEXT NOT NULL,
    period_key TEXT NOT NULL, connection_type TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '', source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_review_connections_period ON review_connections(user_id, period_type, period_key, updated_at DESC);

CREATE TABLE review_action_experiments (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, period_key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '', why_text TEXT NOT NULL DEFAULT '', what_text TEXT NOT NULL DEFAULT '',
    who_text TEXT NOT NULL DEFAULT '', when_text TEXT NOT NULL DEFAULT '', where_text TEXT NOT NULL DEFAULT '',
    how_text TEXT NOT NULL DEFAULT '', resources TEXT NOT NULL DEFAULT '', budget TEXT NOT NULL DEFAULT '',
    success_signal TEXT NOT NULL DEFAULT '', review_date TEXT, result TEXT NOT NULL DEFAULT '',
    source_ids_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_review_experiments_user_review ON review_action_experiments(user_id, review_date, updated_at DESC);

CREATE TABLE review_monthly_reviews (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, month_key TEXT NOT NULL,
    inner_json TEXT NOT NULL DEFAULT '[]', actions_json TEXT NOT NULL DEFAULT '[]',
    results_json TEXT NOT NULL DEFAULT '[]', notes_json TEXT NOT NULL DEFAULT '[]',
    cross_month_json TEXT NOT NULL DEFAULT '[]', affirmation TEXT NOT NULL DEFAULT '',
    source_ids_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id, month_key)
);
CREATE INDEX idx_review_monthly_user_month ON review_monthly_reviews(user_id, month_key DESC);

CREATE TABLE review_annual_reviews (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, year_key TEXT NOT NULL,
    keywords_json TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '',
    cross_month_json TEXT NOT NULL DEFAULT '[]', source_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(user_id, year_key)
);
CREATE INDEX idx_review_annual_user_year ON review_annual_reviews(user_id, year_key DESC);

CREATE TABLE review_insights (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, tier TEXT NOT NULL, level INTEGER NOT NULL,
    statement TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '[]',
    counter_evidence_json TEXT NOT NULL DEFAULT '[]', uncertainty DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    source_ids_json TEXT NOT NULL DEFAULT '[]', ai_candidate_id TEXT,
    status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_review_insights_user_tier_status ON review_insights(user_id, tier, status, updated_at DESC);

CREATE TABLE review_ai_candidates (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, analysis_type TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '', scope_json TEXT NOT NULL DEFAULT '[]',
    candidate_json TEXT NOT NULL DEFAULT '{}', confirmed_content_json TEXT,
    model TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, confirmed_at TEXT
);
CREATE INDEX idx_review_ai_user_status ON review_ai_candidates(user_id, status, created_at DESC);

CREATE TABLE review_preferences (
    user_id TEXT PRIMARY KEY, newbie_mode INTEGER NOT NULL DEFAULT 1,
    week_start_day INTEGER NOT NULL DEFAULT 0, obsidian_root TEXT NOT NULL DEFAULT '复盘',
    updated_at TEXT NOT NULL
);

CREATE TABLE review_sync_state (
    user_id TEXT NOT NULL, record_type TEXT NOT NULL, record_id TEXT NOT NULL,
    relative_path TEXT, content_hash TEXT, status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT, synced_at TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, record_type, record_id)
);
CREATE INDEX idx_review_sync_user_status ON review_sync_state(user_id, status, updated_at DESC);
