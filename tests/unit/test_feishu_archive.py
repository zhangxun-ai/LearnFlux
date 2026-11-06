"""Content integrity, safe rendering, durable retries, and duplicate prevention."""

import json
from pathlib import Path
import re

import pytest

from video_transcript_api.exports.feishu import (
    ArchiveWorker, FeishuRejected, LocalResults, build_document, normalized_text, summary_xml,
)
from video_transcript_api.exports.delivery import diagram_delivery_state


TASK = {"task_id": "task-1", "view_token": "private-view", "status": "success",
        "title": "AI 热词 本视频22分钟", "author": "Author", "platform": "douyin",
        "url": "https://example.com/video", "created_at": "2026-10-18T11:13:00"}


class Source:
    def tasks(self):
        yield TASK

    def document(self, task):
        return build_document(task, "## 结论\n\n**重要观点**。", "第一句。\n\n最后一句。", calibrated=True)

    def read_diagram(self, job_id):
        return b"private png"


class CLI:
    def __init__(self):
        self.calls = 0
        self.xml = ""
        self.timeout = False
        self.fetch_failure = False
        self.revision = 1
        self.updates = 0
        self.update_timeout = False
        self.image_calls = []
        self.image_timeout = False
        self.moves = []

    def create(self, parent, xml):
        self.calls += 1
        self.xml = xml
        if self.timeout:
            raise RuntimeError("Timed out after remote creation")
        return {"document": {"document_id": "document-1", "url": "https://my.feishu.cn/docx/document-1",
                             "revision_id": self.revision}}

    def fetch(self, doc):
        if self.fetch_failure:
            raise RuntimeError("Temporary read failure")
        return self.xml

    def fetch_document(self, doc, *, with_ids=False):
        content = self.fetch(doc)
        if with_ids:
            content = content.replace("<h1>AI 解读</h1>", '<h1 id="analysis">AI 解读</h1>', 1)
            content = content.replace('<img src="media-', f'<img id="block-{self.revision}" src="media-')
        return {"content": content, "revision_id": self.revision}

    def update(self, doc, xml, revision_id):
        assert revision_id == self.revision
        self.xml = xml
        self.revision += 1
        self.updates += 1
        if self.update_timeout:
            raise RuntimeError("Timed out after remote update")
        return {"document": {"revision_id": self.revision}}

    def insert_diagram(self, doc, job_id, image, *, heading_id, revision_id):
        assert doc == "document-1"
        assert image == b"private png"
        assert heading_id == "analysis" and revision_id == self.revision
        self.image_calls.append(job_id)
        tag = f'<img src="media-{job_id}" caption="AI 图解 · {job_id}\n"/>'
        self.xml = self.xml.replace("<h1>AI 解读</h1>", "<h1>AI 解读</h1>" + tag, 1)
        self.revision += 1
        if self.image_timeout:
            self.fetch_failure = True
            raise RuntimeError("Timed out after remote image insertion")

    def move_diagram(self, doc, image_id, *, heading_id, revision_id):
        assert doc == "document-1"
        assert heading_id == "analysis" and revision_id == self.revision
        assert image_id == f"block-{revision_id}"
        self.moves.append(image_id)
        tag = re.findall(r"<img [^>]+/>", self.xml)[-1]
        self.xml = self.xml.replace(tag, "").replace("<h1>AI 解读</h1>", "<h1>AI 解读</h1>" + tag, 1)
        self.revision += 1

    def call(self, *args, **kwargs):
        return {"nodes": [{"title": Source().document(TASK)[0], "obj_token": "document-1",
                            "obj_type": "docx", "node_token": "node-1"}], "has_more": False}


def worker(tmp_path, cli=None, source=None):
    return ArchiveWorker({"state_db": str(tmp_path / "archive.db"), "parent_node_token": "parent",
                          "space_id": "space"}, source=source or Source(), cli=cli or CLI())


def diagram_state(job, job_id, **kwargs):
    return diagram_delivery_state(job.config, TASK["view_token"], job_id, lambda _: None, **kwargs)


def test_diagrams_precede_text_and_survive_later_text_update(tmp_path):
    cli = CLI()
    job = worker(tmp_path, cli=cli)
    first, second = "a" * 32, "b" * 32
    assert diagram_state(job, first, enqueue=True)["state"] == "waiting"
    job.run_once()
    assert diagram_state(job, first)["state"] == "ready"
    assert diagram_state(job, first, enqueue=True)["state"] == "queued"
    assert diagram_state(job, first, enqueue=True)["state"] == "queued"
    assert diagram_state(job, second, enqueue=True)["state"] == "queued"
    assert job.run_diagram_exports() == 2
    assert cli.xml.index("<h1>AI 解读</h1>") < cli.xml.index(f"media-{first}") < cli.xml.index("<h2>结论")
    assert not cli.moves
    assert diagram_state(job, first, enqueue=True)["state"] == "done"
    initial_link = diagram_state(job, first)["document_url"]
    assert initial_link.endswith("#block-2")
    assert job.run_diagram_exports() == 0
    assert cli.image_calls == [first, second]

    class EditedSource(Source):
        def tasks(self):
            yield {**TASK, "updated_at": "2026-10-19T11:13:00"}

        def document(self, task):
            return build_document(task, "Updated analysis.", "Updated full body.", calibrated=True)

    job.source = EditedSource()
    assert job.run_once()["counts"] == {"done": 1}
    assert cli.calls == cli.updates == 1
    assert "Updated full body." in cli.xml
    assert all(f'src="media-{key}"' in cli.xml for key in (first, second))
    assert cli.xml.index("<h1>AI 解读</h1>") < cli.xml.index(f"media-{first}") < cli.xml.index("Updated analysis.")
    assert diagram_state(job, first)["document_url"].endswith(f"#block-{cli.revision}")
    assert diagram_state(job, first)["document_url"] != initial_link
    assert cli.image_calls == [first, second]


def test_completed_diagram_reposition_moves_existing_block_only(tmp_path):
    from video_transcript_api.exports.feishu import remote_digest

    cli = CLI()
    job = worker(tmp_path, cli=cli)
    key = "a" * 32
    job.run_once()
    assert diagram_state(job, key, enqueue=True, reposition=True)["state"] == "ready"
    assert job.run_diagram_exports() == 0
    tag = f'<img src="media-{key}" caption="AI 图解 · {key}\n"/>'
    cli.xml += tag
    cli.revision += 1
    job.save("parent:private-view", remote_digest=remote_digest(cli.xml))
    job.db.execute("INSERT INTO diagram_exports (source_key, job_id, document_id, status) VALUES (?, ?, ?, 'done')",
                   ("parent:private-view", key, "document-1"))
    job.db.commit()
    assert diagram_state(job, key, enqueue=True, reposition=True)["state"] == "writing"
    assert job.run_diagram_exports() == 1
    assert cli.moves == ["block-2"]
    assert cli.image_calls == []
    assert cli.xml.count(tag) == 1
    assert "<h1>AI 解读</h1>" + tag in cli.xml
    assert job._row("parent:private-view")["remote_digest"] == remote_digest(cli.xml)


def test_uncertain_image_insert_only_rechecks_after_restart(tmp_path):
    cli = CLI()
    job = worker(tmp_path, cli=cli)
    key = "a" * 32
    job.run_once()
    diagram_state(job, key, enqueue=True)
    cli.image_timeout = True
    assert job.run_diagram_exports() == 0
    assert diagram_state(job, key)["state"] == "uncertain"
    job.db.close()

    cli.fetch_failure = False
    resumed = worker(tmp_path, cli=cli)
    assert diagram_state(resumed, key, enqueue=True)["state"] == "writing"
    assert resumed.run_diagram_exports() == 1
    assert diagram_state(resumed, key)["state"] == "done"
    assert cli.image_calls == [key]


def test_image_append_does_not_adopt_manual_document_edits(tmp_path):
    cli = CLI()
    job = worker(tmp_path, cli=cli)
    job.run_once()
    original = job._row("parent:private-view")["remote_digest"]
    cli.xml += "<p>Handwritten note</p>"
    diagram_state(job, "a" * 32, enqueue=True)
    assert job.run_diagram_exports() == 1
    assert job._row("parent:private-view")["remote_digest"] == original
    assert "Handwritten note" in cli.xml


def test_complete_content_and_sources_are_preserved_without_private_links():
    title, xml = Source().document(TASK)
    assert title == "2026-10-18 · AI 热词"
    for content in ["重要观点", "第一句。", "最后一句。", TASK["url"], "Author"]:
        assert content in xml
    assert TASK["view_token"] not in xml
    assert "localhost" not in xml


def test_transcript_xml_cannot_inject_uploads():
    _, xml = build_document(TASK, "总结", '<source path="@./secret"/> & <img href="http://127.0.0.1"/>', calibrated=False)
    assert "<source" not in xml and "<img" not in xml
    assert "原始转录" in xml
    assert '&lt;source' in xml


def test_summary_cannot_inject_cli_extensions_or_fetch_images():
    result = summary_xml('## 要点\n\n![图片](http://127.0.0.1/secret)\n\n<source path="@./secret"/>\n\n[链接](javascript:alert)')
    assert "<img" not in result and "<source" not in result and "javascript:" not in result
    assert "图片" in result


def test_incomplete_content_is_not_exported():
    with pytest.raises(ValueError, match="incomplete"):
        build_document(TASK, "", "逐字稿", calibrated=True)


def test_deduplication_survives_process_restart_and_cached_resubmission(tmp_path):
    cli = CLI()
    first = worker(tmp_path, cli)
    assert first.run_once()["counts"] == {"done": 1}
    first.db.close()
    second = worker(tmp_path, cli)
    assert second.run_once()["exported_this_run"] == 0
    assert cli.calls == 1


def test_readback_failure_retries_the_existing_document(tmp_path):
    cli = CLI()
    cli.fetch_failure = True
    job = worker(tmp_path, cli)
    assert job.run_once()["counts"] == {"verifying": 1}
    cli.fetch_failure = False
    job.db.execute("UPDATE exports SET next_retry=0")
    job.db.commit()
    assert job.run_once()["counts"] == {"done": 1}
    assert cli.calls == 1


def test_uncertain_creation_reconciles_instead_of_creating_again(tmp_path):
    cli = CLI()
    cli.timeout = True
    job = worker(tmp_path, cli)
    assert job.run_once()["counts"] == {"uncertain": 1}
    job.db.execute("UPDATE exports SET next_retry=0")
    job.db.commit()
    assert job.run_once()["counts"] == {"done": 1}
    assert cli.calls == 1


def test_truncation_is_never_marked_success(tmp_path):
    cli = CLI()
    cli.fetch = lambda doc: "<title>Only a title</title>"
    job = worker(tmp_path, cli)
    assert job.run_once()["counts"] == {"verifying": 1}
    assert "differs" in job.db.execute("SELECT last_error FROM exports").fetchone()[0]


def test_confirmed_authorization_failure_can_retry_creation(tmp_path):
    cli = CLI()
    original_create = cli.create
    cli.create = lambda *args: (_ for _ in ()).throw(FeishuRejected("Authorization rejected"))
    job = worker(tmp_path, cli)
    assert job.run_once()["counts"] == {"pending": 1}
    cli.create = original_create
    job.db.execute("UPDATE exports SET next_retry=0")
    job.db.commit()
    assert job.run_once()["counts"] == {"done": 1}
    assert cli.calls == 1


def test_discovery_waits_for_completion_and_does_not_backfill_all_history():
    source = LocalResults({"api_base": "http://localhost:8000", "since": "2026-10-18T00:00:00Z"})
    source.read = lambda _: json.dumps({"data": {"items": [TASK, {**TASK, "task_id": "running", "status": "processing"},
        {**TASK, "task_id": "old", "created_at": "2026-10-01T00:00:00"}], "has_more": True}})
    assert [task["task_id"] for task in source.tasks()] == ["task-1"]


def test_api_source_refuses_remote_hosts():
    with pytest.raises(ValueError, match="loopback"):
        LocalResults({"api_base": "https://other.example"})


def test_comparison_ignores_block_ids_but_detects_missing_text():
    assert normalized_text('<p id="1">完整 文本</p>') == normalized_text('<p>完整\n文本</p>')
    assert normalized_text('<p>文本</p>') != normalized_text('<p>完整文本</p>')


def test_comparison_preserves_link_targets_across_native_conversion():
    original = '<p>参考 [原文](https://example.com/lesson)</p>'
    native = '<p>参考 <a href="https://example.com/lesson">原文</a></p>'
    assert normalized_text(original) == normalized_text(native)
    wrong = native.replace("example.com/lesson", "example.com/other")
    assert normalized_text(original) != normalized_text(wrong)
    assert normalized_text(original) != normalized_text('<p>参考 原文</p>')


def test_export_preserves_heading_levels_and_code_without_loading_resources():
    xml = summary_xml('## 大节\n\n### 小节\n\n```python\nprint("ok")\n```')
    assert "<h2>大节</h2>" in xml
    assert "<h3>小节</h3>" in xml
    assert '<pre lang="python"><code>' in xml
    assert "print(&quot;ok&quot;)" in xml


def test_sibling_headings_keep_the_same_level_and_skipped_depths_are_continuous():
    xml = summary_xml("## First\n\n## Second\n\n#### Detail\n\n## Third")
    assert xml.count("<h2>") == 3
    assert "<h3>Detail</h3>" in xml


def test_transport_export_date_is_not_a_content_revision_or_repeated_metadata():
    from video_transcript_api.exports.feishu import _version_text

    header = ("---\nTitle: Source\nPlatform: test\nType: summary\n"
              "Source: https://example.com/video\nExport-Date: 2026-10-18\n---\n")
    _, old = build_document(TASK, header + "实际正文日期：2026-10-18。", header + "完整正文。", calibrated=True)
    _, new = build_document(TASK, "实际正文日期：2026-10-18。", "完整正文。", calibrated=True)
    assert _version_text(old) == _version_text(new)
    assert normalized_text(old) != normalized_text(new)  # Full verification stays strict.
    assert _version_text(new) != _version_text(new.replace("实际正文日期：2026-10-18", "实际正文日期：2026-10-22"))
    source = LocalResults({"api_base": "http://localhost:8000"})
    source.read = lambda path: header + ("AI 解读。" if "summary" in path else "完整正文。")
    _, result = source.document(TASK)
    assert "Export-Date:" not in result and "Platform: test" not in result


class RevisedSource(Source):
    def __init__(self):
        self.version = 1
        self.document_reads = 0

    def tasks(self):
        yield {**TASK, "updated_at": f"2026-10-22T00:00:0{self.version}Z"}

    def document(self, task):
        self.document_reads += 1
        return build_document(task, f"## 版本 {self.version}\n\n核心结论。", "完整正文。", calibrated=True)


def test_changed_source_updates_same_unchanged_remote_revision(tmp_path):
    source, cli = RevisedSource(), CLI()
    job = worker(tmp_path, cli, source)
    assert job.run_once()["counts"] == {"done": 1}
    source.version = 2
    assert job.run_once()["counts"] == {"done": 1}
    assert "版本 2" in cli.xml
    assert cli.calls == 1 and cli.updates == 1
    reads = source.document_reads
    assert job.run_once()["exported_this_run"] == 0
    assert source.document_reads == reads


@pytest.mark.parametrize("edit", ["text", "format", "resource"])
def test_remote_human_edits_are_not_overwritten(tmp_path, edit):
    source, cli = RevisedSource(), CLI()
    job = worker(tmp_path, cli, source)
    job.run_once()
    if edit == "text":
        cli.xml += "<p>My note</p>"
    elif edit == "format":
        cli.xml = cli.xml.replace("核心结论。", "<b>核心结论。</b>")
    else:
        cli.xml += '<img src="human-resource"/>'
    edited = cli.xml
    source.version = 2
    assert job.run_once()["counts"] == {"conflict": 1}
    assert cli.xml == edited and cli.updates == 0


def test_unknown_update_result_is_reconciled_before_any_second_write(tmp_path):
    source, cli = RevisedSource(), CLI()
    job = worker(tmp_path, cli, source)
    job.run_once()
    source.version = 2
    cli.update_timeout = True
    assert job.run_once()["counts"] == {"updating": 1}
    job.db.execute("UPDATE exports SET next_retry=0")
    job.db.commit()
    assert job.run_once()["counts"] == {"done": 1}
    assert cli.calls == 1 and cli.updates == 1


def test_unknown_update_cannot_claim_later_human_rich_edits_as_its_baseline(tmp_path):
    source, cli = RevisedSource(), CLI()
    job = worker(tmp_path, cli, source)
    job.run_once()
    source.version = 2
    cli.update_timeout = True
    job.run_once()
    cli.xml += '<img src="my-manual-image"/>'
    cli.revision += 1
    job.db.execute("UPDATE exports SET next_retry=0")
    job.db.commit()
    assert job.run_once()["counts"] == {"done": 1}
    assert job.db.execute("SELECT remote_digest FROM exports").fetchone()[0] is None
    source.version = 3
    assert job.run_once()["counts"] == {"conflict": 1}
    assert cli.updates == 1 and "my-manual-image" in cli.xml


def test_legacy_remote_formatting_is_never_adopted_as_a_generated_baseline(tmp_path):
    source, cli = RevisedSource(), CLI()
    job = worker(tmp_path, cli, source)
    job.run_once()
    job.db.execute("UPDATE exports SET remote_digest=NULL,source_revision=NULL")
    job.db.commit()
    cli.xml += '<img src="human-resource"/>'
    job.run_once()
    assert job.db.execute("SELECT remote_digest FROM exports").fetchone()[0] is None
    source.version = 2
    assert job.run_once()["counts"] == {"conflict": 1}
    assert cli.updates == 0 and "human-resource" in cli.xml


def test_legacy_archive_schema_is_extended_without_losing_records(tmp_path):
    import sqlite3

    path = tmp_path / "archive.db"
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE exports (
            source_key TEXT PRIMARY KEY, task_id TEXT, title TEXT, content TEXT,
            status TEXT NOT NULL, document_id TEXT, document_url TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, next_retry REAL NOT NULL DEFAULT 0,
            last_error TEXT, updated_at REAL NOT NULL)''')
        db.execute("INSERT INTO exports(source_key,status,updated_at) VALUES('old','done',0)")
    job = worker(tmp_path)
    assert job.db.execute("SELECT status FROM exports WHERE source_key='old'").fetchone()[0] == "done"
    assert "source_revision" in {row[1] for row in job.db.execute("PRAGMA table_info(exports)")}
