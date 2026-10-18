"""Small ownership boundary between content, ASR, and post-ASR workers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


@dataclass
class MediaCleanupOwnership:
    """Delete controlled media exactly once unless ownership was transferred."""

    paths: tuple[Path, ...]
    preserved: frozenset[Path] = frozenset()
    _owned: bool = field(default=True, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def transfer(self) -> "MediaCleanupOwnership":
        with self._lock:
            if not self._owned:
                raise RuntimeError("media_ownership_already_transferred")
            self._owned = False
        return MediaCleanupOwnership(self.paths, self.preserved)

    def cleanup_if_owner(
        self, *, additionally_preserved: frozenset[Path] = frozenset()
    ) -> None:
        with self._lock:
            if not self._owned:
                return
            self._owned = False
        for path in self.paths:
            if path in self.preserved or path in additionally_preserved:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def submit_local_asr_continuation(
    *,
    task_id: str,
    run_provider: Callable[[], Any],
    after_provider: Callable[[Any], Any],
    media: MediaCleanupOwnership,
    controller: Any,
    asr_executor: Any,
    post_executor: Any,
    on_result: Callable[[Any], None],
    on_failure: Callable[[Exception], None],
    cancelled: Callable[[], bool] | None = None,
    submit_failure_preserved: frozenset[Path] = frozenset(),
    failure_preserved: frozenset[Path] = frozenset(),
):
    """Run only Provider under a local slot, then hand post-ASR work back."""
    owner = f"local:{task_id}:{uuid4().hex}"

    def fail(exc: Exception) -> None:
        try:
            on_failure(exc)
        except Exception:
            pass

    def preserved_after_failure() -> frozenset[Path]:
        if cancelled is not None and cancelled():
            return frozenset()
        return failure_preserved

    def post_work(result: Any, post_media: MediaCleanupOwnership) -> None:
        failed = False
        try:
            processed = after_provider(result)
            on_result(processed)
        except Exception as exc:
            failed = True
            fail(exc)
        finally:
            post_media.cleanup_if_owner(
                additionally_preserved=preserved_after_failure() if failed else frozenset()
            )

    def asr_work() -> None:
        failed = False
        try:
            acquired = controller.acquire(
                "local", owner, cancelled=cancelled
            )
            if not acquired:
                fail(RuntimeError("local_asr_cancelled"))
                return
            try:
                if cancelled is not None and cancelled():
                    fail(RuntimeError("local_asr_cancelled"))
                    return
                result = run_provider()
            except Exception as exc:
                failed = True
                fail(exc)
                return
            finally:
                controller.release("local", owner)

            post_media = media.transfer()
            try:
                post_executor.submit(post_work, result, post_media)
            except Exception as exc:
                failed = True
                post_media.cleanup_if_owner(additionally_preserved=preserved_after_failure())
                fail(exc)
        finally:
            media.cleanup_if_owner(
                additionally_preserved=preserved_after_failure() if failed else frozenset()
            )

    try:
        return asr_executor.submit(asr_work)
    except Exception as exc:
        media.cleanup_if_owner(
            additionally_preserved=submit_failure_preserved | preserved_after_failure()
        )
        fail(exc)
        raise
