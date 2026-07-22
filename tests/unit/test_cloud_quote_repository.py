from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from video_transcript_api.transcriber.cloud_quote_repository import (
    CloudQuoteConflict,
    CloudQuoteRepository,
    NewCloudQuote,
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 7, 21, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def repository(tmp_path):
    clock = Clock()
    repo = CloudQuoteRepository(tmp_path / "quotes.db", clock=clock)
    return repo, clock


def new_quote() -> NewCloudQuote:
    return NewCloudQuote(
        task_id="task-1",
        media_ref="retained/task-1/audio.m4a",
        media_sha256="a" * 64,
        duration_seconds=Decimal("15.01"),
        billable_seconds=16,
        model="fun-asr-2025-11-07",
        unit_price=Decimal("0.00022"),
        max_cost=Decimal("0.00352"),
    )


def test_quote_uses_canonical_decimal_strings_and_expires(repository):
    repo, clock = repository
    quote = repo.create(new_quote(), token="secret-token")

    assert quote.max_cost == Decimal("0.00352")
    assert quote.status == "pending"
    assert quote.token == "secret-token"

    clock.now += timedelta(minutes=31)
    assert repo.get("task-1").status == "refresh_required"


def test_confirmation_is_idempotently_queued_without_plaintext_token(repository):
    repo, clock = repository
    repo.create(new_quote(), token="secret-token")

    first, created = repo.confirm_and_queue(
        "task-1", "secret-token", Decimal("0.00352")
    )
    duplicate, duplicate_created = repo.confirm_and_queue(
        "task-1", "secret-token", Decimal("0.00352")
    )

    assert created is True
    assert duplicate_created is False
    assert first.status == duplicate.status == "confirmed_queued"
    assert repo.list_confirmed_queued() == ["task-1"]
    with sqlite3.connect(repo.db_path) as connection:
        stored = connection.execute(
            "SELECT token_hash FROM cloud_quotes WHERE task_id='task-1'"
        ).fetchone()[0]
    assert stored != "secret-token"


def test_cancel_removes_confirmed_quote_from_cloud_dispatch_queue(repository):
    repo, _ = repository
    repo.create(new_quote(), token="secret-token")
    repo.confirm_and_queue("task-1", "secret-token", Decimal("0.00352"))

    assert repo.cancel("task-1") is True
    assert repo.get("task-1").status == "canceled"
    assert repo.list_confirmed_queued() == []
    with pytest.raises(CloudQuoteConflict, match="quote_not_queued"):
        repo.claim_queued("task-1", "worker-1")


def test_dispatch_claim_requeues_once_after_lease_expiry(repository):
    repo, clock = repository
    repo.create(new_quote(), token="secret-token")
    repo.confirm_and_queue("task-1", "secret-token", Decimal("0.00352"))

    claimed = repo.claim_queued("task-1", "worker-1")

    assert claimed.status == "confirming"
    assert claimed.lease_owner == "worker-1"
    assert repo.next_lease_expiry() == clock.now + timedelta(seconds=60)
    assert repo.requeue_expired_leases() == []

    clock.now += timedelta(seconds=61)
    assert repo.requeue_expired_leases() == ["task-1"]
    assert repo.requeue_expired_leases() == []
    assert repo.list_confirmed_queued() == ["task-1"]


def test_refresh_invalidates_old_token(repository):
    repo, clock = repository
    repo.create(new_quote(), token="old-token")
    clock.now += timedelta(minutes=31)

    refreshed = repo.refresh(new_quote(), old_token="old-token", new_token="new-token")

    assert refreshed.token == "new-token"
    with pytest.raises(CloudQuoteConflict):
        repo.confirm_and_queue("task-1", "old-token", Decimal("0.00352"))


def test_existing_attempt_reconciles_quote_to_consumed(repository):
    repo, _ = repository
    repo.create(new_quote(), token="secret-token")
    repo.confirm_and_queue("task-1", "secret-token", Decimal("0.00352"))
    repo.claim_queued("task-1", "worker")

    consumed = repo.mark_consumed("task-1", attempt_no=1)

    assert consumed.status == "consumed"
    assert consumed.attempt_no == 1


def test_local_fallback_never_claims_cloud(repository):
    repo, clock = repository
    repo.create(new_quote(), token="secret-token")

    selected, acquired = repo.claim_local(
        "task-1", "local-1", now=clock.now
    )
    duplicate, duplicate_acquired = repo.claim_local(
        "task-1", "local-2", now=clock.now
    )

    assert acquired is True
    assert duplicate_acquired is False
    assert selected.status == "local_selected"
    assert duplicate.media_ref == selected.media_ref
    assert selected.lease_expires_at == clock.now + timedelta(seconds=3700)
    with pytest.raises(CloudQuoteConflict):
        repo.confirm_and_queue("task-1", "secret-token", Decimal("0.00352"))

    assert repo.release_local_queue("task-1", "local-1") is True
    retried, retry_acquired = repo.claim_local(
        "task-1", "local-3", now=clock.now
    )
    assert retry_acquired is True
    assert retried.media_ref == selected.media_ref
    repo.mark_local_queued("task-1", "local-3", now=clock.now)

    assert repo.reset_stale_local_queued(
        ["task-1"], created_before=clock.now + timedelta(seconds=1)
    ) == ["task-1"]
    assert repo.get("task-1").status == "local_selected"


def test_stale_unconfirmed_quote_expires_after_twenty_four_hours(repository):
    repo, clock = repository
    repo.create(new_quote(), token="secret-token")
    repo.confirm_and_queue("task-1", "secret-token", Decimal("0.00352"))
    clock.now += timedelta(hours=24, seconds=1)

    assert repo.expire_stale_unconfirmed() == ["task-1"]
    assert repo.get("task-1").status == "expired"
