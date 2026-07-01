def test_study_repository_persists_notes(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))

    note = repo.create_note(
        view_token="view-1",
        time_seconds=12.5,
        body="这里需要复看。",
    )

    assert note["view_token"] == "view-1"
    assert note["time_seconds"] == 12.5
    assert note["body"] == "这里需要复看。"

    notes = repo.list_notes("view-1")
    assert [item["id"] for item in notes] == [note["id"]]


def test_study_repository_updates_and_deletes_notes(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    note = repo.create_note("view-1", 30, "初稿")

    updated = repo.update_note(
        note_id=note["id"],
        view_token="view-1",
        body="修改后",
        time_seconds=42,
    )

    assert updated["body"] == "修改后"
    assert updated["time_seconds"] == 42

    assert repo.delete_note(note["id"], "view-1") is True
    assert repo.list_notes("view-1") == []


def test_study_repository_rejects_cross_token_updates(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    note = repo.create_note("view-1", 30, "初稿")

    assert repo.update_note(note["id"], "other-view", "bad", None) is None
    assert repo.delete_note(note["id"], "other-view") is False
    assert len(repo.list_notes("view-1")) == 1
