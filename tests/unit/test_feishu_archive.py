"""Content integrity, safe rendering, durable retries, and duplicate prevention."""

import json
from pathlib import Path

import pytest

from video_transcript_api.exports.feishu import (
    ArchiveWorker, FeishuRejected, LocalResults, build_document, normalized_text, summary_xml,
)


TASK = {"task_id": "task-1", "view_token": "private-view", "status": "success",
        "title": "AI 热词 本视频22分钟", "author": "Author", "platform": "douyin",
        "url": "https://example.com/video", "created_at": "2026-10-18T11:13:00"}


class Source:
    def tasks(self):
        yield TASK

    def document(self, task):
        return build_document(task, "## 结论\n\n**重要观点**。", "第一句。\n\n最后一句。", calibrated=True)


class CLI:
    def __init__(self):
        self.calls = 0
        self.xml = ""
        self.timeout = False
        self.fetch_failure = False
        self.revision = 1
        self.updates = 0
        self.update_timeout = False

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

    def fetch_document(self, doc):
        return {"content": self.fetch(doc), "revision_id": self.revision}

    def update(self, doc, xml, revision_id):
        assert revision_id == self.revision
        self.xml = xml
        self.revision += 1
        self.updates += 1
        if self.update_timeout:
            raise RuntimeError("Timed out after remote update")
        return {"document": {"revision_id": self.revision}}

    def call(self, *args, **kwargs):
        return {"nodes": [{"title": Source().document(TASK)[0], "obj_token": "document-1",
                            "obj_type": "docx", "node_token": "node-1"}], "has_more": False}


def worker(tmp_path, cli=None, source=None):
    return ArchiveWorker({"state_db": str(tmp_path / "archive.db"), "parent_node_token": "parent",
                          "space_id": "space"}, source=source or Source(), cli=cli or CLI())


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
