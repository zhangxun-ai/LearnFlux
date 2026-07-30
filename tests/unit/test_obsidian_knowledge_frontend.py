from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_single_result_has_independent_preview_confirm_assets():
    template = (ROOT / "src/web/templates/transcript.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "src/web/static/js/obsidian-knowledge.js").read_text(
        encoding="utf-8"
    )

    assert 'id="obsidian-knowledge-open"' in template
    button_at = template.index('id="obsidian-knowledge-open"')
    nearby = template[max(0, button_at - 500):button_at + 500]
    assert "study_available" not in nearby
    assert "/static/css/obsidian-knowledge.css" in template
    assert "/static/js/obsidian-knowledge.js" in template
    for element_id in (
        "obsidian-knowledge-category",
        "obsidian-knowledge-recommendation",
        "obsidian-knowledge-source-access",
        "obsidian-knowledge-preview-list",
        "obsidian-knowledge-preview",
        "obsidian-knowledge-apply",
    ):
        assert f'id="{element_id}"' in template

    assert "/recommend-category" in script
    assert "/binding" in script
    assert "/preview" in script
    assert "/apply" in script
    assert "preconditions" in script
    assert "expected_binding_revision" in script
    assert "stale_preview" in script
    assert "refreshPreviewAfterStale" in script
    assert "externally_modified" in script


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
        'id="obsidian-collection-sources"',
        'id="obsidian-collection-select-all"',
        'id="obsidian-collection-clear-all"',
        "预览所选",
        "增量同步全部",
        "强制重新同步全部",
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
    assert "const hasPreconditions = (data.preconditions || []).length > 0" in script
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
    assert ".obsidian-collection" in css


def test_opening_dialogs_does_not_call_apply():
    single = (ROOT / "src/web/static/js/obsidian-knowledge.js").read_text(
        encoding="utf-8"
    )
    collections = (ROOT / "src/web/static/js/collections.js").read_text(
        encoding="utf-8"
    )
    single_open = single[
        single.index("async function openKnowledgeDialog"):
        single.index("async function generatePreview")
    ]
    collection_open = collections[
        collections.index("async function openCollectionKnowledgeDialog"):
        collections.index("function clearCollectionKnowledgePreview")
    ]
    assert "/apply" not in single_open
    assert "/apply" not in collection_open
