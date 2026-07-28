"""Thread-safe runtime limits for local and cloud ASR providers."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping


LOCAL_ASR_HARD_LIMIT = 3
DEFAULT_CLOUD_ASR_HARD_LIMIT = 10
MAX_CLOUD_ASR_HARD_LIMIT = 10

Strategy = Literal["local", "cloud"]


class ConcurrencyLimitError(ValueError):
    """A user-provided ASR concurrency value is outside trusted limits."""


@dataclass(frozen=True)
class TranscriptionLimits:
    local_soft: int
    local_hard: int
    cloud_soft: int
    cloud_hard: int


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def resolve_transcription_limits(
    config: Mapping[str, Any],
    *,
    warn: Callable[[str], None] | None = None,
) -> TranscriptionLimits:
    """Resolve trusted hard limits before fail-closed runtime soft limits."""
    concurrent = config.get("concurrent", {})
    if not isinstance(concurrent, Mapping):
        concurrent = {}

    cloud_hard = concurrent.get(
        "cloud_asr_hard_limit", DEFAULT_CLOUD_ASR_HARD_LIMIT
    )
    if not _is_int(cloud_hard) or not 1 <= cloud_hard <= MAX_CLOUD_ASR_HARD_LIMIT:
        cloud_hard = 1
        if warn is not None:
            warn("Invalid cloud ASR hard limit; using fail-closed value")

    local_soft = concurrent.get("local_asr_workers", 1)
    if not _is_int(local_soft) or local_soft < 1:
        local_soft = 1
    if local_soft > LOCAL_ASR_HARD_LIMIT:
        local_soft = LOCAL_ASR_HARD_LIMIT
        if warn is not None:
            warn("Local ASR concurrency exceeds hard limit; using safe value")

    cloud_soft = concurrent.get("cloud_asr_workers", min(3, cloud_hard))
    if not _is_int(cloud_soft) or cloud_soft < 1:
        cloud_soft = min(3, cloud_hard)
    if cloud_soft > cloud_hard:
        cloud_soft = cloud_hard
        if warn is not None:
            warn("Cloud ASR concurrency exceeds hard limit; using safe value")

    return TranscriptionLimits(
        local_soft=local_soft,
        local_hard=LOCAL_ASR_HARD_LIMIT,
        cloud_soft=cloud_soft,
        cloud_hard=cloud_hard,
    )


class TranscriptionConcurrencyController:
    """Own active ASR slots and adjust soft limits without replacing locks."""

    def __init__(
        self,
        *,
        local: int,
        cloud: int,
        local_hard: int = LOCAL_ASR_HARD_LIMIT,
        cloud_hard: int = DEFAULT_CLOUD_ASR_HARD_LIMIT,
    ) -> None:
        self._condition = threading.Condition()
        self._local_hard = local_hard
        self._cloud_hard = cloud_hard
        self._validate_limit("local", local)
        self._validate_limit("cloud", cloud)
        self._local_limit = local
        self._cloud_limit = cloud
        self._local_owners: set[str] = set()
        self._cloud_owners: set[str] = set()

    def _validate_limit(self, strategy: Strategy, value: int) -> None:
        hard = self._local_hard if strategy == "local" else self._cloud_hard
        if not _is_int(value) or value < 1 or value > hard:
            raise ConcurrencyLimitError(f"invalid_{strategy}_asr_limit")

    def _state(self, strategy: Strategy) -> tuple[set[str], int]:
        if strategy == "local":
            return self._local_owners, self._local_limit
        if strategy == "cloud":
            return self._cloud_owners, self._cloud_limit
        raise ConcurrencyLimitError("unknown_asr_strategy")

    def snapshot(self) -> dict[str, int]:
        with self._condition:
            return {
                "local_asr_workers": self._local_limit,
                "cloud_asr_workers": self._cloud_limit,
                "local_asr_hard_limit": self._local_hard,
                "cloud_asr_hard_limit": self._cloud_hard,
                "local_active": len(self._local_owners),
                "cloud_active": len(self._cloud_owners),
            }

    def update_soft_limits(
        self, *, local: int | None = None, cloud: int | None = None
    ) -> None:
        with self._condition:
            if local is not None:
                self._validate_limit("local", local)
            if cloud is not None:
                self._validate_limit("cloud", cloud)
            if local is not None:
                self._local_limit = local
            if cloud is not None:
                self._cloud_limit = cloud
            self._condition.notify_all()

    def acquire(
        self,
        strategy: Strategy,
        owner: str,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        if not isinstance(owner, str) or not owner:
            raise ConcurrencyLimitError("invalid_asr_slot_owner")
        with self._condition:
            owners, _ = self._state(strategy)
            if owner in owners:
                return True
            while True:
                if cancelled is not None and cancelled():
                    return False
                owners, limit = self._state(strategy)
                if len(owners) < limit:
                    owners.add(owner)
                    return True
                self._condition.wait()

    def try_acquire(self, strategy: Strategy, owner: str) -> bool:
        """Acquire immediately, returning false when the soft limit is full."""
        if not isinstance(owner, str) or not owner:
            raise ConcurrencyLimitError("invalid_asr_slot_owner")
        with self._condition:
            owners, limit = self._state(strategy)
            if owner in owners:
                return True
            if len(owners) >= limit:
                return False
            owners.add(owner)
            return True

    def reserve_recovered_cloud(self, owner: str) -> None:
        if not isinstance(owner, str) or not owner:
            raise ConcurrencyLimitError("invalid_asr_slot_owner")
        with self._condition:
            self._cloud_owners.add(owner)

    def cancel_if_not_active(
        self,
        strategy: Strategy,
        *,
        owner_prefix: str,
        on_cancel: Callable[[], None],
    ) -> bool:
        """Cancel queued work only when no matching owner has acquired a slot."""
        if not isinstance(owner_prefix, str) or not owner_prefix:
            raise ConcurrencyLimitError("invalid_asr_slot_owner_prefix")
        with self._condition:
            owners, _ = self._state(strategy)
            if any(owner.startswith(owner_prefix) for owner in owners):
                return False
            on_cancel()
            self._condition.notify_all()
            return True

    def transfer_cloud_owner(self, old_owner: str, new_owner: str) -> None:
        if not new_owner:
            raise ConcurrencyLimitError("invalid_asr_slot_owner")
        with self._condition:
            if old_owner == new_owner and old_owner in self._cloud_owners:
                return
            if old_owner not in self._cloud_owners:
                if new_owner in self._cloud_owners:
                    return
                raise ConcurrencyLimitError("unknown_cloud_slot_owner")
            if new_owner in self._cloud_owners:
                raise ConcurrencyLimitError("duplicate_cloud_slot_owner")
            self._cloud_owners.remove(old_owner)
            self._cloud_owners.add(new_owner)

    def release(self, strategy: Strategy, owner: str) -> None:
        with self._condition:
            owners, _ = self._state(strategy)
            if owner not in owners:
                raise ConcurrencyLimitError("unknown_asr_slot_owner")
            owners.remove(owner)
            self._condition.notify_all()

    def wake_waiters(self) -> None:
        with self._condition:
            self._condition.notify_all()
