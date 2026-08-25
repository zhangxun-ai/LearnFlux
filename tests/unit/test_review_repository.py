from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest

from video_transcript_api.reviews.periods import (
    iso_week_key,
    month_period,
    week_period,
    year_period,
)
from video_transcript_api.reviews.repository import ReviewDataError, ReviewRepository
from video_transcript_api.transcriber.control_database import CompatRow


class _AggregateCursor:
    def __init__(self, rows):
        self._rows = iter(rows)
        self._current = None

    def execute(self, _statement, _parameters):
        self._current = next(self._rows)
        return self

    def fetchone(self):
        return self._current

    def close(self):
        return None


class _AggregateConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _AggregateDatabase:
    dialect = "postgres"

    def __init__(self, rows):
        self._connection = _AggregateConnection(_AggregateCursor(rows))

    @contextmanager
    def transaction(self):
        yield self._connection


@pytest.fixture
def repository(tmp_path):
    repo = ReviewRepository(tmp_path / "review.db")
    try:
        yield repo
    finally:
        repo.close()


def test_review_periods_use_monday_and_inclusive_calendar_bounds():
    week = week_period("2026-08-26")
    assert week.start == date(2026, 8, 24)
    assert week.end == date(2026, 8, 30)
    assert iso_week_key(week.start) == "2026-W35"

    leap_month = month_period("2024-02")
    assert leap_month.start.isoformat() == "2024-02-01"
    assert leap_month.end.isoformat() == "2024-02-29"
    assert year_period("2026").end.isoformat() == "2026-12-31"


def test_evidence_overview_reads_postgres_compat_rows_by_index():
    database = _AggregateDatabase(
        [
            CompatRow(
                ["count", "min", "max"],
                [2, "2026-08-01", "2026-08-24"],
            ),
            CompatRow(["count"], [3]),
            CompatRow(["count"], [1]),
        ]
    )
    repository = object.__new__(ReviewRepository)
    repository.database = database
    repository._is_postgres = True
    repository.db_path = None

    overview = repository.evidence_overview("alice")

    assert overview["daily_events"] == 2
    assert overview["weekly_reviews"] == 3
    assert overview["monthly_reviews"] == 1
    assert overview["first_date"] == "2026-08-01"
    assert overview["last_date"] == "2026-08-24"
    assert overview["span_days"] == 24


def test_daily_events_are_multi_record_owner_scoped_and_reorderable(repository):
    first = repository.create_daily_event(
        "alice",
        "2026-08-24",
        {
            "title": "First",
            "fact": "A visible fact",
            "people": ["Alex"],
            "keywords": ["meeting"],
            "meaning_types": ["learning", "joy"],
            "past": {"thoughts": "I hesitated"},
            "present": {"new_view": "There may be another explanation"},
            "emotions": [{"name": "担心"}],
        },
    )
    second = repository.create_daily_event(
        "alice", "2026-08-24", {"title": "Second", "fact": "Another fact"}
    )
    repository.create_daily_event("bob", "2026-08-24", {"title": "Private"})

    items = repository.list_daily_events("alice", review_date="2026-08-24")
    assert [item["id"] for item in items] == [first["id"], second["id"]]
    assert items[0]["past"] == {"thoughts": "I hesitated"}
    assert items[0]["present"]["new_view"].startswith("There may")
    assert items[0]["emotions"] == [{"name": "担心"}]
    assert items[0]["people"] == ["Alex"]
    assert items[0]["keywords"] == ["meeting"]
    assert items[0]["meaning_types"] == ["learning", "joy"]
    assert repository.get_daily_event("bob", first["id"]) is None

    reordered = repository.reorder_daily_events(
        "alice", "2026-08-24", [second["id"], first["id"]]
    )
    assert [item["id"] for item in reordered] == [second["id"], first["id"]]
    with pytest.raises(ReviewDataError):
        repository.reorder_daily_events("alice", "2026-08-24", [first["id"]])


def test_daily_update_duplicate_delete_and_search(repository):
    event = repository.create_daily_event(
        "alice", "2026-08-24", {"title": "表达", "meaning_type": "learning"}
    )
    updated = repository.update_daily_event(
        "alice",
        event["id"],
        {"quick_meaning": "先说结论", "emotions": [{"name": "期待"}]},
    )
    assert updated["quick_meaning"] == "先说结论"
    duplicate = repository.duplicate_daily_event("alice", event["id"])
    assert duplicate["id"] != event["id"]
    assert duplicate["title"].endswith("（副本）")

    found = repository.search(
        "alice", keyword="结论", meaning_type="learning", emotion="期待"
    )
    assert {item["id"] for item in found} == {event["id"], duplicate["id"]}
    assert repository.delete_daily_event("alice", duplicate["id"]) is True
    assert repository.delete_daily_event("alice", duplicate["id"]) is False


def test_periodic_reviews_connections_experiments_and_insights(repository):
    event = repository.create_daily_event("alice", "2026-08-24", {"title": "Source"})
    target = repository.create_daily_event("alice", "2026-08-25", {"title": "Target"})
    weekly = repository.upsert_weekly(
        "alice",
        "2026-08-24",
        "2026-08-30",
        {
            "focus_ids": [event["id"]],
            "abstraction": {"1": "A repeatable observation"},
            "source_ids": [event["id"]],
        },
    )
    repository.upsert_weekly(
        "alice", "2026-08-24", "2026-08-30", {"summary": "Updated"}
    )
    assert repository.get_weekly("alice", "2026-08-24")["id"] == weekly["id"]
    assert repository.get_weekly("alice", "2026-08-24")["summary"] == "Updated"

    connection = repository.create_connection(
        "alice",
        {
            "period_type": "weekly",
            "period_key": "2026-08-24",
            "connection_type": "unexpected",
            "title": "Two contexts",
            "source_id": event["id"],
            "target_id": target["id"],
            "direction": "forward",
        },
    )
    assert repository.list_connections(
        "alice", period_type="weekly", period_key="2026-08-24"
    )[0]["connection_type"] == "unexpected"
    assert connection["source_id"] == event["id"]
    assert connection["target_id"] == target["id"]
    assert repository.update_connection(
        "alice", connection["id"], {"direction": "bidirectional"}
    )["direction"] == "bidirectional"
    assert repository.get_connection("bob", connection["id"]) is None

    experiment = repository.create_experiment(
        "alice",
        {
            "period_key": "2026-08-24",
            "title": "Open with one sentence",
            "why": "Test the observation",
            "what": "Say the conclusion first",
            "review_date": "2026-08-31",
            "desire_check": "yes",
            "control_check": "partial",
            "first_step": "Write one sentence",
            "source_ids": [event["id"]],
        },
    )
    assert experiment["why"] == "Test the observation"
    assert repository.list_experiments("alice")[0]["what"] == "Say the conclusion first"
    assert experiment["desire_check"] == "yes"
    assert experiment["first_step"] == "Write one sentence"

    monthly = repository.upsert_monthly(
        "alice",
        "2026-08",
        {"inner": ["担心"], "actions": ["先说结论"], "results": ["被听见"]},
    )
    annual = repository.upsert_annual(
        "alice", "2026", {"keywords": ["表达"], "source_ids": [monthly["id"]]}
    )
    assert repository.source("alice", "annual", annual["id"])["keywords"] == ["表达"]

    insight = repository.create_insight(
        "alice",
        {
            "tier": "trunk",
            "level": 5,
            "statement": "I prepare to reduce uncertainty",
            "evidence": [{"source_id": event["id"], "observation": "Repeated"}],
            "counter_evidence": ["Sometimes preparation is quick"],
            "source_ids": [event["id"]],
            "uncertainty": 0.4,
            "uncertainty_note": "Only two events",
            "evidence_strength": {"label": "证据较少", "independent_sources": 1},
            "verification_experiment": "Observe the next meeting",
        },
    )
    assert repository.get_insight("alice", insight["id"])["counter_evidence"]
    assert repository.get_insight("alice", insight["id"])["evidence_strength"]["label"] == "证据较少"
    assert repository.update_insight(
        "alice", insight["id"], {"status": "verified"}
    )["status"] == "verified"
    overview = repository.evidence_overview("alice")
    assert overview["daily_events"] == 2
    assert overview["max_level"] == 3
    active_types = {
        item["record_type"] for item in repository.search("alice", status="active")
    }
    draft_types = {
        item["record_type"] for item in repository.search("alice", status="draft")
    }
    assert active_types == {"daily"}
    assert {"weekly", "monthly", "annual"} <= draft_types
    assert {item["record_type"] for item in repository.search("alice", status="verified")} == {"insight"}


def test_ai_candidates_require_explicit_confirmation(repository):
    event = repository.create_daily_event("alice", "2026-08-24", {"title": "Source"})
    candidates = repository.create_ai_candidates(
        "alice",
        "inner_insight",
        "Find a candidate",
        [{"type": "daily", "id": event["id"]}],
        [{"statement": "Possible pattern", "evidence": [{"source_id": event["id"]}]}],
        "test-model",
    )
    candidate = candidates[0]
    assert candidate["status"] == "candidate"
    assert repository.list_insights("alice") == []

    confirmed = repository.confirm_ai_candidate(
        "alice", candidate["id"], {"statement": "Edited by user"}
    )
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_content"]["statement"] == "Edited by user"
    assert repository.confirm_ai_candidate("alice", candidate["id"], {}) is None


def test_preferences_and_sync_state_are_owner_scoped(repository):
    preferences = repository.save_preferences(
        "alice", {"newbie_mode": False, "week_start_day": 6, "obsidian_root": "我的复盘"}
    )
    assert preferences["newbie_mode"] is False
    assert preferences["week_start_day"] == 6
    assert repository.get_preferences("bob")["newbie_mode"] is True

    state = repository.save_sync_state(
        "alice", "daily", "dre_test", status="failed", error_message="vault unavailable"
    )
    assert state["status"] == "failed"
    assert repository.get_sync_state("bob", "daily", "dre_test") is None
