from concurrent.futures import ThreadPoolExecutor
from threading import Event

from video_transcript_api.transcriber.submission_guard import CloudSubmissionGuard


class _CaffeinateProcess:
    def __init__(self, events):
        self.events = events

    def terminate(self):
        self.events.append("terminate")

    def wait(self, timeout):
        self.events.append(("wait", timeout))


def test_macos_submission_guard_prevents_sleep_and_releases_assertion():
    events = []

    def start_process(command):
        events.append(command)
        return _CaffeinateProcess(events)

    guard = CloudSubmissionGuard(
        platform="darwin",
        process_factory=start_process,
    )

    with guard.hold():
        events.append("inside")

    assert events == [
        ("caffeinate", "-i"),
        "inside",
        "terminate",
        ("wait", 1),
    ]


def test_submission_guard_serializes_local_upload_stage():
    guard = CloudSubmissionGuard(platform="linux")
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def first():
        with guard.hold():
            first_entered.set()
            release_first.wait(timeout=1)

    def second():
        with guard.hold():
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first)
        assert first_entered.wait(timeout=1)
        second_future = executor.submit(second)
        assert not second_entered.wait(timeout=0.05)
        release_first.set()
        assert second_entered.wait(timeout=1)
        first_future.result()
        second_future.result()
