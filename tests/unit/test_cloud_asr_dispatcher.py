from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event

from video_transcript_api.transcriber.cloud_dispatcher import CloudASRDispatcher
from video_transcript_api.transcriber.cloud_quote_repository import (
    CloudQuoteRepository,
    NewCloudQuote,
)
from video_transcript_api.transcriber.concurrency import (
    TranscriptionConcurrencyController,
)


def _quote(task_id: str) -> NewCloudQuote:
    return NewCloudQuote(
        task_id=task_id,
        media_ref=f"cloud_quotes/{task_id}/input.m4a",
        media_sha256="a" * 64,
        duration_seconds=Decimal("2"),
        billable_seconds=2,
        model="fun-asr-2025-11-07",
        unit_price=Decimal("0.00022"),
        max_cost=Decimal("0.00044"),
    )


class _UsageRepository:
    def freeze_stale_submissions(self, *, now):
        return 0

    def next_submission_lease_expiry(self, *, now=None):
        return None


def _queue(repository: CloudQuoteRepository, task_id: str) -> None:
    repository.create(_quote(task_id), token=f"token-{task_id}")
    repository.confirm_and_queue(
        task_id, f"token-{task_id}", Decimal("0.00044")
    )


def test_cloud_limit_keeps_next_task_durable_and_dispatches_it_once(tmp_path):
    repository = CloudQuoteRepository(tmp_path / "quotes.db")
    _queue(repository, "task-1")
    _queue(repository, "task-2")
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    first_started = Event()
    release_first = Event()
    second_started = Event()
    calls = []

    def run(task_id, **kwargs):
        calls.append(task_id)
        if task_id == "task-1":
            first_started.set()
            release_first.wait(timeout=2)
        else:
            second_started.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        dispatcher = CloudASRDispatcher(
            repository,
            _UsageRepository(),
            controller,
            executor,
            run,
        )
        dispatcher.start()
        assert first_started.wait(timeout=1)
        dispatcher.notify("task-2")
        dispatcher.notify("task-2")
        assert repository.get("task-2").status == "confirmed_queued"
        assert not second_started.wait(timeout=0.05)

        release_first.set()
        assert second_started.wait(timeout=1)
        dispatcher.stop(timeout=1)

    assert calls == ["task-1", "task-2"]


def test_executor_submit_failure_requeues_claim_and_releases_slot(tmp_path):
    repository = CloudQuoteRepository(tmp_path / "quotes.db")
    _queue(repository, "task-1")
    controller = TranscriptionConcurrencyController(local=1, cloud=1)

    class FailingExecutor:
        def submit(self, *args, **kwargs):
            raise RuntimeError("executor unavailable")

    dispatcher = CloudASRDispatcher(
        repository,
        _UsageRepository(),
        controller,
        FailingExecutor(),
        lambda *args, **kwargs: None,
    )
    dispatcher.start()

    deadline = datetime.now(UTC).timestamp() + 1
    while (
        repository.get("task-1").status != "confirmed_queued"
        and datetime.now(UTC).timestamp() < deadline
    ):
        Event().wait(0.01)
    dispatcher.stop(timeout=1)

    assert repository.get("task-1").status == "confirmed_queued"
    assert controller.snapshot()["cloud_active"] == 0


def test_dispatcher_wakes_for_expired_claim_and_stops_bounded(tmp_path):
    repository = CloudQuoteRepository(tmp_path / "quotes.db")
    _queue(repository, "task-1")
    repository.claim_queued("task-1", "crashed", lease_seconds=0.05)
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    started = Event()
    executor = ThreadPoolExecutor(max_workers=1)
    dispatcher = CloudASRDispatcher(
        repository,
        _UsageRepository(),
        controller,
        executor,
        lambda *args, **kwargs: started.set(),
    )

    dispatcher.start()

    assert started.wait(timeout=1)
    assert dispatcher.stop(timeout=1)
    assert dispatcher.notify("task-1") is False
    executor.shutdown(wait=True)


def test_full_cloud_capacity_does_not_block_stale_lease_maintenance(tmp_path):
    repository = CloudQuoteRepository(tmp_path / "quotes.db")
    _queue(repository, "task-queued")
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    controller.reserve_recovered_cloud("usage:stale")

    class ExpiringUsageRepository(_UsageRepository):
        def __init__(self):
            self.freeze_calls = 0

        def freeze_stale_submissions(self, *, now):
            self.freeze_calls += 1
            return 0

        def next_submission_lease_expiry(self, *, now=None):
            return (now or datetime.now(UTC)) + timedelta(seconds=0.02)

    usage_repository = ExpiringUsageRepository()
    executor = ThreadPoolExecutor(max_workers=1)
    dispatcher = CloudASRDispatcher(
        repository,
        usage_repository,
        controller,
        executor,
        lambda *args, **kwargs: None,
    )

    try:
        dispatcher.start()
        deadline = datetime.now(UTC).timestamp() + 0.3
        while (
            usage_repository.freeze_calls < 2
            and datetime.now(UTC).timestamp() < deadline
        ):
            Event().wait(0.01)
        assert usage_repository.freeze_calls >= 2
    finally:
        controller.release("cloud", "usage:stale")
        dispatcher.stop(timeout=1)
        executor.shutdown(wait=True)
