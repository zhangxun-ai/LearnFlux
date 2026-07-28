"""Hard uniqueness for learning collection identity.

Same owner + creator + title must reuse one collection, never create history
duplicates. All console output must be in English only.
"""

from __future__ import annotations

from video_transcript_api.collections.identity import normalize_collection_identity_field
from video_transcript_api.collections.repository import LearningCollectionRepository
from video_transcript_api.collections.service import LearningCollectionService
from video_transcript_api.cache.cache_manager import CacheManager


def test_normalize_collapses_whitespace_and_fullwidth():
    assert normalize_collection_identity_field("  王  达峰  ") == "王 达峰"
    assert normalize_collection_identity_field("认知　心智破局") == "认知 心智破局"


def test_repository_reuses_same_identity(tmp_path):
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))

    first = repo.create_collection(
        title="认知心智破局",
        creator_name="王达峰",
        collection_type="video_course",
        owner_user_id="user-a",
    )
    second = repo.create_collection(
        title="  认知心智破局  ",
        creator_name="王达峰",
        collection_type="video_course",
        owner_user_id="user-a",
    )

    assert first["id"] == second["id"]
    assert second.get("reused") is True
    assert first.get("created") is True

    rows = repo.list_collections(owner_user_id="user-a", limit=20)
    assert len(rows) == 1


def test_different_owners_can_share_same_title(tmp_path):
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    a = repo.create_collection(
        title="认知心智破局",
        creator_name="王达峰",
        collection_type="video_course",
        owner_user_id="user-a",
    )
    b = repo.create_collection(
        title="认知心智破局",
        creator_name="王达峰",
        collection_type="video_course",
        owner_user_id="user-b",
    )
    assert a["id"] != b["id"]


def test_service_reuses_by_default(tmp_path):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache)

    first = service.create_collection(
        title="CodeX从0到1实战课",
        creator_name="CodeX",
        collection_type="video_course",
        owner_user_id="legacy_user",
    )
    second = service.create_collection(
        title="CodeX从0到1实战课",
        creator_name="CodeX",
        collection_type="video_course",
        owner_user_id="legacy_user",
    )
    assert first["id"] == second["id"]
    assert second.get("reused") is True


def test_service_can_reject_duplicate_when_requested(tmp_path):
    cache = CacheManager(cache_dir=str(tmp_path / "cache"))
    repo = LearningCollectionRepository(db_path=str(tmp_path / "collections.db"))
    service = LearningCollectionService(repository=repo, cache_manager=cache)

    service.create_collection(
        title="CodeX从0到1实战课",
        creator_name="CodeX",
        collection_type="video_course",
        owner_user_id="legacy_user",
    )
    try:
        service.create_collection(
            title="CodeX从0到1实战课",
            creator_name="CodeX",
            collection_type="video_course",
            owner_user_id="legacy_user",
            reuse_if_exists=False,
        )
    except ValueError as exc:
        assert "同名专题已存在" in str(exc)
    else:
        raise AssertionError("expected ValueError for rejected duplicate")
