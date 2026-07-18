import pytest


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


def test_study_context_keys_use_utf8_byte_lengths():
    from video_transcript_api.study.repository import build_study_context_key

    assert build_study_context_key("课|一") == "single|7|课|一"
    assert (
        build_study_context_key("retry-view", collection_id="合集", source_id="第|1课")
        == "collection|6|合集|8|第|1课"
    )


def test_note_document_is_stable_across_collection_view_token_changes(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    first = repo.get_or_create_note_document(
        owner_user_id="user-1",
        view_token="view-old",
        collection_id="course-1",
        source_id="lesson-1",
    )
    updated = repo.update_note_document(
        owner_user_id="user-1",
        view_token="view-old",
        collection_id="course-1",
        source_id="lesson-1",
        body="持续编辑的正文",
        expected_revision=first["revision"],
    )

    retried = repo.get_or_create_note_document(
        owner_user_id="user-1",
        view_token="view-new",
        collection_id="course-1",
        source_id="lesson-1",
    )

    assert retried["id"] == first["id"]
    assert retried["body"] == updated["body"]
    assert retried["current_view_token"] == "view-new"
    assert retried["revision"] == updated["revision"]


def test_single_note_documents_are_context_isolated_and_revision_checked(tmp_path):
    from video_transcript_api.study.repository import (
        StudyRepository,
        StudyRevisionConflict,
    )

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    first = repo.get_or_create_note_document(owner_user_id="user-1", view_token="view-1")
    second = repo.get_or_create_note_document(owner_user_id="user-1", view_token="view-2")

    saved = repo.update_note_document(
        owner_user_id="user-1",
        view_token="view-1",
        body="new body",
        expected_revision=first["revision"],
    )

    assert first["id"] != second["id"]
    assert saved["revision"] == first["revision"] + 1
    with pytest.raises(StudyRevisionConflict) as conflict:
        repo.update_note_document(
            owner_user_id="user-1",
            view_token="view-1",
            body="stale overwrite",
            expected_revision=first["revision"],
        )
    assert conflict.value.current["body"] == "new body"


def test_note_document_migrates_legacy_single_notes_once_in_stable_order(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    repo.create_note("view-1", None, "最后", owner_user_id="")
    repo.create_note("view-1", 30, "第二", owner_user_id="user-1")
    repo.create_note("view-1", 10, "第一", owner_user_id=None)
    repo.create_note("view-1", 20, "不属于当前用户", owner_user_id="user-2")
    repo.create_note("view-1", 15, "   ", owner_user_id="user-1")

    migrated = repo.get_or_create_note_document(
        owner_user_id="user-1",
        view_token="view-1",
        claim_unowned_single_legacy=True,
    )
    again = repo.get_or_create_note_document(
        owner_user_id="user-1",
        view_token="view-1",
        claim_unowned_single_legacy=True,
    )

    assert migrated["body"] == "第一\n\n第二\n\n最后"
    assert again["id"] == migrated["id"]
    assert len(repo.list_notes("view-1", owner_user_id="user-1")) == 2


def test_collection_legacy_migration_never_claims_unowned_rows(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    repo.create_note(
        "view-1", 5, "owned", owner_user_id="user-1", collection_id="course", source_id="lesson"
    )
    repo.create_note(
        "view-1", 1, "unowned", owner_user_id="", collection_id="course", source_id="lesson"
    )

    document = repo.get_or_create_note_document(
        owner_user_id="user-1",
        view_token="view-1",
        collection_id="course",
        source_id="lesson",
    )

    assert document["body"] == "owned"


def test_binding_revision_and_collection_inheritance(tmp_path):
    from video_transcript_api.study.repository import (
        StudyRepository,
        StudyRevisionConflict,
    )

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    binding = repo.save_obsidian_binding(
        owner_user_id="user-1",
        scope_type="collection",
        scope_id="course-1",
        vault_id="vault-1",
        transcript_directory="raw/course-1",
        note_directory="course-1/笔记",
        expected_revision=None,
    )

    inherited = repo.get_obsidian_binding(
        owner_user_id="user-1",
        scope_type="collection",
        scope_id="course-1",
        vault_id="vault-1",
    )
    assert inherited == binding

    changed = repo.save_obsidian_binding(
        owner_user_id="user-1",
        scope_type="collection",
        scope_id="course-1",
        vault_id="vault-1",
        transcript_directory="raw/course-new",
        note_directory="course-new/笔记",
        expected_revision=binding["revision"],
    )
    assert changed["revision"] == binding["revision"] + 1

    with pytest.raises(StudyRevisionConflict):
        repo.save_obsidian_binding(
            owner_user_id="user-1",
            scope_type="collection",
            scope_id="course-1",
            vault_id="vault-1",
            transcript_directory="raw/stale",
            note_directory="stale/笔记",
            expected_revision=binding["revision"],
        )


def test_binding_change_resets_all_collection_source_sync_state(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    binding = repo.save_obsidian_binding(
        owner_user_id="user-1",
        scope_type="collection",
        scope_id="course-1",
        vault_id="vault-1",
        transcript_directory="raw/course-1",
        note_directory="course-1/笔记",
        expected_revision=None,
    )
    for source_id in ("lesson-1", "lesson-2"):
        repo.update_obsidian_source_sync(
            owner_user_id="user-1",
            view_token=f"view-{source_id}",
            collection_id="course-1",
            source_id=source_id,
            transcript_relative_path=f"raw/course-1/{source_id}.md",
            transcript_synced_hash="transcript-hash",
            note_relative_path=f"course-1/笔记/{source_id}.md",
            note_body_synced_hash="note-body-hash",
            note_managed_hash="note-file-hash",
        )

    repo.save_obsidian_binding(
        owner_user_id="user-1",
        scope_type="collection",
        scope_id="course-1",
        vault_id="vault-1",
        transcript_directory="raw/course-new",
        note_directory="course-new/笔记",
        expected_revision=binding["revision"],
    )

    for source_id in ("lesson-1", "lesson-2"):
        state = repo.get_obsidian_source_sync(
            owner_user_id="user-1",
            view_token=f"view-{source_id}",
            collection_id="course-1",
            source_id=source_id,
        )
        assert state["transcript_relative_path"] is None
        assert state["transcript_synced_hash"] is None
        assert state["note_relative_path"] is None
        assert state["note_body_synced_hash"] is None
        assert state["note_managed_hash"] is None


def test_collection_source_sync_state_survives_view_token_retry(tmp_path):
    from video_transcript_api.study.repository import StudyRepository

    repo = StudyRepository(db_path=str(tmp_path / "study.db"))
    saved = repo.update_obsidian_source_sync(
        owner_user_id="user-1",
        view_token="view-old",
        collection_id="course-1",
        source_id="lesson-1",
        note_relative_path="course-1/笔记/lesson.md",
        note_body_synced_hash="baseline",
    )
    retried = repo.update_obsidian_source_sync(
        owner_user_id="user-1",
        view_token="view-new",
        collection_id="course-1",
        source_id="lesson-1",
    )

    assert retried["id"] == saved["id"]
    assert retried["current_view_token"] == "view-new"
    assert retried["note_relative_path"] == saved["note_relative_path"]
    assert retried["note_body_synced_hash"] == "baseline"
