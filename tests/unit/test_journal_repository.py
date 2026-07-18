from video_transcript_api.journal.repository import JournalRepository


def test_journal_repository_upserts_entry_by_user_date_and_type(tmp_path):
    repo = JournalRepository(db_path=str(tmp_path / "journal.db"))

    first = repo.upsert_entry(
        user_id="user-1",
        entry_date="2026-07-02",
        entry_type="daily",
        title="早上记录",
        body="今天先记录真实发生了什么。",
    )
    second = repo.upsert_entry(
        user_id="user-1",
        entry_date="2026-07-02",
        entry_type="daily",
        title="晚上记录",
        body="晚上补充复盘。",
    )

    assert second["id"] == first["id"]
    assert second["title"] == "晚上记录"
    assert second["body"] == "晚上补充复盘。"
    assert len(repo.list_entries("user-1")) == 1


def test_journal_repository_lists_entries_and_reviews_per_user(tmp_path):
    repo = JournalRepository(db_path=str(tmp_path / "journal.db"))
    repo.upsert_entry("user-1", "2026-07-01", "daily", "A", "内容 A")
    repo.upsert_entry("user-1", "2026-07-02", "weekly_review", "B", "内容 B")
    repo.upsert_entry("user-2", "2026-07-03", "daily", "C", "内容 C")

    entries = repo.list_entries(
        user_id="user-1",
        start_date="2026-07-01",
        end_date="2026-07-31",
    )

    assert [item["entry_date"] for item in entries] == ["2026-07-02", "2026-07-01"]
    assert {item["user_id"] for item in entries} == {"user-1"}

    review = repo.create_review(
        user_id="user-1",
        range_start="2026-07-01",
        range_end="2026-07-07",
        question="卡住在哪里？",
        answer="卡在边界不清。",
        model="deepseek-v4-pro",
        reasoning_effort="high",
    )

    assert repo.list_reviews("user-1")[0]["id"] == review["id"]
    assert repo.list_reviews("user-2") == []
