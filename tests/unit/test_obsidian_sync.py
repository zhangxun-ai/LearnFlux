import pytest


def _hash(body: str) -> str:
    from video_transcript_api.obsidian.markdown import note_body_hash

    return note_body_hash(body)


@pytest.mark.parametrize(
    ("app_body", "obsidian_exists", "obsidian_body", "baseline", "expected"),
    [
        ("same", True, "same", _hash("same"), "clean"),
        ("app changed", True, "base", _hash("base"), "app_dirty"),
        ("base", True, "obsidian changed", _hash("base"), "obsidian_dirty"),
        ("same change", True, "same change", _hash("base"), "converged"),
        ("app changed", True, "obsidian changed", _hash("base"), "conflict"),
        ("draft", False, None, None, "app_dirty"),
        ("", False, None, None, "skipped_empty"),
        ("", True, "from obsidian", None, "obsidian_dirty"),
        ("draft", True, "", None, "app_dirty"),
        ("same", True, "same", None, "converged"),
        ("app", True, "obsidian", None, "conflict"),
        ("base", False, None, _hash("base"), "external_deleted"),
        ("app changed", False, None, _hash("base"), "external_deleted"),
    ],
)
def test_reconcile_note_state(
    app_body,
    obsidian_exists,
    obsidian_body,
    baseline,
    expected,
):
    from video_transcript_api.obsidian.service import reconcile_note_state

    result = reconcile_note_state(
        app_body=app_body,
        obsidian_exists=obsidian_exists,
        obsidian_body=obsidian_body,
        baseline_hash=baseline,
    )

    assert result.state == expected
    assert result.app_hash == _hash(app_body)
    assert result.obsidian_hash == (
        _hash(obsidian_body or "") if obsidian_exists else "__absent__"
    )


def test_existing_empty_file_is_distinct_from_absence():
    from video_transcript_api.obsidian.service import reconcile_note_state

    existing = reconcile_note_state(
        app_body="",
        obsidian_exists=True,
        obsidian_body="",
        baseline_hash=None,
    )
    absent = reconcile_note_state(
        app_body="",
        obsidian_exists=False,
        obsidian_body=None,
        baseline_hash=None,
    )

    assert existing.state == "converged"
    assert existing.obsidian_hash == _hash("")
    assert absent.state == "skipped_empty"
    assert absent.obsidian_hash == "__absent__"


def test_example_config_has_disabled_empty_obsidian_placeholders():
    import commentjson
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    with (project_root / "config" / "config.example.jsonc").open(encoding="utf-8") as handle:
        config = commentjson.load(handle)

    assert config["obsidian"] == {
        "enabled": False,
        "vault_id": "",
        "vault_path": "",
        "knowledge_raw_root": "raw",
        "knowledge_processed_root": "processed",
        "review_root": "复盘",
    }


def _context(**overrides):
    from video_transcript_api.obsidian.service import StudySyncContext

    values = {
        "owner_user_id": "user-1",
        "view_token": "view-1",
        "title": "第01课：核心概念",
        "course": "高效学习",
        "transcript_lines": [
            {"start_seconds": 0, "seekable": True, "text": "第一段"},
            {"start_seconds": 12, "seekable": True, "text": "第二段"},
        ],
        "collection_id": "course-1",
        "source_id": "lesson-1",
    }
    values.update(overrides)
    return StudySyncContext(**values)


def _service(tmp_path):
    from video_transcript_api.obsidian.service import ObsidianSyncService
    from video_transcript_api.study.repository import StudyRepository

    vault = tmp_path / "vault"
    (vault / "raw" / "高效学习").mkdir(parents=True)
    (vault / "高效学习" / "笔记").mkdir(parents=True)
    service = ObsidianSyncService(
        vault_id="vault-1",
        vault_path=vault,
        repository=StudyRepository(str(tmp_path / "study.db")),
        now_provider=lambda: "2026-07-17T12:00:00+08:00",
    )
    return service, vault


def _bind(service, context):
    return service.save_binding(
        context,
        transcript_directory="raw/高效学习",
        note_directory="高效学习/笔记",
        expected_revision=None,
    )


def _save_body(service, context, body):
    loaded = service.load_note(context)
    return service.save_note(
        context,
        body=body,
        expected_revision=loaded["document"]["revision"],
    )


def test_collection_binding_is_inherited_and_sync_is_idempotent(tmp_path):
    service, vault = _service(tmp_path)
    first = _context()
    second = _context(view_token="view-2", source_id="lesson-2", title="第02课")
    binding = _bind(service, first)

    assert service.get_binding(second)["id"] == binding["id"]
    _save_body(service, first, "我的持续笔记")

    created = service.sync(first)
    repeated = service.sync(first)

    assert created["overall"] == "success"
    assert created["transcript"]["status"] == "created"
    assert created["note"]["status"] == "created"
    assert repeated["transcript"]["status"] == "unchanged"
    assert repeated["note"]["status"] == "unchanged"
    assert len(list(vault.rglob("*.md"))) == 2


def test_sync_updates_legacy_line_transcript_without_changing_note(tmp_path):
    service, vault = _service(tmp_path)
    context = _context()
    _bind(service, context)
    original_note = "这篇笔记必须保持不变。"
    _save_body(service, context, original_note)
    first = service.sync(context)
    transcript_path = vault / first["transcript"]["relative_path"]
    note_path = vault / first["note"]["relative_path"]
    rendered = transcript_path.read_text(encoding="utf-8")
    body_start = rendered.index("# ")
    transcript_path.write_text(
        rendered[:body_start]
        + "# 第01课：核心概念\n\n[00:00] 第一段\n[00:12] 第二段\n",
        encoding="utf-8",
    )
    note_before = note_path.read_text(encoding="utf-8")

    updated = service.sync(context)
    repeated = service.sync(context)
    updated_transcript = transcript_path.read_text(encoding="utf-8")

    assert updated["transcript"]["status"] == "updated"
    assert "## 文字稿" in updated_transcript
    assert "**00:00** 第一段，第二段。" in updated_transcript
    assert repeated["transcript"]["status"] == "unchanged"
    assert note_path.read_text(encoding="utf-8") == note_before
    assert service.load_note(context)["document"]["body"] == original_note


def test_sync_stops_before_writing_when_transcript_is_not_ready(tmp_path):
    from video_transcript_api.obsidian.service import ObsidianSyncError

    service, vault = _service(tmp_path)
    context = _context(transcript_lines=[])
    _bind(service, context)
    _save_body(service, context, "先保存在学习页里的笔记")

    with pytest.raises(ObsidianSyncError, match="transcript_not_ready"):
        service.sync(context)

    assert list(vault.rglob("*.md")) == []
    assert service.load_note(context)["document"]["body"] == "先保存在学习页里的笔记"


def test_collection_retry_reuses_note_document_paths_and_baseline(tmp_path):
    service, vault = _service(tmp_path)
    original = _context(view_token="view-old")
    retried = _context(view_token="view-new")
    _bind(service, original)
    saved = _save_body(service, original, "same lesson note")
    first_sync = service.sync(original)

    loaded = service.load_note(retried)
    second_sync = service.sync(retried)

    assert loaded["document"]["id"] == saved["id"]
    assert loaded["document"]["current_view_token"] == "view-new"
    assert second_sync["note"]["relative_path"] == first_sync["note"]["relative_path"]
    assert second_sync["transcript"]["relative_path"] == first_sync["transcript"]["relative_path"]
    note_content = (vault / second_sync["note"]["relative_path"]).read_text(encoding="utf-8")
    assert "vta_view_token: view-new" in note_content
    assert len(list(vault.rglob("*.md"))) == 2


def test_single_and_same_view_in_different_collections_are_isolated(tmp_path):
    service, vault = _service(tmp_path)
    single_dir = vault / "single"
    (single_dir / "raw").mkdir(parents=True)
    (single_dir / "笔记").mkdir()
    single = _context(collection_id="", source_id="", course="", title="单篇")
    service.save_binding(
        single,
        transcript_directory="single/raw",
        note_directory="single/笔记",
        expected_revision=None,
    )
    other_course = _context(collection_id="course-2", source_id="lesson-9")
    (vault / "raw" / "课程2").mkdir()
    (vault / "课程2" / "笔记").mkdir(parents=True)
    service.save_binding(
        other_course,
        transcript_directory="raw/课程2",
        note_directory="课程2/笔记",
        expected_revision=None,
    )

    single_doc = service.load_note(single)["document"]
    first_course_doc = service.load_note(_context())["document"]
    other_course_doc = service.load_note(other_course)["document"]

    assert len({single_doc["id"], first_course_doc["id"], other_course_doc["id"]}) == 3


def test_obsidian_only_edit_and_external_rename_are_imported_on_load(tmp_path):
    from video_transcript_api.obsidian.markdown import render_note_markdown

    service, vault = _service(tmp_path)
    context = _context()
    _bind(service, context)
    _save_body(service, context, "baseline")
    synced = service.sync(context)
    old_path = vault / synced["note"]["relative_path"]
    renamed = old_path.with_name("我在 Obsidian 重命名了.md")
    old_content = old_path.read_text(encoding="utf-8")
    old_path.rename(renamed)
    renamed.write_text(
        render_note_markdown(
            {
                "view_token": context.view_token,
                "collection_id": context.collection_id,
                "source_id": context.source_id,
                "course": context.course,
                "lesson": context.title,
                "synced_at": "2026-07-17T13:00:00+08:00",
            },
            "Obsidian 里的最新正文",
            existing_content=old_content,
        ),
        encoding="utf-8",
    )

    loaded = service.load_note(context)

    assert loaded["document"]["body"] == "Obsidian 里的最新正文"
    assert loaded["state"] == "clean"
    assert loaded["reconciled_from"] == "obsidian"
    state = service.repository.get_obsidian_source_sync(
        owner_user_id=context.owner_user_id,
        view_token=context.view_token,
        collection_id=context.collection_id,
        source_id=context.source_id,
    )
    assert state["note_relative_path"].endswith("我在 Obsidian 重命名了.md")


def test_dual_edit_conflict_does_not_overwrite_and_stale_resolution_is_rejected(tmp_path):
    from video_transcript_api.obsidian.markdown import render_note_markdown
    from video_transcript_api.obsidian.service import ObsidianConflict

    service, vault = _service(tmp_path)
    context = _context()
    _bind(service, context)
    _save_body(service, context, "baseline")
    synced = service.sync(context)
    path = vault / synced["note"]["relative_path"]
    existing = path.read_text(encoding="utf-8")
    _save_body(service, context, "app edit")
    path.write_text(
        render_note_markdown(
            service.markdown_metadata(context),
            "obsidian edit",
            existing_content=existing,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ObsidianConflict) as conflict:
        service.sync(context)
    preview = conflict.value.payload
    assert preview["state"] == "conflict"
    assert "obsidian edit" in path.read_text(encoding="utf-8")

    _save_body(service, context, "later app edit")
    with pytest.raises(ObsidianConflict) as stale:
        service.resolve_conflict(context, choice="app", **preview["preconditions"])
    assert stale.value.payload["code"] == "stale_conflict"

    latest = service.inspect_conflict(context)
    resolved = service.resolve_conflict(
        context,
        choice="app",
        **latest["preconditions"],
    )
    assert resolved["document"]["body"] == "later app edit"
    assert "later app edit" in path.read_text(encoding="utf-8")


def test_external_deletion_can_recreate_or_be_explicitly_accepted(tmp_path):
    from video_transcript_api.obsidian.service import ObsidianConflict

    service, vault = _service(tmp_path)
    context = _context()
    _bind(service, context)
    _save_body(service, context, "keep me")
    synced = service.sync(context)
    path = vault / synced["note"]["relative_path"]
    path.unlink()

    with pytest.raises(ObsidianConflict) as deleted:
        service.sync(context)
    assert deleted.value.payload["state"] == "external_deleted"
    recreated = service.resolve_conflict(
        context,
        choice="recreate_from_app",
        **deleted.value.payload["preconditions"],
    )
    recreated_path = vault / recreated["note_relative_path"]
    assert recreated_path.is_file()
    assert "keep me" in recreated_path.read_text(encoding="utf-8")

    recreated_path.unlink()
    preview = service.inspect_conflict(context)
    accepted = service.resolve_conflict(
        context,
        choice="accept_external_deletion",
        **preview["preconditions"],
    )
    assert accepted["document"]["body"] == ""
    assert accepted["note_relative_path"] is None
    assert list((vault / "高效学习" / "笔记").glob("*.md")) == []


def test_empty_draft_is_skipped_but_clearing_existing_note_updates_file(tmp_path):
    from video_transcript_api.obsidian.markdown import extract_note_body

    service, vault = _service(tmp_path)
    context = _context()
    _bind(service, context)

    empty = service.sync(context)
    assert empty["note"]["status"] == "skipped_empty"
    assert list((vault / "高效学习" / "笔记").glob("*.md")) == []

    _save_body(service, context, "temporary")
    created = service.sync(context)
    _save_body(service, context, "")
    cleared = service.sync(context)
    note_path = vault / created["note"]["relative_path"]

    assert cleared["note"]["status"] == "updated"
    assert extract_note_body(note_path.read_text(encoding="utf-8")) == ""


def test_partial_write_persists_success_and_retry_converges(tmp_path, monkeypatch):
    import video_transcript_api.obsidian.service as service_module

    service, vault = _service(tmp_path)
    context = _context()
    _bind(service, context)
    _save_body(service, context, "note")
    real_write = service_module.atomic_write_text

    def fail_note(vault_root, relative_path, content):
        if "/笔记/" in f"/{relative_path}":
            raise OSError("simulated note failure")
        real_write(vault_root, relative_path, content)

    monkeypatch.setattr(service_module, "atomic_write_text", fail_note)
    partial = service.sync(context)

    assert partial["overall"] == "partial"
    assert partial["transcript"]["status"] == "created"
    assert partial["note"]["status"] == "failed"

    monkeypatch.setattr(service_module, "atomic_write_text", real_write)
    retried = service.sync(context)
    assert retried["transcript"]["status"] == "unchanged"
    assert retried["note"]["status"] == "created"
    assert len(list(vault.rglob("*.md"))) == 2
