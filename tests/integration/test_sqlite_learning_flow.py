"""Offline SQLite learning flow through a real isolated API and worker.

Copies only public source files into a disposable runtime. Credentials, HOME,
configuration, data, HTTP ports and model results all belong to this test.
No user database, running service, external network or paid model is used.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import commentjson


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "\n\n".join(
    f"Public source paragraph {number}: A learning note should preserve the original "
    "material, explain its main ideas and record questions for later review. "
    "Keeping the source and notes together makes the result easier to verify."
    for number in range(1, 9)
)
SUMMARY = (
    "## Learning summary\n\n"
    "Preserve original material, explain its main ideas and record questions. "
    "Keep source material and notes together so that a later review can verify "
    "the explanation against the source."
)
NOTE = "SQLite persistence note: verify the source before accepting a summary."


@contextmanager
def _running_api(runtime: Path, environment: dict, port: int, token: str):
    """Start and stop only this test's isolated server process."""
    with (runtime / "startup.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, str(runtime / "start_isolated.py")],
            cwd=runtime, env=environment, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError, ConnectionError):
                    time.sleep(0.1)
            else:
                diagnostic = (runtime / "startup.log").read_text(errors="replace")
                raise AssertionError(diagnostic.replace(token, "[redacted]")[-5000:])
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_sqlite_text_learning_exports_notes_and_restart(tmp_path):
    """A new SQLite install completes, exports and retains one actual task."""
    shutil.copytree(
        ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"),
    )
    initialize = runpy.run_path(str(ROOT / "scripts/init_config.py"))["initialize_config"]
    config_path = tmp_path / "config/config.jsonc"
    initialize(config_path, ROOT / "config/config.example.jsonc")
    config = commentjson.loads(config_path.read_text())
    token = config["api"]["auth_token"]
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config["api"]["host"] = "127.0.0.1"
    config["api"]["port"] = port
    config["llm"]["api_key"] = ""
    config["llm"]["base_url"] = "http://127.0.0.1:9/v1"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "home").mkdir()
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "PYTHONPATH": str(tmp_path / "src"),
        "PYTHONUNBUFFERED": "1",
        "LEARNFLUX_PERSISTENCE_BACKEND": "sqlite",
        "LEARNFLUX_OBJECT_BACKEND": "local",
    }
    runner = '''import json
import socket
import sys
from pathlib import Path

class NoOptionalOcr:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"paddle", "paddleocr", "paddlex"}:
            raise ModuleNotFoundError("Optional OCR is absent in the SQLite smoke")
sys.meta_path.insert(0, NoOptionalOcr())
original_connect = socket.socket.connect
original_resolve = socket.getaddrinfo
def guard(host):
    if host not in {"localhost", "127.0.0.1", "::1"}:
        Path("blocked_network.txt").write_text("An external connection was blocked.")
        raise OSError("External networking is disabled for the SQLite smoke")
def connect(instance, address):
    if isinstance(address, tuple): guard(address[0])
    return original_connect(instance, address)
def resolve(host, *args, **kwargs):
    guard(host)
    return original_resolve(host, *args, **kwargs)
socket.socket.connect = connect
socket.getaddrinfo = resolve

# Replace only the model orchestration result. HTTP routing, document parsing,
# worker queues, terminal status, SQLite writes and artifact exports remain real.
from video_transcript_api.llm.coordinator import LLMCoordinator
def offline_model(self, content, **kwargs):
    assert isinstance(content, str) and "Public source paragraph" in content
    with Path("llm_calls.jsonl").open("a") as calls:
        calls.write(json.dumps({"content_chars": len(content)}) + "\\n")
    return {
        "calibrated_text": content,
        "summary_text": SUMMARY,
        "key_info": {},
        "stats": {},
        "models_used": {},
    }
LLMCoordinator.process = offline_model
from video_transcript_api.api.server import start_server
start_server()
'''
    (tmp_path / "start_isolated.py").write_text(
        "SUMMARY = " + repr(SUMMARY) + "\n" + runner, encoding="utf-8",
    )

    def request(path, payload=None, *, content_type=None):
        headers = {"Authorization": f"Bearer {token}"}
        body = None
        if payload is not None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            headers["Content-Type"] = content_type or "application/json"
        req = Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers)
        with urlopen(req, timeout=10) as response:
            return response.status, response.read().decode()

    def request_json(path, payload=None):
        status, body = request(path, payload)
        return status, json.loads(body)

    assert not (tmp_path / "data").exists()
    with _running_api(tmp_path, environment, port, token):
        _, health = request_json("/health")
        assert health["checks"]["sqlite"] == {"healthy": True, "backend": "sqlite"}
        status, accepted = request_json(
            "/api/study/text", {"title": "Public SQLite learning example", "content": SOURCE},
        )
        assert status == 202
        task_id = accepted["data"]["task_id"]
        view_token = accepted["data"]["view_token"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            _, task = request_json(f"/api/task/{task_id}")
            if task["data"]["status"] in {"success", "failed", "no_transcript"}:
                break
            time.sleep(0.1)
        assert task["data"]["status"] == "success", task
        status, note = request_json(
            f"/api/study/{view_token}/notes", {"body": NOTE},
        )
        assert status == 200 and note["data"]["body"] == NOTE
        status, collection = request_json(
            "/api/collections",
            {"title": "SQLite collection", "creator_name": "Offline test", "collection_type": "document_topic"},
        )
        assert status == 200
        collection_id = collection["data"]["id"]
        boundary = "sqlite-reading-smoke-boundary"
        upload = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="public-reading.txt"\r\nContent-Type: text/plain\r\n\r\n'
            f'{SOURCE}\r\n--{boundary}--\r\n'
        ).encode()
        status, imported = request(
            "/api/reading/documents", upload,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        document = json.loads(imported)["data"]
        assert status == 201 and document["status"] == "ready"
        document_id = document["id"]
        status, markdown = request(f"/api/study/{view_token}/export/markdown")
        assert status == 200
        assert "Public source paragraph 1:" in markdown
        assert SUMMARY in markdown and NOTE in markdown
        assert request(f"/view/{view_token}")[0] == 200
        for kind, expected in (("transcript", SOURCE), ("calibrated", SOURCE), ("summary", SUMMARY)):
            status, exported = request(f"/export/{view_token}/{kind}")
            assert status == 200 and expected in exported

    # The worker, rather than test code, must have saved status and artifacts.
    db_path = tmp_path / "data/cache/cache.db"
    with sqlite3.connect(db_path) as database:
        row = database.execute(
            "SELECT status, media_id FROM task_status WHERE task_id = ?", (task_id,),
        ).fetchone()
        assert row[0] == "success"
        stored = database.execute(
            "SELECT files_loc FROM video_cache WHERE media_id = ?", (row[1],),
        ).fetchone()
        artifact_dir = Path(stored[0])
        if not artifact_dir.is_absolute():
            artifact_dir = tmp_path / "data/cache" / artifact_dir
        artifact_dir.resolve().relative_to(tmp_path.resolve())
        assert (artifact_dir / "transcript_capswriter.txt").read_text() == SOURCE
        assert (artifact_dir / "llm_calibrated.txt").read_text() == SOURCE
        assert (artifact_dir / "llm_summary.txt").read_text() == SUMMARY

    with _running_api(tmp_path, environment, port, token):
        _, task = request_json(f"/api/task/{task_id}")
        assert task["data"]["status"] == "success"
        _, session = request_json(f"/api/study/{view_token}")
        assert session["data"]["ai"]["overview"] == SUMMARY
        assert any(item["body"] == NOTE for item in session["data"]["notes"])
        _, restored = request_json(f"/api/collections/{collection_id}")
        assert restored["data"]["title"] == "SQLite collection"
        _, reading = request_json(f"/api/reading/documents/{document_id}")
        assert reading["data"]["document"]["status"] == "ready"
        assert "Public source paragraph 1:" in "\n".join(
            chapter["plain_text"] for chapter in reading["data"]["chapters"]
        )
        status, markdown = request(f"/api/study/{view_token}/export/markdown")
        assert status == 200 and SUMMARY in markdown and NOTE in markdown
        assert request(f"/view/{view_token}")[0] == 200

    calls = (tmp_path / "llm_calls.jsonl").read_text().splitlines()
    assert len(calls) == 1, "Restart must reuse the stored result without another model call"
    assert not (tmp_path / "blocked_network.txt").exists()
