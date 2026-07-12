import json
import os
import subprocess
import sys


def _run_import_probe(script: str):
    env = os.environ.copy()
    src_path = str(os.path.abspath("src"))
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else os.pathsep.join([src_path, env["PYTHONPATH"]])
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_lightweight_service_submodule_import_does_not_load_transcription():
    script = """
import json
import sys

import video_transcript_api.api.services.source_preservation

print(json.dumps({
    "server_loaded": "video_transcript_api.api.server" in sys.modules,
    "transcription_loaded": (
        "video_transcript_api.api.services.transcription" in sys.modules
    )
}))
"""

    result = _run_import_probe(script)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["server_loaded"] is False
    assert payload["transcription_loaded"] is False


def test_services_package_keeps_legacy_transcription_exports():
    script = """
import json

from video_transcript_api.api.services import TranscribeRequest, process_task_queue

print(json.dumps({
    "request": TranscribeRequest.__name__,
    "queue": process_task_queue.__name__,
}))
"""

    result = _run_import_probe(script)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "request": "TranscribeRequest",
        "queue": "process_task_queue",
    }


def test_root_and_api_packages_keep_legacy_app_exports():
    script = """
import json

from video_transcript_api import app
from video_transcript_api.api import start_server

print(json.dumps({
    "app_title": app.title,
    "start_server": start_server.__name__,
}))
"""

    result = _run_import_probe(script)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "app_title": "VideoTranscriptAPI",
        "start_server": "start_server",
    }
