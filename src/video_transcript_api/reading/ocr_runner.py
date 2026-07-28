"""One-page PaddleOCR command runner for the local reading importer."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def parse_arguments() -> argparse.Namespace:
    """Parse the one-page input/output contract used by the parent process."""
    parser = argparse.ArgumentParser(description="Run local OCR for one page image")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def run(input_path: Path, output_path: Path) -> int:
    """Recognize one image and atomically persist the serializable Paddle result."""
    try:
        os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
        from paddleocr import PaddleOCR

        results = list(PaddleOCR(lang="ch").predict(str(input_path)))
        result = results[0].json.get("res", {}) if results else {}
        if not isinstance(result, dict):
            return 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary_file:
            json.dump({"res": result}, temporary_file, ensure_ascii=False)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(output_path)
        return 0
    except Exception:
        return 1


def main() -> int:
    """Run the standalone OCR process."""
    arguments = parse_arguments()
    return run(arguments.input, arguments.output)


if __name__ == "__main__":
    sys.exit(main())
