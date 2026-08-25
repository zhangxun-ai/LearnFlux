from video_transcript_api.persistence.schema import load_postgres_migrations


def test_review_postgres_migrations_preserve_base_and_extend_schema() -> None:
    migrations = load_postgres_migrations()
    review = next(item for item in migrations if item.name == "0004_review_module.sql")
    extensions = next(
        item for item in migrations
        if item.name == "0005_review_module_extensions.sql"
    )

    assert review.version == 4
    assert review.checksum == (
        "06b52970a0ff73bd5879a9fd4138ce4035f9aa1c7a39bba18405d771cb31f978"
    )
    assert extensions.version == 5
    for table in (
        "review_daily_events",
        "review_weekly_reviews",
        "review_connections",
        "review_action_experiments",
        "review_monthly_reviews",
        "review_annual_reviews",
        "review_insights",
        "review_ai_candidates",
        "review_preferences",
        "review_sync_state",
    ):
        assert f"CREATE TABLE {table}" in review.sql
    for field in (
        "meaning_types_json",
        "source_type",
        "target_type",
        "direction",
        "evidence_span_json",
        "evidence_strength_json",
        "verification_experiment_id",
    ):
        assert field not in review.sql
        assert f"ADD COLUMN {field}" in extensions.sql
