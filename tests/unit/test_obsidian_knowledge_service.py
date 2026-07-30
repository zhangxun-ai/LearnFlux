from pathlib import Path

import pytest

from video_transcript_api.obsidian.knowledge_models import KnowledgeItem


def test_preview_is_side_effect_free_then_apply_writes_mirrored_documents(tmp_path):
    from video_transcript_api.obsidian.knowledge_repository import ObsidianKnowledgeRepository
    from video_transcript_api.obsidian.knowledge_service import ObsidianKnowledgeService
    vault = tmp_path / "vault"; (vault / "raw" / "分类").mkdir(parents=True)
    repo = ObsidianKnowledgeRepository(tmp_path / "db.sqlite")
    binding = repo.save_binding("u", "single", "v", "vault", "分类", "", None)
    item = KnowledgeItem("u", "v", "标题", "原文", "解读", "online_url", "https://e")
    service = ObsidianKnowledgeService(vault_path=vault, repository=repo)
    preview = service.preview(items=[item], binding=binding)
    assert [d["state"] for d in preview["items"][0]["documents"]] == ["new", "new"]
    assert not (vault / "processed").exists()
    result = service.apply(items=[item], binding=binding, expected_binding_revision=1, preconditions=preview["preconditions"])
    assert {d["status"] for d in result["items"][0]["documents"]} == {"created"}
    assert (vault / "raw" / "分类" / "标题.md").exists()
    assert (vault / "processed" / "分类" / "标题.md").exists()


def _setup(tmp_path, *, writer=None):
    from video_transcript_api.obsidian.knowledge_repository import ObsidianKnowledgeRepository
    from video_transcript_api.obsidian.knowledge_service import ObsidianKnowledgeService

    vault = tmp_path / "vault"
    (vault / "raw" / "分类").mkdir(parents=True)
    repo = ObsidianKnowledgeRepository(tmp_path / "db.sqlite")
    binding = repo.save_binding("u", "single", "v", "vault", "分类", "", None)
    service = ObsidianKnowledgeService(
        vault_path=vault,
        repository=repo,
        now_provider=lambda: "2026-07-30T12:00:00+08:00",
        writer=writer,
    )
    item = KnowledgeItem("u", "v", "坏:标题", "原文", "解读", "online_url", "https://e")
    return service, repo, vault, binding, item


def test_safe_filename_repeat_sync_and_source_change_states(tmp_path):
    service, _repo, vault, binding, item = _setup(tmp_path)
    first = service.preview(items=[item], binding=binding)
    assert first["items"][0]["documents"][0]["relative_path"].endswith("坏-标题.md")
    service.apply(items=[item], binding=binding, expected_binding_revision=1, preconditions=first["preconditions"])

    repeated = service.preview(items=[item], binding=binding)
    assert {doc["state"] for doc in repeated["items"][0]["documents"]} == {"unchanged"}

    changed_item = KnowledgeItem(**{**item.__dict__, "analysis_content": "新解读"})
    changed = service.preview(items=[changed_item], binding=binding)
    states = {doc["document_type"]: doc["state"] for doc in changed["items"][0]["documents"]}
    assert states == {"raw": "unchanged", "analysis": "changed"}
    assert not str(vault) in changed["items"][0]["documents"][1]["diff"]


def test_unmanaged_raw_name_collision_keeps_raw_and_processed_filenames_mirrored(tmp_path):
    service, _repo, vault, binding, item = _setup(tmp_path)
    (vault / "raw" / "分类" / "坏-标题.md").write_text(
        "unmanaged content",
        encoding="utf-8",
    )

    preview = service.preview(items=[item], binding=binding)

    documents = {
        document["document_type"]: document
        for document in preview["items"][0]["documents"]
    }
    assert Path(documents["raw"]["relative_path"]).name == "坏-标题 (2).md"
    assert Path(documents["analysis"]["relative_path"]).name == "坏-标题 (2).md"


def test_external_edit_and_rename_are_detected_without_writing_during_preview(tmp_path):
    service, _repo, vault, binding, item = _setup(tmp_path)
    preview = service.preview(items=[item], binding=binding)
    applied = service.apply(items=[item], binding=binding, expected_binding_revision=1, preconditions=preview["preconditions"])
    raw_relative = applied["items"][0]["documents"][0]["relative_path"]
    raw_path = vault / raw_relative
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "\n用户修改\n", encoding="utf-8")

    dirty = service.preview(items=[item], binding=binding)
    assert dirty["items"][0]["documents"][0]["state"] == "externally_modified"

    renamed = raw_path.with_name("用户重命名.md")
    raw_path.rename(renamed)
    before = sorted(path.relative_to(vault) for path in vault.rglob("*"))
    relocated = service.preview(items=[item], binding=binding)
    after = sorted(path.relative_to(vault) for path in vault.rglob("*"))
    raw_doc = relocated["items"][0]["documents"][0]
    assert raw_doc["state"] == "relocated"
    assert raw_doc["relative_path"].endswith("用户重命名.md")
    assert before == after


def test_stale_preview_rejects_source_file_and_binding_changes(tmp_path):
    from video_transcript_api.obsidian.knowledge_service import KnowledgeStalePreview

    service, repo, vault, binding, item = _setup(tmp_path)
    preview = service.preview(items=[item], binding=binding)
    changed_item = KnowledgeItem(**{**item.__dict__, "raw_content": "后来变化"})
    with pytest.raises(KnowledgeStalePreview):
        service.apply(items=[changed_item], binding=binding, expected_binding_revision=1, preconditions=preview["preconditions"])

    raw_relative = preview["items"][0]["documents"][0]["relative_path"]
    (vault / raw_relative).parent.mkdir(parents=True, exist_ok=True)
    (vault / raw_relative).write_text("external", encoding="utf-8")
    with pytest.raises(KnowledgeStalePreview):
        service.apply(items=[item], binding=binding, expected_binding_revision=1, preconditions=preview["preconditions"])

    updated = repo.save_binding("u", "single", "v", "vault", "分类", "", binding["revision"])
    assert updated["revision"] == 2
    with pytest.raises(KnowledgeStalePreview):
        service.apply(items=[item], binding=binding, expected_binding_revision=1, preconditions=preview["preconditions"])


def test_analysis_failure_returns_truthful_partial_and_retry_is_idempotent(tmp_path):
    from video_transcript_api.obsidian.paths import atomic_write_text

    attempts = {"analysis": 0}

    def flaky_writer(vault_root, relative_path, content):
        if relative_path.startswith("processed/") and attempts["analysis"] == 0:
            attempts["analysis"] += 1
            raise OSError("simulated analysis failure")
        atomic_write_text(vault_root, relative_path, content)

    service, _repo, vault, binding, item = _setup(tmp_path, writer=flaky_writer)
    preview = service.preview(items=[item], binding=binding)
    partial = service.apply(
        items=[item],
        binding=binding,
        expected_binding_revision=1,
        preconditions=preview["preconditions"],
    )
    statuses = {doc["document_type"]: doc["status"] for doc in partial["items"][0]["documents"]}
    assert statuses == {"raw": "created", "analysis": "failed"}

    retry_preview = service.preview(items=[item], binding=binding)
    retry = service.apply(
        items=[item],
        binding=binding,
        expected_binding_revision=1,
        preconditions=retry_preview["preconditions"],
    )
    statuses = {doc["document_type"]: doc["status"] for doc in retry["items"][0]["documents"]}
    assert statuses == {"raw": "unchanged", "analysis": "created"}
    assert len(list(vault.rglob("*.md"))) == 2
