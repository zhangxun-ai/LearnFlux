"""Durable worker for collection summary jobs."""

from __future__ import annotations

import threading
import uuid
from typing import Optional

from ..utils.logging import setup_logger
from .service import LearningCollectionService

logger = setup_logger("collection_summary_worker")


class CollectionSummaryWorker:
    """Poll persisted jobs and keep their lease alive while LLM work runs."""

    def __init__(
        self,
        service: LearningCollectionService,
        *,
        poll_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 10.0,
        lease_seconds: int = 60,
    ) -> None:
        self.service = service
        self.repository = service.repository
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        self.heartbeat_interval_seconds = max(
            0.05,
            float(heartbeat_interval_seconds),
        )
        self.lease_seconds = max(1, int(lease_seconds))
        self.worker_id = f"summary-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> dict[str, int]:
        """Recover interrupted state and start one daemon polling thread."""
        recovery = self.repository.recover_interrupted_summary_jobs()
        if self._thread and self._thread.is_alive():
            return recovery
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="collection-summary-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Collection summary worker started: worker_id={} recovery={}",
            self.worker_id,
            recovery,
        )
        return recovery

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        logger.info("Collection summary worker stop requested: worker_id={}", self.worker_id)

    def run_once(self) -> bool:
        """Claim and execute at most one job; return whether work was found."""
        job = self.repository.claim_next_summary_job(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if not job:
            return False

        job_id = job["job_id"]
        logger.info(
            "Collection summary job claimed: job_id={} collection_id={} attempt={}",
            job_id,
            job["collection_id"],
            job.get("attempt"),
        )
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat,
            args=(job_id, heartbeat_stop),
            name=f"collection-summary-heartbeat-{job_id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            self.service.generate_summary_job(
                job["collection_id"],
                job_id=job_id,
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=self.heartbeat_interval_seconds + 0.5)
        completed = self.repository.get_summary_job_by_id(job_id) or {}
        logger.info(
            "Collection summary job finished: job_id={} status={} phase={}",
            job_id,
            completed.get("status"),
            completed.get("phase"),
        )
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                worked = self.run_once()
            except Exception:
                logger.exception("Collection summary worker iteration failed")
                worked = False
            if not worked:
                self._stop_event.wait(self.poll_interval_seconds)

    def _heartbeat(self, job_id: str, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.heartbeat_interval_seconds):
            if not self.repository.heartbeat_summary_job(
                job_id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
            ):
                return
