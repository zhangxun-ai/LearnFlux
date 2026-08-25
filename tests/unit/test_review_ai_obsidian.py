from __future__ import annotations

from pathlib import Path

import pytest

from video_transcript_api.llm import StructuredResult
from video_transcript_api.reviews.ai import ReviewAIAnalyzer
from video_transcript_api.reviews.markdown import (
    MANAGED_END,
    MANAGED_START,
    ReviewMarkdownConflict,
    merge_review_markdown,
    render_review_markdown,
)
from video_transcript_api.reviews.obsidian import ReviewObsidianSyncService
from video_transcript_api.reviews.repository import ReviewDataError, ReviewRepository
from video_transcript_api.reviews.service import ReviewService


@pytest.fixture
def repository(tmp_path):
    repo = ReviewRepository(tmp_path / "review.db")
    try:
        yield repo
    finally:
        repo.close()


def test_review_ai_uses_only_server_resolved_evidence(repository):
    event = repository.create_daily_event(
        "alice", "2026-08-24", {"title": "Meeting", "fact": "I opened with a conclusion"}
    )
    captured = {}

    def fake_answerer(**kwargs):
        captured.update(kwargs)
        return StructuredResult(
            success=True,
            data={
                "candidates": [
                    {
                        "statement": "A possible communication pattern",
                        "tier": "branch",
                        "level": 2,
                        "evidence": [
                            {"source_id": event["id"], "observation": "The conclusion came first"},
                            {"source_id": "invented", "observation": "Must be removed"},
                        ],
                        "counter_evidence": ["Only one event is available"],
                        "uncertainty": 0.8,
                        "follow_up_questions": ["Does this repeat?"],
                        "verification_experiment": "Observe the next meeting",
                    }
                ]
            },
        )

    analyzer = ReviewAIAnalyzer(
        repository,
        {"llm": {"summary_model": "configured-model"}},
        answerer=fake_answerer,
    )
    result = analyzer.analyze(
        "alice", "inner_insight", [{"type": "daily", "id": event["id"]}]
    )

    assert captured["model"] == "configured-model"
    assert captured["response_schema"]["properties"]["candidates"]["maxItems"] == 5
    assert event["fact"] in captured["prompt"]
    assert result[0]["status"] == "candidate"
    assert result[0]["candidate"]["evidence"] == [
        {
            "source_id": event["id"],
            "source_type": "daily",
            "record_date": "2026-08-24",
            "source_excerpt": "I opened with a conclusion",
            "observation": "The conclusion came first",
        }
    ]
    assert result[0]["candidate"]["evidence_strength"] == {
        "label": "证据较少",
        "independent_sources": 1,
        "source_types": ["daily"],
        "counter_evidence": 1,
    }
    assert result[0]["candidate"]["uncertainty_note"]


def test_review_ai_rejects_deep_candidate_when_time_span_is_insufficient(repository):
    event = repository.create_daily_event("alice", "2026-08-24", {"fact": "One event"})

    def fake_answerer(**kwargs):
        return StructuredResult(
            success=True,
            data={
                "candidates": [{
                    "statement": "A root-level conclusion",
                    "tier": "root",
                    "level": 8,
                    "evidence": [{"source_id": event["id"], "observation": "One event"}],
                    "counter_evidence": [],
                    "uncertainty": 0.9,
                    "follow_up_questions": [],
                    "verification_experiment": "Keep observing",
                }]
            },
        )

    analyzer = ReviewAIAnalyzer(repository, {}, answerer=fake_answerer)
    with pytest.raises(ReviewDataError, match="证据不足"):
        analyzer.analyze(
            "alice", "inner_insight", [{"type": "daily", "id": event["id"]}]
        )


def test_annual_ai_supports_the_full_candidate_category_set(repository):
    month = repository.upsert_monthly(
        "alice", "2026-08", {"inner": ["More willing to speak"]}
    )
    captured = {}
    categories = [
        "important_event", "inner_change", "key_action", "delayed_result",
        "important_person", "interest",
    ]

    def fake_answerer(**kwargs):
        captured.update(kwargs)
        return StructuredResult(
            success=True,
            data={
                "candidates": [{
                    "category": category,
                    "statement": f"Candidate for {category}",
                    "tier": "branch",
                    "level": 2,
                    "evidence": [{"source_id": month["id"], "observation": "August source"}],
                    "counter_evidence": [],
                    "uncertainty": 0.5,
                    "uncertainty_note": "Only one month",
                    "follow_up_questions": [],
                    "verification_experiment": "Keep observing",
                } for category in categories]
            },
        )

    analyzer = ReviewAIAnalyzer(repository, {}, answerer=fake_answerer)
    result = analyzer.analyze(
        "alice", "annual_summary", [{"type": "monthly", "id": month["id"]}]
    )

    assert len(result) == len(categories)
    assert captured["response_schema"]["properties"]["candidates"]["maxItems"] == 12
    assert "delayed_result" in captured["prompt"]


def test_confirmed_annual_ai_candidate_appends_without_overwriting_user_summary(repository):
    month = repository.upsert_monthly(
        "alice", "2026-08", {"inner": ["More willing to speak"]}
    )
    repository.upsert_annual("alice", "2026", {"summary": "User-written opening"})
    candidate = repository.create_ai_candidates(
        "alice",
        "annual_summary",
        "Annual summary",
        [{"type": "monthly", "id": month["id"]}],
        [{
            "statement": "Expression became a repeated theme",
            "tier": "branch",
            "level": 2,
            "evidence": [{"source_id": month["id"], "source_type": "monthly"}],
        }],
        "test-model",
    )[0]
    service = ReviewService(repository, {})

    confirmed = service.confirm_ai("alice", candidate["id"])

    assert confirmed["applied_to"]["year"] == "2026"
    annual = repository.get_annual("alice", "2026")
    assert annual["summary"].startswith("User-written opening")
    assert "Expression became a repeated theme" in annual["summary"]
    assert annual["source_ids"] == [
        {"type": "monthly", "id": month["id"], "date": "2026-08", "label": "2026-08"}
    ]


def test_review_markdown_merge_is_idempotent_and_preserves_user_content():
    record = {
        "id": "daily:2026-08-24",
        "period": "2026-08-24",
        "events": [{"id": "dre_1", "title": "One", "fact": "A fact"}],
        "source_ids": ["dre_1"],
        "status": "active",
        "created_at": "2026-08-24T00:00:00+00:00",
        "updated_at": "2026-08-24T01:00:00+00:00",
    }
    fresh = render_review_markdown("daily", record)
    with_user_content = fresh.replace(
        MANAGED_END, f"{MANAGED_END}\n\n## My private notes\nKeep this paragraph."
    )
    updated = {**record, "events": [{"id": "dre_1", "title": "One", "fact": "Updated fact"}]}
    merged = merge_review_markdown(with_user_content, "daily", updated)

    assert "Updated fact" in merged
    assert "Keep this paragraph." in merged
    assert merged.count(MANAGED_START) == 1
    assert merged.count(MANAGED_END) == 1
    assert merge_review_markdown(merged, "daily", updated) == merged


def test_review_markdown_refuses_unmanaged_or_wrong_identity_files():
    record = {"id": "ins_1", "period": "2026-08-24", "statement": "Candidate"}
    with pytest.raises(ReviewMarkdownConflict):
        merge_review_markdown("# Existing private file", "insight", record)

    other = render_review_markdown("insight", {**record, "id": "ins_other"})
    with pytest.raises(ReviewMarkdownConflict):
        merge_review_markdown(other, "insight", record)


def test_obsidian_sync_uses_canonical_path_and_keeps_database_on_conflict(repository, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    event = repository.create_daily_event(
        "alice", "2026-08-24", {"title": "One", "fact": "A fact"}
    )
    syncer = ReviewObsidianSyncService(
        repository,
        {"obsidian": {"enabled": True, "vault_path": str(vault), "review_root": "复盘"}},
    )

    first = syncer.sync("alice", "daily", event["id"])
    expected = vault / "复盘" / "每日" / "2026" / "2026-08-24-每日复盘.md"
    assert first["status"] == "synced"
    assert expected.exists()
    assert "learnflux_managed: true" in expected.read_text(encoding="utf-8")

    second = syncer.sync("alice", "daily", event["id"])
    assert second["status"] == "unchanged"

    expected.write_text("# Private file\n", encoding="utf-8")
    failed = syncer.sync("alice", "daily", event["id"])
    assert failed["status"] == "failed"
    assert "not managed" in failed["error_message"]
    assert repository.get_daily_event("alice", event["id"])["fact"] == "A fact"
    assert expected.read_text(encoding="utf-8") == "# Private file\n"

    expected.unlink()
    retried = syncer.sync("alice", "daily", event["id"])
    assert retried["status"] == "synced"
    assert "A fact" in expected.read_text(encoding="utf-8")


def test_periodic_obsidian_markdown_links_back_to_daily_source(repository, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    event = repository.create_daily_event(
        "alice", "2026-08-24", {"title": "Meeting", "fact": "A visible fact"}
    )
    weekly = repository.upsert_weekly(
        "alice",
        "2026-08-24",
        "2026-08-30",
        {
            "focus_ids": [event["id"]],
            "source_ids": [{"type": "daily", "id": event["id"]}],
        },
    )
    syncer = ReviewObsidianSyncService(
        repository,
        {"obsidian": {"enabled": True, "vault_path": str(vault), "review_root": "复盘"}},
    )

    assert syncer.sync("alice", "daily", event["id"])["status"] == "synced"
    assert syncer.sync("alice", "weekly", weekly["id"])["status"] == "synced"
    daily_text = (vault / "复盘" / "每日" / "2026" / "2026-08-24-每日复盘.md").read_text(encoding="utf-8")
    weekly_text = (vault / "复盘" / "周度" / "2026" / "2026-W35-周度复盘.md").read_text(encoding="utf-8")
    assert f"^{event['id']}" in daily_text
    assert f"[[复盘/每日/2026/2026-08-24-每日复盘#^{event['id']}|Meeting]]" in weekly_text


def test_periodic_saves_refresh_daily_obsidian_backlinks(repository, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    service = ReviewService(
        repository,
        {"obsidian": {"enabled": True, "vault_path": str(vault), "review_root": "复盘"}},
    )
    daily = service.create_daily(
        "alice", "2026-08-24", {"title": "Meeting", "fact": "A visible fact"}
    )["record"]
    daily_path = vault / "复盘" / "每日" / "2026" / "2026-08-24-每日复盘.md"

    service.save_weekly("alice", "2026-08-24", {"focus_ids": [daily["id"]]})
    assert "[[复盘/周度/2026/2026-W35-周度复盘|2026-08-24]]" in daily_path.read_text(encoding="utf-8")

    service.save_monthly("alice", "2026-08", {"inner": ["A thought"]})
    assert "[[复盘/月度/2026/2026-08-月度复盘|2026-08]]" in daily_path.read_text(encoding="utf-8")

    experiment = service.create_experiment(
        "alice",
        {"title": "Start small", "source_ids": [daily["id"]]},
    )["record"]
    assert "[[复盘/行动实验/Start small|Start small]]" in daily_path.read_text(encoding="utf-8")

    assert service.delete_experiment("alice", experiment["id"]) is True
    assert "复盘/行动实验/Start small" not in daily_path.read_text(encoding="utf-8")


def test_obsidian_disabled_records_not_configured_without_touching_files(repository, tmp_path):
    event = repository.create_daily_event("alice", "2026-08-24", {"title": "One"})
    syncer = ReviewObsidianSyncService(repository, {"obsidian": {"enabled": False}})
    state = syncer.sync("alice", "daily", event["id"])
    assert state["status"] == "not_configured"
    assert list(Path(tmp_path).rglob("*.md")) == []
