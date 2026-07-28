"""SQLite integration tests for durable background-job coordination."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bookflow.core.durable_jobs import (
    BACKGROUND_JOBS_TABLE_SQL,
    DurableJobService,
    JobStatus,
    LeaseLostError,
    retry_backoff,
)


@pytest.fixture
def service(tmp_path: Path) -> DurableJobService:
    durable_jobs = DurableJobService(tmp_path / "durable-jobs.sqlite")
    durable_jobs.create_schema()
    return durable_jobs


@pytest.fixture
def now() -> datetime:
    return datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_schema_constant_can_be_applied_by_a_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(BACKGROUND_JOBS_TABLE_SQL)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(background_jobs)")}

    assert {"job_key", "status", "attempt_count", "lease_expires_at"} <= columns


def test_enqueue_is_idempotent_and_preserves_the_original_job(
    service: DurableJobService, now: datetime
) -> None:
    first = service.enqueue(
        job_key="request:123",
        job_type="acquire_request",
        payload={"request_id": 123},
        run_at=now,
        max_attempts=2,
    )
    repeated = service.enqueue(
        job_key="request:123",
        job_type="other_work",
        payload={"request_id": 999},
        run_at=now + timedelta(days=1),
    )

    assert repeated == first
    assert repeated.payload == {"request_id": 123}
    assert repeated.max_attempts == 2


def test_claim_complete_and_heartbeat_require_the_lease_owner(
    service: DurableJobService, now: datetime
) -> None:
    enqueued = service.enqueue(job_key="acquire:1", job_type="acquire", payload={}, run_at=now)
    [claimed] = service.claim_due(
        worker_id="worker-a", lease_duration=timedelta(minutes=2), now=now
    )

    extended = service.heartbeat(
        job_id=claimed.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=4),
        now=now + timedelta(minutes=1),
    )
    assert extended.lease_expires_at == now + timedelta(minutes=5)

    with pytest.raises(LeaseLostError):
        service.complete(job_id=enqueued.id, worker_id="worker-b", now=now + timedelta(minutes=1))

    completed = service.complete(
        job_id=enqueued.id, worker_id="worker-a", now=now + timedelta(minutes=2)
    )
    assert completed.status is JobStatus.COMPLETED
    assert completed.lease_owner is None


def test_failure_retries_with_backoff_then_becomes_terminal(
    service: DurableJobService, now: datetime
) -> None:
    service.enqueue(job_key="acquire:2", job_type="acquire", payload={}, run_at=now, max_attempts=2)
    [first] = service.claim_due(worker_id="worker", lease_duration=timedelta(minutes=1), now=now)
    retry = service.fail(job_id=first.id, worker_id="worker", error="temporary", now=now)

    assert retry.status is JobStatus.QUEUED
    assert retry.run_at == now + timedelta(minutes=5)
    assert retry.last_error == "temporary"
    assert (
        service.claim_due(
            worker_id="worker", lease_duration=timedelta(minutes=1), now=now + timedelta(minutes=4)
        )
        == []
    )

    [second] = service.claim_due(
        worker_id="worker", lease_duration=timedelta(minutes=1), now=now + timedelta(minutes=5)
    )
    terminal = service.fail(
        job_id=second.id,
        worker_id="worker",
        error="permanent",
        now=now + timedelta(minutes=5),
    )

    assert terminal.status is JobStatus.FAILED
    assert terminal.attempt_count == 2
    assert (
        service.claim_due(
            worker_id="worker", lease_duration=timedelta(minutes=1), now=now + timedelta(days=1)
        )
        == []
    )


def test_startup_reconciliation_recovers_expired_lease_after_restart(
    service: DurableJobService, now: datetime
) -> None:
    job = service.enqueue(job_key="acquire:3", job_type="acquire", payload={}, run_at=now)
    [claimed] = service.claim_due(
        worker_id="crashed-worker", lease_duration=timedelta(minutes=1), now=now
    )
    restarted_service = DurableJobService(service._database_path)

    assert restarted_service.reconcile_expired_leases(now=now + timedelta(minutes=1)) == 1
    recovered = restarted_service.get(job.id)
    assert recovered is not None
    assert recovered.status is JobStatus.QUEUED
    assert recovered.lease_owner is None
    assert recovered.attempt_count == claimed.attempt_count

    [reclaimed] = restarted_service.claim_due(
        worker_id="new-worker", lease_duration=timedelta(minutes=1), now=now + timedelta(minutes=1)
    )
    assert reclaimed.lease_owner == "new-worker"
    assert reclaimed.attempt_count == 2


def test_claim_due_automatically_recovers_expired_jobs(
    service: DurableJobService, now: datetime
) -> None:
    service.enqueue(job_key="acquire:4", job_type="acquire", payload={}, run_at=now)
    [first] = service.claim_due(worker_id="old", lease_duration=timedelta(minutes=1), now=now)

    [reclaimed] = service.claim_due(
        worker_id="new", lease_duration=timedelta(minutes=1), now=now + timedelta(minutes=1)
    )
    assert reclaimed.id == first.id
    assert reclaimed.attempt_count == 2


def test_two_workers_can_claim_each_due_job_only_once(
    service: DurableJobService, now: datetime
) -> None:
    service.enqueue(job_key="acquire:5", job_type="acquire", payload={}, run_at=now)
    barrier = threading.Barrier(2)
    claimed_ids: list[int] = []
    errors: list[BaseException] = []

    def claim_as(worker_id: str) -> None:
        try:
            worker = DurableJobService(service._database_path)
            barrier.wait(timeout=5)
            claimed_ids.extend(
                job.id
                for job in worker.claim_due(
                    worker_id=worker_id, lease_duration=timedelta(minutes=1), now=now
                )
            )
        except BaseException as error:  # thread errors must surface in the test
            errors.append(error)

    workers = [threading.Thread(target=claim_as, args=(worker_id,)) for worker_id in ("a", "b")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert not errors
    assert claimed_ids == [1]


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, timedelta(minutes=5)), (2, timedelta(minutes=15)), (3, timedelta(hours=1)), (4, None)],
)
def test_retry_backoff_is_bounded(attempt: int, expected: timedelta | None) -> None:
    assert retry_backoff(attempt) == expected
