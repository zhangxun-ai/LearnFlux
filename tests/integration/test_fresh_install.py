"""Offline new-config startup smoke in a disposable source/runtime directory.

Reuses installed Python packages; it does not install dependencies or use real
credentials, user data, ASR, or a demo server. All outbound network is blocked.
Run explicitly: uv run --extra dev pytest tests/integration/test_fresh_install.py
"""

import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import commentjson


ROOT = Path(__file__).resolve().parents[2]


def test_fresh_config_starts_real_pages_without_external_services(tmp_path):
    # This task-created pytest directory is disposable. Never copy config/data.
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    initializer = runpy.run_path(str(ROOT / "scripts/init_config.py"))["initialize_config"]
    config_path = tmp_path / "config/config.jsonc"
    initializer(config_path, ROOT / "config/config.example.jsonc")
    config = commentjson.loads(config_path.read_text())
    token = config["api"]["auth_token"]
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config["api"]["port"] = port
    config["llm"]["api_key"] = ""
    config["llm"]["base_url"] = "http://127.0.0.1:9/v1"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    runner = tmp_path / "start_isolated.py"
    runner.write_text('''import socket
import sys
from pathlib import Path
class NoOptionalOcr:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"paddle", "paddleocr", "paddlex"}:
            raise ModuleNotFoundError("Optional OCR is absent in the install smoke")
sys.meta_path.insert(0, NoOptionalOcr())
original_connect = socket.socket.connect
original_resolve = socket.getaddrinfo
allowed = {"localhost", "127.0.0.1", "::1"}
def guard(host):
    if host not in allowed:
        Path("blocked_network.txt").write_text("An external connection was blocked.")
        raise OSError("External networking is disabled for the install smoke")
def connect(instance, address):
    if isinstance(address, tuple): guard(address[0])
    return original_connect(instance, address)
def resolve(host, *args, **kwargs):
    guard(host)
    return original_resolve(host, *args, **kwargs)
socket.socket.connect = connect
socket.getaddrinfo = resolve
from video_transcript_api.api.server import start_server
start_server()
''', encoding="utf-8")
    environment = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(tmp_path / "src"),
        "PYTHONUNBUFFERED": "1",
    }
    log_path = tmp_path / "startup.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, str(runner)], cwd=tmp_path, env=environment,
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 25
            ready = False
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as response:
                        ready = response.status == 200
                        if ready:
                            break
                except (URLError, TimeoutError, ConnectionError):
                    time.sleep(0.1)
            diagnostic = log_path.read_text(errors="replace").replace(token, "[redacted]")
            assert ready, diagnostic[-4000:]
            for path in ("/", "/settings", "/add_task_by_web"):
                with urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                    assert response.status == 200
                    html = response.read().decode()
                    if path == "/add_task_by_web":
                        assert 'id="study-text-content"' in html
            assert not (tmp_path / "blocked_network.txt").exists(), "Startup tried an external service"
            assert (tmp_path / "data").is_dir()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
