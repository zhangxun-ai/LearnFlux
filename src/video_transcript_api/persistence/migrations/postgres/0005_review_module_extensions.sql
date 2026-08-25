-- Forward-only additions made after the initial review schema was released.

ALTER TABLE review_daily_events
    ADD COLUMN meaning_types_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE review_daily_events
    ADD COLUMN people_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE review_daily_events
    ADD COLUMN keywords_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE review_connections
    ADD COLUMN source_type TEXT NOT NULL DEFAULT 'daily';
ALTER TABLE review_connections
    ADD COLUMN source_id TEXT NOT NULL DEFAULT '';
ALTER TABLE review_connections
    ADD COLUMN target_type TEXT NOT NULL DEFAULT 'daily';
ALTER TABLE review_connections
    ADD COLUMN target_id TEXT NOT NULL DEFAULT '';
ALTER TABLE review_connections
    ADD COLUMN direction TEXT NOT NULL DEFAULT 'forward';

ALTER TABLE review_action_experiments
    ADD COLUMN desire_check TEXT NOT NULL DEFAULT '';
ALTER TABLE review_action_experiments
    ADD COLUMN control_check TEXT NOT NULL DEFAULT '';
ALTER TABLE review_action_experiments
    ADD COLUMN first_step TEXT NOT NULL DEFAULT '';
ALTER TABLE review_action_experiments
    ADD COLUMN executed TEXT NOT NULL DEFAULT '';
ALTER TABLE review_action_experiments
    ADD COLUMN insight_result TEXT NOT NULL DEFAULT '';
ALTER TABLE review_action_experiments
    ADD COLUMN next_decision TEXT NOT NULL DEFAULT '';

ALTER TABLE review_insights
    ADD COLUMN category TEXT NOT NULL DEFAULT '';
ALTER TABLE review_insights
    ADD COLUMN evidence_span_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE review_insights
    ADD COLUMN evidence_strength_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE review_insights
    ADD COLUMN uncertainty_note TEXT NOT NULL DEFAULT '';
ALTER TABLE review_insights
    ADD COLUMN verification_experiment TEXT NOT NULL DEFAULT '';
ALTER TABLE review_insights
    ADD COLUMN verification_experiment_id TEXT;
