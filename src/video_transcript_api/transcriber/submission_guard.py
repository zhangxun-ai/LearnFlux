"""Serialize cloud uploads and keep macOS awake while submission is local."""

from __future__ import annotations

from contextlib import contextmanager
import subprocess
import sys
import threading
from typing import Callable, Iterator

from ..utils.logging import setup_logger


logger = setup_logger("transcriber")


class CloudSubmissionGuard:
    """Allow one local upload at a time and inhibit idle sleep on macOS."""

    def __init__(
        self,
        *,
        platform: str | None = None,
        process_factory: Callable[[tuple[str, ...]], object] | None = None,
    ) -> None:
        self._platform = platform or sys.platform
        self._process_factory = process_factory or self._start_process
        self._semaphore = threading.BoundedSemaphore(1)

    @staticmethod
    def _start_process(command: tuple[str, ...]):
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold the single upload slot and a best-effort sleep assertion."""
        with self._semaphore:
            process = None
            if self._platform == "darwin":
                try:
                    process = self._process_factory(("caffeinate", "-i"))
                except OSError as exc:
                    logger.warning(
                        "Could not inhibit idle sleep during cloud upload: {}",
                        type(exc).__name__,
                    )
            try:
                yield
            finally:
                if process is not None:
                    try:
                        process.terminate()
                        process.wait(timeout=1)
                    except Exception as exc:
                        logger.warning(
                            "Could not release cloud upload sleep assertion: {}",
                            type(exc).__name__,
                        )
