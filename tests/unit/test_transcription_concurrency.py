import threading

import pytest

from video_transcript_api.transcriber.concurrency import (
    ConcurrencyLimitError,
    TranscriptionConcurrencyController,
    resolve_transcription_limits,
)


def test_defaults_and_lower_trusted_hard_limit_are_fail_closed():
    defaults = resolve_transcription_limits({"concurrent": {}})
    assert (defaults.local_soft, defaults.local_hard) == (1, 2)
    assert (defaults.cloud_soft, defaults.cloud_hard) == (3, 10)

    lowered = resolve_transcription_limits(
        {
            "concurrent": {
                "cloud_asr_hard_limit": 2,
                "cloud_asr_workers": 8,
            }
        }
    )
    assert (lowered.cloud_soft, lowered.cloud_hard) == (2, 2)


def test_invalid_trusted_hard_limit_warns_without_echoing_value():
    warnings = []

    limits = resolve_transcription_limits(
        {"concurrent": {"cloud_asr_hard_limit": True}},
        warn=warnings.append,
    )

    assert (limits.cloud_soft, limits.cloud_hard) == (1, 1)
    assert warnings == ["Invalid cloud ASR hard limit; using fail-closed value"]
    assert "True" not in warnings[0]


def test_local_waiter_does_not_block_cloud_and_raise_wakes_it():
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    assert controller.acquire("local", "local-1") is True

    entered = threading.Event()

    def wait_for_local_slot():
        if controller.acquire("local", "local-2"):
            entered.set()

    waiter = threading.Thread(target=wait_for_local_slot)
    waiter.start()
    assert entered.wait(0.05) is False
    assert controller.acquire("cloud", "cloud-1") is True

    controller.update_soft_limits(local=2)
    assert entered.wait(1) is True
    waiter.join(timeout=1)
    assert not waiter.is_alive()


def test_lowering_and_recovered_slots_drain_without_new_cloud_entry():
    controller = TranscriptionConcurrencyController(local=1, cloud=3)
    for index in range(3):
        controller.reserve_recovered_cloud(f"usage:{index}")

    controller.update_soft_limits(cloud=1)
    entered = threading.Event()

    def wait_for_cloud_slot():
        if controller.acquire("cloud", "continuation:new"):
            entered.set()

    waiter = threading.Thread(target=wait_for_cloud_slot)
    waiter.start()
    controller.release("cloud", "usage:0")
    controller.release("cloud", "usage:1")
    assert entered.wait(0.05) is False
    controller.release("cloud", "usage:2")
    assert entered.wait(1) is True
    waiter.join(timeout=1)


def test_owner_transfer_keeps_count_and_cancel_wakes_waiter():
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    assert controller.acquire("cloud", "continuation:task") is True
    controller.transfer_cloud_owner("continuation:task", "usage:event")
    assert controller.snapshot()["cloud_active"] == 1

    canceled = threading.Event()
    result = []

    def wait_for_cloud_slot():
        result.append(
            controller.acquire(
                "cloud", "continuation:second", cancelled=canceled.is_set
            )
        )

    waiter = threading.Thread(target=wait_for_cloud_slot)
    waiter.start()
    canceled.set()
    controller.wake_waiters()
    waiter.join(timeout=1)

    assert result == [False]
    assert controller.snapshot()["cloud_active"] == 1


@pytest.mark.parametrize("value", [True, 0, -1, 3])
def test_user_local_limit_rejects_invalid_or_over_hard_values(value):
    controller = TranscriptionConcurrencyController(local=1, cloud=1)
    with pytest.raises(ConcurrencyLimitError):
        controller.update_soft_limits(local=value)
