"""Focused tests for synchronous durable request_process scheduling."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bookflow.core.durable_jobs import DurableJobService, JobStatus
from bookflow.core.request_scheduler import RequestScheduler
from bookflow.core.user_db import UserDB


def _seed_request_process(database_path: Path, *, status: str, next_search_at: datetime) -> int:
    users = UserDB(str(database_path))
    users.initialize()
    with sqlite3.connect(database_path) as connection:
        book_id = connection.execute(
            "INSERT INTO books (metadata_provider, provider_book_id, title) VALUES ('test', '1', 'Book')"
        ).lastrowid
        cursor = connection.execute(
            """
            INSERT INTO request_processes (
                book_id, content_type, profile_hash, profile_snapshot_json, status,
                monitoring_enabled, next_search_at
            ) VALUES (?, 'ebook', ?, '{}', ?, 1, ?)
            """,
            (book_id, "a" * 64, status, next_search_at.isoformat()),
        )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _scheduler(
    database_path: Path,
    jobs: DurableJobService,
    *,
    searched: list[int],
    attempted: list[int],
    results: list[dict[str, int]],
) -> RequestScheduler:
    def search(request_process_id: int, **_kwargs: object) -> dict[str, int]:
        searched.append(request_process_id)
        return results.pop(0)

    def attempt(request_process_id: int) -> None:
        attempted.append(request_process_id)

    return RequestScheduler(
        str(database_path),
        jobs=jobs,
        worker_id="test-worker",
        search_request=search,
        start_attempt=attempt,
        monitor_interval=timedelta(hours=1),
    )


def test_restart_no_result_then_later_success_starts_an_attempt(tmp_path: Path) -> None:
    now = datetime(2031, 1, 2, 3, 4, 5, tzinfo=UTC)
    database_path = tmp_path / "users.db"
    request_process_id = _seed_request_process(
        database_path, status="waiting_for_release", next_search_at=now
    )
    jobs = DurableJobService(database_path)
    searched: list[int] = []
    attempted: list[int] = []
    first = _scheduler(
        database_path,
        jobs,
        searched=searched,
        attempted=attempted,
        results=[{"search_run_id": 1, "accepted_count": 0}],
    )

    first_run = first.run_once(now=now)
    assert first_run.completed_jobs == 1
    assert searched == [request_process_id]
    with sqlite3.connect(database_path) as connection:
        state = connection.execute(
            "SELECT status, next_search_at FROM request_processes WHERE id = ?",
            (request_process_id,),
        ).fetchone()
    assert state is not None
    assert state[0] == "waiting_for_release"
    assert datetime.fromisoformat(state[1]) == now + timedelta(hours=1)

    restarted = _scheduler(
        database_path,
        DurableJobService(database_path),
        searched=searched,
        attempted=attempted,
        results=[{"search_run_id": 2, "accepted_count": 1}],
    )
    second_run = restarted.run_once(now=now + timedelta(hours=1))
    assert second_run.completed_jobs == 1
    assert searched == [request_process_id, request_process_id]

    attempt_run = restarted.run_once(now=now + timedelta(hours=1))
    assert attempt_run.completed_jobs == 1
    assert attempted == [request_process_id]


def test_startup_reclaims_expired_lease_and_worker_completes_job(tmp_path: Path) -> None:
    now = datetime(2031, 2, 3, 4, 5, 6, tzinfo=UTC)
    database_path = tmp_path / "users.db"
    request_process_id = _seed_request_process(
        database_path, status="downloading", next_search_at=now
    )
    jobs = DurableJobService(database_path)
    job = jobs.enqueue(
        job_key="retry-attempt:1",
        job_type="retry_attempt",
        payload={"request_process_id": request_process_id},
        run_at=now,
    )
    jobs.claim_due(worker_id="crashed", lease_duration=timedelta(minutes=1), now=now)
    attempted: list[int] = []
    scheduler = _scheduler(
        database_path,
        jobs,
        searched=[],
        attempted=attempted,
        results=[],
    )

    run = scheduler.run_once(now=now + timedelta(minutes=1))

    assert run.reconciled_leases == 1
    assert run.completed_jobs == 1
    assert attempted == [request_process_id]
    completed = jobs.get(job.id)
    assert completed is not None and completed.status is JobStatus.COMPLETED


def test_interactive_search_never_enqueues_an_attempt(tmp_path: Path) -> None:
    now = datetime(2031, 3, 4, tzinfo=UTC)
    database_path = tmp_path / "users.db"
    request_process_id = _seed_request_process(database_path, status="queued", next_search_at=now)
    jobs = DurableJobService(database_path)
    jobs.enqueue(
        job_key="search-request:interactive:1",
        job_type="search_request",
        payload={"request_process_id": request_process_id, "search_run_id": 7, "interactive": True},
        run_at=now,
    )
    attempted: list[int] = []
    scheduler = _scheduler(
        database_path,
        jobs,
        searched=[],
        attempted=attempted,
        results=[{"search_run_id": 7, "accepted_count": 1}],
    )

    run = scheduler.run_once(now=now)

    assert run.completed_jobs == 1
    assert attempted == []
    with sqlite3.connect(database_path) as connection:
        status, monitoring_enabled, next_search_at = connection.execute(
            "SELECT status, monitoring_enabled, next_search_at FROM request_processes WHERE id=?",
            (request_process_id,),
        ).fetchone()
    assert status == "waiting_for_release" and monitoring_enabled == 1
    assert datetime.fromisoformat(next_search_at) == now + timedelta(hours=1)


def test_interactive_search_failure_marks_reserved_run_terminal(tmp_path: Path) -> None:
    now = datetime(2031, 3, 5, tzinfo=UTC)
    database_path = tmp_path / "users.db"
    request_process_id = _seed_request_process(database_path, status="queued", next_search_at=now)
    with sqlite3.connect(database_path) as connection:
        search_run_id = connection.execute(
            "INSERT INTO request_search_runs(request_process_id,status,source_count) VALUES (?, 'running', 0)",
            (request_process_id,),
        ).lastrowid
    assert search_run_id is not None
    jobs = DurableJobService(database_path)
    jobs.enqueue(
        job_key="search-request:interactive-failure",
        job_type="search_request",
        payload={
            "request_process_id": request_process_id,
            "search_run_id": search_run_id,
            "interactive": True,
        },
        run_at=now,
    )
    scheduler = RequestScheduler(
        str(database_path),
        jobs=jobs,
        worker_id="test-worker",
        search_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("source failed")
        ),
        start_attempt=lambda _request_process_id: None,
    )

    run = scheduler.run_once(now=now)

    assert run.failed_jobs >= 1
    with sqlite3.connect(database_path) as connection:
        status, completed_at, errors = connection.execute(
            "SELECT status, completed_at, errors_json FROM request_search_runs WHERE id=?",
            (search_run_id,),
        ).fetchone()
    assert status == "failed" and completed_at is not None and "RuntimeError" in errors
