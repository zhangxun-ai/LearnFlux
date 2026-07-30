"""Contracts for the independent Obsidian knowledge persistence."""

import pytest


def test_collection_binding_is_shared_by_all_sources_and_revision_guarded(tmp_path):
    from video_transcript_api.obsidian.knowledge_repository import (
        KnowledgeRevisionConflict,
        ObsidianKnowledgeRepository,
    )

    repo = ObsidianKnowledgeRepository(tmp_path / "knowledge.db")
    created = repo.save_binding(
        owner_user_id="u1", scope_type="collection", scope_id="c1", vault_id="v1",
        category="分类", collection_directory="合集", expected_revision=None,
    )
    assert created["revision"] == 1
    assert repo.get_binding("u1", "collection", "c1", "v1")["id"] == created["id"]
    with pytest.raises(KnowledgeRevisionConflict):
        repo.save_binding(
            owner_user_id="u1", scope_type="collection", scope_id="c1", vault_id="v1",
            category="新分类", collection_directory="合集", expected_revision=99,
        )


def test_context_sync_is_reused_after_collection_retry_and_cleared_on_binding_change(tmp_path):
    from video_transcript_api.obsidian.knowledge_repository import ObsidianKnowledgeRepository
    from video_transcript_api.study.repository import build_study_context_key

    repo = ObsidianKnowledgeRepository(tmp_path / "knowledge.db")
    binding = repo.save_binding("u", "collection", "c", "v", "A", "C", None)
    key = build_study_context_key("old", "c", "s")
    repo.update_sync_state("u", key, "old", "c", "s", raw_relative_path="raw/A/C/a.md", raw_synced_hash="r")
    assert repo.get_sync_state("u", build_study_context_key("new", "c", "s"))["raw_relative_path"] == "raw/A/C/a.md"
    repo.save_binding("u", "collection", "c", "v", "B", "C", binding["revision"])
    assert repo.get_sync_state("u", key) is None


def test_sync_context_is_isolated_by_owner_and_single_binding_change_clears_only_knowledge(tmp_path):
    from video_transcript_api.obsidian.knowledge_repository import ObsidianKnowledgeRepository
    from video_transcript_api.study.repository import StudyRepository, build_study_context_key

    database = tmp_path / "shared.db"
    study = StudyRepository(db_path=str(database))
    repo = ObsidianKnowledgeRepository(database)
    context_key = build_study_context_key("same-view")
    binding = repo.save_binding("u1", "single", "same-view", "v", "A", "", None)
    repo.update_sync_state("u1", context_key, "same-view", raw_synced_hash="u1")
    repo.update_sync_state("u2", context_key, "same-view", raw_synced_hash="u2")
    study.save_obsidian_binding(
        owner_user_id="u1",
        scope_type="single",
        scope_id="same-view",
        vault_id="v",
        transcript_directory="raw",
        note_directory="notes",
        expected_revision=None,
    )

    repo.save_binding("u1", "single", "same-view", "v", "B", "", binding["revision"])

    assert repo.get_sync_state("u1", context_key) is None
    assert repo.get_sync_state("u2", context_key)["raw_synced_hash"] == "u2"
    assert study.get_obsidian_binding(
        owner_user_id="u1",
        scope_type="single",
        scope_id="same-view",
        vault_id="v",
    ) is not None
