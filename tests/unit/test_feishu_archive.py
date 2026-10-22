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

    def create(self, parent, xml):
        self.calls += 1
        self.xml = xml
        if self.timeout:
            raise RuntimeError("Timed out after remote creation")
        return {"document": {"document_id": "document-1", "url": "https://my.feishu.cn/docx/document-1"}}

    def fetch(self, doc):
        if self.fetch_failure:
            raise RuntimeError("Temporary read failure")
        return self.xml

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
