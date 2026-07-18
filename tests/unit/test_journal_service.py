import pytest

from video_transcript_api.journal.repository import JournalRepository
from video_transcript_api.journal.service import JournalService


def test_journal_service_saves_entry_with_default_title(tmp_path):
    service = JournalService(
        repository=JournalRepository(db_path=str(tmp_path / "journal.db")),
    )

    entry = service.save_entry(
        user_id="user-1",
        entry_date="2026-07-02",
        entry_type="daily",
        title="",
        body="今天把复盘记录收窄到写作页里。\n第二行内容。",
    )

    assert entry["title"] == "今天把复盘记录收窄到写作页里。"
    assert entry["entry_type"] == "daily"


def test_journal_service_lists_month_entries(tmp_path):
    repo = JournalRepository(db_path=str(tmp_path / "journal.db"))
    service = JournalService(repository=repo)
    service.save_entry("user-1", "2026-06-30", "daily", "旧", "旧内容")
    service.save_entry("user-1", "2026-07-01", "daily", "一", "内容一")
    service.save_entry("user-1", "2026-07-02", "note", "二", "内容二")

    entries = service.list_entries("user-1", month="2026-07")

    assert [item["title"] for item in entries] == ["二", "一"]


def test_journal_service_review_uses_entries_and_saves_answer(tmp_path):
    repo = JournalRepository(db_path=str(tmp_path / "journal.db"))
    calls = {}

    def fake_answerer(**kwargs):
        calls.update(kwargs)
        return "观察：真正推进的是收窄范围。下一步保留每日记录。"

    service = JournalService(
        repository=repo,
        llm_config={},
        llm_answerer=fake_answerer,
    )
    service.save_entry("user-1", "2026-07-01", "weekly_plan", "本周计划", "只推进两个目标。")
    service.save_entry("user-1", "2026-07-02", "daily", "今天记录", "把功能放回心流写作。")

    review = service.review(
        user_id="user-1",
        range_start="2026-07-01",
        range_end="2026-07-07",
        question="哪些应该保留？",
    )

    assert review["answer"].startswith("观察")
    assert review["model"] == "deepseek-v4-pro"
    assert review["reasoning_effort"] == "high"
    assert calls["task_type"] == "journal_review"
    assert "哪些应该保留？" in calls["prompt"]
    assert "只推进两个目标" in calls["prompt"]
    assert "把功能放回心流写作" in calls["prompt"]
    assert repo.list_reviews("user-1")[0]["id"] == review["id"]


def test_journal_service_review_requires_records_or_question(tmp_path):
    service = JournalService(
        repository=JournalRepository(db_path=str(tmp_path / "journal.db")),
        llm_answerer=lambda **kwargs: "unused",
    )

    with pytest.raises(ValueError):
        service.review("user-1", "2026-07-01", "2026-07-07", "")
