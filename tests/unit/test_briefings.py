"""Offline report ownership, scope, integrity and explicit-export contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from video_transcript_api.briefings.bridge_runner import ReportBridge, safe_path, edition_date, issue_metadata
from video_transcript_api.briefings.service import BriefingError, BriefingService, export_markdown, reading_html
from video_transcript_api.api.routes import briefings
from video_transcript_api.api.services.transcription import verify_token

BUNDLE = "2026-10-31-daily-20261031-122131-da42af"
LIVE = "2026-10-30-live-20261031-110904-f20656"


def report(tmp_path):
    folder = tmp_path / "exports/ai-guide-reports" / BUNDLE
    folder.mkdir(parents=True)
    body = b"# Public daily report\n\nEvidence with sources.\n"
    (folder / "report.md").write_bytes(body)
    (folder / "report.html").write_text("<html><body>Safe report</body></html>")
    files = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("report.md", "report.html")}
    (folder / "manifest.json").write_text(json.dumps({"date": "2026-10-31", "files": files}))
    (tmp_path / "state").mkdir()
    (tmp_path / "state/latest-ai-guide-report.json").write_text(json.dumps({"bundle": BUNDLE}))
    return folder, body


def test_bridge_rejects_tampered_and_nonreport_files(tmp_path):
    folder, body = report(tmp_path)
    bridge = ReportBridge(tmp_path)
    assert bridge.read("ai", BUNDLE, "report.md") == body
    (folder / "report.md").write_text("tampered")
    with pytest.raises(ValueError): bridge.read("ai", BUNDLE, "report.md")
    for name in ("manifest.json", "report.json", "../../private/key", "/etc/passwd"):
        with pytest.raises(ValueError): bridge.read("ai", BUNDLE, name)


def test_bridge_rejects_symlink_ancestors(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    root = tmp_path / "root"; root.mkdir()
    (root / "exports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError): safe_path(root, "exports/report.md")


def test_policy_is_checked_again_after_read(tmp_path, monkeypatch):
    (tmp_path / "report.md").write_text("private")
    store = Mock()
    store.manifest.side_effect = [(tmp_path, {}), ValueError("scope revoked")]
    store.read.return_value = b"private"
    bridge = ReportBridge(tmp_path)
    monkeypatch.setattr(bridge, "wechat_store", lambda: store)
    with pytest.raises(ValueError): bridge.read("wechat", LIVE, "report.md")
    assert store.manifest.call_count == 2


def test_catalog_keeps_healthy_ai_when_wechat_policy_fails(tmp_path, monkeypatch):
    report(tmp_path)
    bridge = ReportBridge(tmp_path)
    monkeypatch.setattr(bridge, "wechat_store", Mock(side_effect=ValueError("scope invalid")))
    data = bridge.catalog()
    assert len(data["items"]) == 1 and data["items"][0]["kind"] == "ai"
    assert data["warnings"][0]["kind"] == "wechat"


def test_reading_removes_active_content_and_keeps_source_links():
    source = b'<html><head><style>p{color:black}</style></head><body><aside class="sidebar">Old nav</aside><main><a href="sources.html#message">Source</a><img src="media/image.png" onerror="alert(1)"><script>fetch("/private")</script><a href="javascript:alert(1)">Unsafe</a><img src="https://tracker.invalid/a"></main></body></html>'
    page = reading_html(source, "wechat").decode()
    assert "<script" not in page and "onerror" not in page and "javascript:" not in page
    assert 'href="sources.html#message"' in page and 'src="media/image.png"' in page
    assert "tracker.invalid" not in page and "Old nav" not in page


def test_export_keeps_provenance_but_not_broken_local_links():
    text = export_markdown("[Speaker 12:00](sources.html#id) [Public](https://example.org/post)")
    assert "Speaker 12:00" in text and "sources.html" not in text
    assert "https://example.org/post" in text


def test_issue_dates_use_content_semantics_not_rebuild_time():
    assert edition_date("wechat", LIVE) == edition_date("ai", BUNDLE) == "2026-10-31"
    later_rebuild = "2026-10-30-live-20261120-110904-abcdef"
    assert edition_date("wechat", later_rebuild) == "2026-10-31"
    assert edition_date("wechat", "2026-12-31-live-20270102-110904-abcdef") == "2027-01-01"
    assert issue_metadata("wechat", LIVE, {})["content_date"] == "2026-10-30"
    with pytest.raises(ValueError): issue_metadata("wechat", LIVE, {"edition_date":"2026-11-01"})


def test_catalog_aligns_same_issue_without_relabeling_artifacts(tmp_path, monkeypatch):
    report(tmp_path)
    bridge = ReportBridge(tmp_path)
    store = Mock()
    store.history.return_value = [{"bundle": LIVE, "date":"2026-10-30"}]
    store.latest.return_value = LIVE
    store.manifest.return_value = (tmp_path, {"date":"2026-10-30"})
    monkeypatch.setattr(bridge, "wechat_store", lambda: store)
    items=bridge.catalog()["items"]
    assert {x["date"] for x in items} == {"2026-10-31"}
    assert next(x for x in items if x["kind"]=="wechat")["bundle"] == LIVE


def test_wechat_download_and_preview_share_issue_date(tmp_path, monkeypatch):
    instance=BriefingService({},obsidian={"enabled":True,"vault_path":str(tmp_path)})
    monkeypatch.setattr(instance,"_bridge",lambda *_:'# 微信日报 · 2026-10-30\n\nActual summary'.encode())
    result=instance.preview("wechat",LIVE,"obsidian")
    assert result["title"].endswith("2026-10-31")
    assert result["markdown"].startswith('# 微信日报 · 2026-10-31\n')
    assert '内容日期：2026-10-30' in result["markdown"]


def test_wechat_chrome_removal_preserves_limits_and_all_evidence():
    raw='<html><body><aside class="sidebar"><details class="system-status"><summary>Coverage</summary><p>Some images are thumbnails</p></details></aside><main id="report"><header class="topbar">Old date</header><section id="groups"><p>Real summary</p><a href="sources.html#s">Speaker 12:00</a><img src="media/a.png"></section><section id="private"><p>Private summary</p></section><div class="mobile-utilities">Duplicate controls</div></main></body></html>'
    page=reading_html(raw.encode(),"wechat").decode()
    for text in ['Real summary','Private summary','Speaker 12:00','Some images are thumbnails','media/a.png']:
        assert text in page
    assert 'Old date' not in page and 'Duplicate controls' not in page
    assert page.count('Some images are thumbnails') == 1
    assert 'href="#groups"' in page


@pytest.fixture
def service(tmp_path, monkeypatch):
    vault = tmp_path / "vault"; vault.mkdir()
    instance = BriefingService({"state_dir": str(tmp_path / "state")}, obsidian={"enabled": True, "vault_path": str(vault)})
    monkeypatch.setattr(instance, "read", lambda *_: b"# Daily report\n\nReviewed facts.\n")
    return instance, vault


def test_obsidian_preview_is_readonly_apply_is_idempotent_and_protects_edits(service):
    instance, vault = service
    preview = instance.preview("ai", BUNDLE, "obsidian")
    assert list(vault.iterdir()) == []
    def sync(): return instance.sync("ai", BUNDLE, "obsidian", preview["content_sha256"], confirm=True, confirm_private=False)
    assert sync()["status"] == "done"
    assert sync()["status"] == "unchanged"
    note = next(vault.rglob("*.md")); note.write_text("my edits")
    assert sync()["status"] == "conflict"
    assert note.read_text() == "my edits"


def test_stale_preview_and_missing_private_confirmation_cannot_write(service):
    instance, vault = service
    for kind, digest, confirmed in (("ai", "0" * 64, True), ("wechat", "0" * 64, False)):
        with pytest.raises(BriefingError):
            instance.sync(kind, LIVE if kind == "wechat" else BUNDLE, "obsidian", digest, confirm=True, confirm_private=confirmed)
    assert list(vault.iterdir()) == []


@pytest.fixture
def client(monkeypatch):
    instance = Mock()
    instance.catalog.return_value = {"items": [], "warnings": [], "destinations": {}}
    user = {"user_id": "owner"}
    app = FastAPI(); app.include_router(briefings.router)
    async def current_user(): return user
    app.dependency_overrides[verify_token] = current_user
    monkeypatch.setattr(briefings, "local_request", lambda request: None)
    monkeypatch.setattr(briefings, "load_settings", lambda: {"enabled": True, "source_root": "/configured/source", "owner_user_id": "owner"})
    monkeypatch.setattr(briefings, "load_archive_config", lambda: None)
    monkeypatch.setattr(briefings, "get_config", lambda: {})
    monkeypatch.setattr(briefings, "BriefingService", lambda *a, **k: instance)
    with TestClient(app) as current: yield current, user, instance


def test_nonowner_cannot_list_read_preview_or_sync(client):
    current, user, instance = client
    user["user_id"] = "other"
    for suffix in ("", "/ai/" + BUNDLE + "/files/report.html", "/ai/" + BUNDLE + "/preview/obsidian"):
        assert current.get("/api/briefings" + suffix).status_code == 403
    assert current.post("/api/briefings/ai/" + BUNDLE + "/sync/obsidian", json={"content_sha256": "0" * 64, "confirm": True}).status_code == 403
    instance.catalog.assert_not_called(); instance.read.assert_not_called(); instance.sync.assert_not_called()


def test_read_only_requests_do_not_sync_and_responses_are_not_cached(client):
    current, _, instance = client
    response = current.get("/api/briefings")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    instance.sync.assert_not_called()
    instance.read.return_value = b"<html><body>Public content</body></html>"
    response = current.get("/api/briefings/ai/" + BUNDLE + "/files/report.html")
    assert "script-src 'none'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert "allow-popups-to-escape-sandbox" in response.headers["content-security-policy"]


def test_page_is_an_empty_authenticated_shell(client):
    current, _, instance = client
    response = current.get("/briefings")
    assert response.status_code == 200
    assert "briefings-frame" in response.text and "LearnFlux" in response.text
    instance.read.assert_not_called()


def test_download_filename_uses_issue_date(client):
    current, _, instance = client
    instance.read.return_value = b'# Test report\n'
    response = current.get(f"/api/briefings/wechat/{LIVE}/files/report.md")
    assert response.status_code == 200
    assert 'wechat-2026-10-31.md' in response.headers['content-disposition']


def test_bad_optional_delivery_config_does_not_block_reading(client, monkeypatch):
    current, _, _ = client
    monkeypatch.setattr(briefings, "load_archive_config", Mock(side_effect=ValueError("broken config")))
    assert current.get("/api/briefings").status_code == 200


@pytest.mark.parametrize("peer,host,origin", [("192.0.2.1", "localhost:8000", None), ("127.0.0.1", "external.example", None), ("127.0.0.1", "localhost:8000", "https://evil.example")])
def test_remote_or_cross_origin_access_rejected(peer, host, origin):
    headers = [(b"host", host.encode())]
    if origin: headers.append((b"origin", origin.encode()))
    request = Request({"type": "http", "scheme": "http", "method": "GET", "path": "/api/briefings", "headers": headers, "client": (peer, 1234), "server": ("127.0.0.1", 8000), "query_string": b""})
    with pytest.raises(HTTPException): briefings.local_request(request)


def test_unknown_old_feishu_creation_cannot_confirm_new_preview(tmp_path, monkeypatch):
    from video_transcript_api.exports.feishu import ArchiveWorker
    import video_transcript_api.briefings.service as module
    cfg = {"parent_node_token": "parent", "space_id": "space", "cli_path": "/fake", "state_db": str(tmp_path / "feishu.db")}
    old = "2026-10-31-daily-20261031-110000-aaaaaa"
    instance = BriefingService({"state_dir": str(tmp_path)}, feishu=cfg)
    class CLI:
        def call(self, *args): return {"nodes": [{"title": "Old", "obj_type": "docx", "obj_token": "doc", "node_token": "node"}], "has_more": False}
        def fetch(self, _id): return "<title>Old</title><p>Old body</p>"
        def fetch_document(self, _id): return {"content": self.fetch(_id), "revision_id": 1}
    cli = CLI()
    worker = ArchiveWorker(cfg, source=Mock(), cli=cli)
    key = "parent:briefing:ai:2026-10-31"
    worker.db.execute("INSERT INTO exports(source_key,task_id,title,content,status,source_revision,updated_at) VALUES(?,?,?,?,?,?,?)", (key, old, "Old", cli.fetch("doc"), "uncertain", "old-revision", 0)); worker.db.commit(); worker.db.close()
    monkeypatch.setattr(module, "ArchiveWorker", lambda config, source: ArchiveWorker(config, source=source, cli=cli))
    result = instance._feishu_sync("ai", BUNDLE, {"title": "New", "markdown": "New body", "content_sha256": "a" * 64})
    assert result["status"] == "pending"
    assert "新版尚未同步" in result["label"]


def test_feishu_sample_to_daily_and_duplicate_sync_use_one_document(tmp_path, monkeypatch):
    from video_transcript_api.exports.feishu import ArchiveWorker
    import video_transcript_api.briefings.service as module
    cfg = {"parent_node_token": "parent", "space_id": "space", "cli_path": "/fake", "state_db": str(tmp_path / "feishu.db")}
    instance = BriefingService({"state_dir": str(tmp_path)}, feishu=cfg)
    class CLI:
        creates = 0
        updates = 0
        revision = 1
        content = ""
        def create(self, _parent, content):
            self.creates += 1; self.content = content
            return {"document": {"document_id": "doc", "url": "https://my.feishu.cn/docx/test", "revision_id": self.revision}}
        def update(self, _id, content, revision):
            assert revision == self.revision
            self.updates += 1; self.revision += 1; self.content = content
            return {"document": {"revision_id": self.revision}}
        def fetch_document(self, _id): return {"content": self.content, "revision_id": self.revision}
    cli = CLI()
    monkeypatch.setattr(module, "ArchiveWorker", lambda config, source: ArchiveWorker(config, source=source, cli=cli))
    old = "2026-10-31-sample-20261031-100000-aaaaaa"
    preview = {"title": "Daily", "markdown": "Initial", "content_sha256": "a" * 64}
    assert instance._feishu_sync("ai", old, preview)["status"] == "done"
    preview.update(markdown="Updated", content_sha256="b" * 64)
    assert instance._feishu_sync("ai", BUNDLE, preview)["status"] == "done"
    assert instance._feishu_sync("ai", BUNDLE, preview)["status"] == "done"
    assert cli.creates == 1 and cli.updates == 1
    assert instance._feishu_sync("ai", old, preview)["status"] == "conflict"
