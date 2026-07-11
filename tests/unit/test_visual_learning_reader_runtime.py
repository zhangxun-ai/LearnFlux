import json
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RENDERER = PROJECT_ROOT / "src/web/static/js/visual-learning.js"
TRANSCRIPT_READER = PROJECT_ROOT / "src/web/static/js/transcript-visual-reader.js"


def _run_renderer(expression: str):
    source = RENDERER.read_text(encoding="utf-8")
    script = (
        "global.window = {};\n"
        f"{source}\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _run_transcript_reader(expression: str):
    renderer = RENDERER.read_text(encoding="utf-8")
    transcript_reader = TRANSCRIPT_READER.read_text(encoding="utf-8")
    script = (
        "global.window = {};\n"
        f"{renderer}\n"
        f"{transcript_reader}\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_reader_state_keeps_section_when_mode_changes_and_rejects_old_owner():
    result = _run_renderer(
        "(() => {"
        "const reader = window.VisualLearning.createReaderState('collection-1', 'text');"
        "reader.setSection('section-02');"
        "reader.setMode('visual');"
        "const oldGeneration = reader.generation();"
        "reader.resetOwner('collection-2');"
        "return {"
        "snapshot: reader.snapshot(),"
        "oldAccepted: reader.accepts('collection-1', oldGeneration),"
        "currentAccepted: reader.accepts('collection-2', reader.generation())"
        "};"
        "})()"
    )

    assert result == {
        "snapshot": {
            "ownerId": "collection-2",
            "mode": "visual",
            "sectionId": "",
        },
        "oldAccepted": False,
        "currentAccepted": True,
    }


def test_reader_markdown_normalization_removes_only_document_metadata():
    result = _run_renderer(
        "window.VisualLearning.normalizeMarkdownForReader("
        "'---\\ntitle: 示例\\n---\\n## 第一节\\n正文\\n\\n---\\n\\n继续'"
        ")"
    )

    assert result == "## 第一节\n正文\n\n---\n\n继续"


def test_stale_full_note_hides_review_content():
    result = _run_renderer(
        "({"
        "fresh: window.VisualLearning.reviewBlocksForReader({"
        "fullNote: {pages: [{blocks: [{type: 'review_questions'}]}]},"
        "fullNoteStale: false"
        "}).length,"
        "stale: window.VisualLearning.reviewBlocksForReader({"
        "fullNote: {pages: [{blocks: [{type: 'review_questions'}]}]},"
        "fullNoteStale: true"
        "}).length"
        "})"
    )

    assert result == {"fresh": 1, "stale": 0}


def test_collection_reader_generation_rejects_response_after_owner_switch():
    result = _run_renderer(
        "(() => {"
        "const collectionReader = window.VisualLearning.createReaderState('collection-a', 'visual');"
        "const request = {owner: 'collection-a', generation: collectionReader.generation()};"
        "collectionReader.resetOwner('collection-b');"
        "return {"
        "late: collectionReader.accepts(request.owner, request.generation),"
        "current: collectionReader.accepts('collection-b', collectionReader.generation())"
        "};"
        "})()"
    )

    assert result == {"late": False, "current": True}


def test_transcript_one_click_requests_only_overview_and_explicit_detail_requests_full_note():
    result = _run_transcript_reader(
        "({"
        "oneClick: window.TranscriptVisualReader.requestedDocumentTypes('one-click'),"
        "detail: window.TranscriptVisualReader.requestedDocumentTypes('full-note')"
        "})"
    )

    assert result == {"oneClick": ["overview"], "detail": ["full_note"]}


def test_transcript_reader_generation_rejects_response_after_close():
    result = _run_transcript_reader(
        "(() => {"
        "const reader = window.VisualLearning.createReaderState('view-1', 'visual');"
        "const generation = reader.generation();"
        "reader.invalidate();"
        "return reader.accepts('view-1', generation);"
        "})()"
    )

    assert result is False
