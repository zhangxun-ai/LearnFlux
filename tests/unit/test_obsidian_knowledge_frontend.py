from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_single_result_syncs_without_a_preview_step_and_closes_on_success():
    template = (ROOT / "src/web/templates/transcript.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "src/web/static/js/obsidian-knowledge.js").read_text(
        encoding="utf-8"
    )
    context = (ROOT / "src/video_transcript_api/api/context.py").read_text(
        encoding="utf-8"
    )

    assert 'id="obsidian-knowledge-open"' in template
    button_at = template.index('id="obsidian-knowledge-open"')
    nearby = template[max(0, button_at - 500):button_at + 500]
    assert "study_available" not in nearby
    assert "/static/css/obsidian-knowledge.css" in template
    assert "/static/js/obsidian-knowledge.js" in template
    assert 'static_dir / "css" / "obsidian-knowledge.css"' in context
    assert 'static_dir / "js" / "obsidian-knowledge.js"' in context
    for element_id in (
        "obsidian-knowledge-notice",
        "obsidian-knowledge-notice-title",
        "obsidian-knowledge-notice-detail",
    ):
        assert f'id="{element_id}"' in template
    assert 'popover="manual"' in template
    for element_id in (
        "obsidian-knowledge-category",
        "obsidian-knowledge-recommendation",
        "obsidian-knowledge-apply",
    ):
        assert f'id="{element_id}"' in template
    assert 'id="obsidian-knowledge-source-access"' not in template
    assert 'id="obsidian-knowledge-preview-list"' not in template
    assert 'id="obsidian-knowledge-preview"' not in template
    assert "生成同步预览" not in template
    assert "同步到 Obsidian" in template

    assert "/recommend-category" in script
    assert "/binding" in script
    assert "/preview" in script
    assert "/apply" in script
    assert "async function syncKnowledgeToObsidian" in script
    assert "function showSyncNotice" in script
    assert "showSyncNotice('success'" in script
    assert "showSyncNotice('error'" in script
    assert "dialog.close()" in script
    assert "data.counts && data.counts.failed" in script
    assert "preconditions" in script
    assert "expected_binding_revision" in script
    assert "stale_preview" in script


def test_collection_has_selection_incremental_force_and_result_ui():
    html = (ROOT / "src/web/static/collections.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "src/web/static/js/collections.js").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "src/web/static/css/collections.css").read_text(
        encoding="utf-8"
    )

    for value in (
        'id="obsidian-collection-open"',
        'id="obsidian-collection-dialog"',
        'id="obsidian-collection-category"',
        'id="obsidian-collection-directory"',
        'id="obsidian-collection-directory-browse"',
        'id="obsidian-collection-directory-panel"',
        'id="obsidian-collection-directory-list"',
        'id="obsidian-collection-directory-status"',
        'id="obsidian-collection-sources"',
        'id="obsidian-collection-select-all"',
        'id="obsidian-collection-clear-all"',
        "确认同步",
        "强制重新同步全部",
        "同步时自动创建",
        "<details",
    ):
        assert value in html
    assert "openCollectionKnowledgeDialog" in script
    assert "source_ids: selectedSourceIds" in script
    assert "sync_all: true" in script
    assert "force: false" in script
    assert "force: true" in script
    assert "clearCollectionKnowledgePreview" in script
    assert "preconditions" in script
    assert "loadCollectionVaultDirectories" in script
    assert "chooseCollectionDirectoryValue" in script
    assert "setCollectionDirectoryValue" in script
    assert "openCollectionDirectoryPanel" in script
    assert "closeCollectionDirectoryPanel" in script
    assert "updateCollectionDirectoryMeta" in script
    assert "refreshCollectionKnowledgeApplyState" in script
    assert "collectionPreviewHasExternalModifications" in script
    assert "One-click path: auto-preview when user has not previewed yet." in script
    assert "/api/obsidian/directories" in script
    assert "createCollectionDirectoryInVault" not in script
    assert "displaySourceTitle(source)" in script
    assert "els.obsidianCollectionDialog.close()" in script
    force_preview = script[
        script.index("async function previewForcedCollectionKnowledge"):
        script.index("async function applyCollectionKnowledgePreview")
    ]
    assert "/apply" not in force_preview
    for status in (
        "unavailable",
        "unchanged",
        "created",
        "updated",
        "failed",
    ):
        assert status in script
    assert ".obsidian-dir-combobox" in css
    assert ".obsidian-dir-panel" in css
    assert ".obsidian-collection-setup" in css


def test_opening_dialogs_does_not_call_apply():
    single = (ROOT / "src/web/static/js/obsidian-knowledge.js").read_text(
        encoding="utf-8"
    )
    collections = (ROOT / "src/web/static/js/collections.js").read_text(
        encoding="utf-8"
    )
    single_open = single[
        single.index("async function openKnowledgeDialog"):
        single.index("async function syncKnowledgeToObsidian")
    ]
    collection_open = collections[
        collections.index("async function openCollectionKnowledgeDialog"):
        collections.index("function clearCollectionKnowledgePreview")
    ]
    assert "/apply" not in single_open
    assert "/apply" not in collection_open
