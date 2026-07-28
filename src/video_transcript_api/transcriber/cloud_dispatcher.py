"""Single durable dispatcher for user-confirmed cloud ASR work."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from .cloud_quote_repository import CloudQuoteConflict
from .concurrency import ConcurrencyLimitError


class CloudASRDispatcher:
    """Lease durable quotes only after a cloud capacity slot is available."""

    def __init__(
        self,
        quote_repository: Any,
        usage_repository: Any,
        controller: Any,
        executor: Any,
        run_callback: Callable[..., Any],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.quote_repository = quote_repository
        self.usage_repository = usage_repository
        self.controller = controller
        self.executor = executor
        self.run_callback = run_callback
        self.clock = clock
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._submit_failed_tasks: set[str] = set()

    def start(self) -> None:
        """Start one idempotent daemon dispatcher."""
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._stop_event.is_set():
                raise RuntimeError("dispatcher_stopped")
            self._thread = threading.Thread(
                target=self._run,
                name="cloud-asr-dispatcher",
                daemon=True,
            )
            self._thread.start()

    def notify(self, task_id: str | None = None) -> bool:
        """Wake the scanner; a task id only clears its submit-failure pause."""
        with self._condition:
            if self._stop_event.is_set():
                return False
            if task_id is not None:
                self._submit_failed_tasks.discard(task_id)
            self._condition.notify_all()
            return True

    def stop(self, *, timeout: float = 2.0) -> bool:
        """Stop accepting notifications and join the scanner boundedly."""
        self._stop_event.set()
        self.controller.wake_waiters()
        with self._condition:
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            return not thread.is_alive()
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            now = self.clock()
            self.quote_repository.requeue_expired_leases(now=now)
            self.usage_repository.freeze_stale_submissions(now=now)
            queued = [
                task_id
                for task_id in self.quote_repository.list_confirmed_queued()
                if task_id not in self._submit_failed_tasks
            ]
            if not queued:
                self._wait_for_work(now)
                continue
            for task_id in queued:
                if self._stop_event.is_set():
                    return
                if not self._dispatch_one(task_id):
                    self._wait_for_work(now)
                    break

    def _dispatch_one(self, task_id: str) -> bool:
        nonce = uuid4().hex
        claim_owner = f"claim:{nonce}"
        slot_owner = f"continuation:{nonce}"
        if not self.controller.try_acquire("cloud", slot_owner):
            return False
        try:
            self.quote_repository.claim_queued(task_id, claim_owner)
        except CloudQuoteConflict:
            self._release_slot(slot_owner)
            return True
        try:
            self.executor.submit(
                self._run_claimed,
                task_id,
                claim_owner,
                slot_owner,
            )
        except Exception:
            self.quote_repository.requeue_claim(task_id, claim_owner)
            self._submit_failed_tasks.add(task_id)
            self._release_slot(slot_owner)
        return True

    def _run_claimed(
        self, task_id: str, claim_owner: str, slot_owner: str
    ) -> None:
        try:
            self.run_callback(
                task_id,
                claim_owner=claim_owner,
                slot_owner=slot_owner,
            )
        finally:
            # The provider may have transferred this owner to a durable usage id.
            self._release_slot(slot_owner)
            self.notify()

    def _release_slot(self, owner: str) -> None:
        try:
            self.controller.release("cloud", owner)
        except ConcurrencyLimitError:
            pass

    def _wait_for_work(self, now: datetime) -> None:
        expiries = [
            self.quote_repository.next_lease_expiry(),
            self.usage_repository.next_submission_lease_expiry(now=now),
        ]
        live = [expiry for expiry in expiries if expiry is not None]
        timeout = None
        if live:
            timeout = max(0.0, (min(live) - now).total_seconds())
        with self._condition:
            if not self._stop_event.is_set():
                self._condition.wait(timeout=timeout)
