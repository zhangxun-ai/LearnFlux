from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from video_transcript_api.api.services.asr_continuations import (
    MediaCleanupOwnership,
    submit_local_asr_continuation,
)
from video_transcript_api.transcriber.concurrency import (
    TranscriptionConcurrencyController,
)


def _media(tmp_path: Path, name: str) -> MediaCleanupOwnership:
    path = tmp_path / name
    path.write_bytes(b"audio")
    return MediaCleanupOwnership((path,))


def test_waiting_local_continuation_keeps_media_then_cleans_once(tmp_path):
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    controller.acquire("local", "blocker")
    media = _media(tmp_path, "waiting.wav")
    provider_called = Event()
    completed = Event()

    with ThreadPoolExecutor(max_workers=2) as asr_executor, ThreadPoolExecutor(
        max_workers=1
    ) as post_executor:
        future = submit_local_asr_continuation(
            task_id="task-1",
            run_provider=lambda: provider_called.set() or "raw",
            after_provider=lambda result: result.upper(),
            media=media,
            controller=controller,
            asr_executor=asr_executor,
            post_executor=post_executor,
            on_result=lambda result: completed.set(),
            on_failure=lambda exc: None,
        )

        assert media.paths[0].exists()
        assert not provider_called.wait(timeout=0.05)
        controller.release("local", "blocker")
        assert completed.wait(timeout=1)
        future.result(timeout=1)

    assert not media.paths[0].exists()


def test_post_asr_does_not_hold_local_provider_slot_or_worker(tmp_path):
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    first_post_started = Event()
    release_first_post = Event()
    second_provider_started = Event()
    both_done = Event()
    results = []

    def after_first(result):
        first_post_started.set()
        release_first_post.wait(timeout=2)
        return result

    def on_result(result):
        results.append(result)
        if len(results) == 2:
            both_done.set()

    with ThreadPoolExecutor(max_workers=2) as asr_executor, ThreadPoolExecutor(
        max_workers=2
    ) as post_executor:
        submit_local_asr_continuation(
            task_id="task-1",
            run_provider=lambda: "first",
            after_provider=after_first,
            media=_media(tmp_path, "first.wav"),
            controller=controller,
            asr_executor=asr_executor,
            post_executor=post_executor,
            on_result=on_result,
            on_failure=lambda exc: None,
        )
        assert first_post_started.wait(timeout=1)
        submit_local_asr_continuation(
            task_id="task-2",
            run_provider=lambda: second_provider_started.set() or "second",
            after_provider=lambda result: result,
            media=_media(tmp_path, "second.wav"),
            controller=controller,
            asr_executor=asr_executor,
            post_executor=post_executor,
            on_result=on_result,
            on_failure=lambda exc: None,
        )

        assert second_provider_started.wait(timeout=1)
        release_first_post.set()
        assert both_done.wait(timeout=1)


def test_cancelled_waiter_never_runs_provider_and_cleans_media(tmp_path):
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    controller.acquire("local", "blocker")
    cancelled = Event()
    failed = Event()
    provider_called = Event()
    media = _media(tmp_path, "cancelled.wav")

    with ThreadPoolExecutor(max_workers=1) as asr_executor, ThreadPoolExecutor(
        max_workers=1
    ) as post_executor:
        future = submit_local_asr_continuation(
            task_id="task-1",
            run_provider=lambda: provider_called.set(),
            after_provider=lambda result: result,
            media=media,
            controller=controller,
            asr_executor=asr_executor,
            post_executor=post_executor,
            on_result=lambda result: None,
            on_failure=lambda exc: failed.set(),
            cancelled=cancelled.is_set,
        )
        cancelled.set()
        controller.wake_waiters()
        future.result(timeout=1)

    controller.release("local", "blocker")
    assert failed.is_set()
    assert not provider_called.is_set()
    assert not media.paths[0].exists()
