from video_transcript_api.marks.repository import ContentMarkRepository


def test_content_mark_repository_marks_and_unmarks_transcript(tmp_path):
    repo = ContentMarkRepository(db_path=str(tmp_path / "marks.db"))

    mark = repo.mark(owner_type="transcript", owner_id="view-1", user_key="sk-****0001")
    again = repo.mark(owner_type="transcript", owner_id="view-1", user_key="sk-****0001")

    assert mark["id"] == again["id"]
    assert repo.is_marked("transcript", "view-1", "sk-****0001") is True

    assert repo.unmark("transcript", "view-1", "sk-****0001") is True
    assert repo.is_marked("transcript", "view-1", "sk-****0001") is False


def test_content_marks_are_scoped_by_user_key(tmp_path):
    repo = ContentMarkRepository(db_path=str(tmp_path / "marks.db"))
    repo.mark(owner_type="transcript", owner_id="view-1", user_key="sk-****0001")

    assert repo.is_marked("transcript", "view-1", "sk-****0001") is True
    assert repo.is_marked("transcript", "view-1", "sk-****0002") is False
