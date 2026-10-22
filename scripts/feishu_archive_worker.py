"""Run the optional local Feishu archive service independently of the API."""

import argparse
import fcntl
import json
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_transcript_api.exports.feishu import ArchiveWorker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get("enabled") is not True:
        print("Feishu archive is disabled.", flush=True)
        return
    lock_path = Path(config["state_db"]).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        worker = ArchiveWorker(config)
        try:
            while not stop.is_set():
                try:
                    print(json.dumps(worker.run_once()), flush=True)
                except Exception as error:
                    # No API keys, view URLs, bodies, or CLI stderr in logs.
                    print(json.dumps({"error_type": type(error).__name__, "status": "retrying"}), flush=True)
                if args.once:
                    break
                stop.wait(max(10, int(config.get("poll_seconds", 30))))
        finally:
            worker.db.close()


if __name__ == "__main__":
    main()
