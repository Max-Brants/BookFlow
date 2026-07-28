"""Small, synchronous application worker for durable request_process jobs.

The scheduler deliberately does not create a thread or contact providers itself.
Callers inject the two application boundaries and invoke :meth:`run_once` from
their process worker.  This keeps restart recovery and job handling deterministic
in both production and tests.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from bookflow.core.durable_jobs import DurableJob, DurableJobService, LeaseLostError

SEARCH_REQUEST = "search_request"
START_ATTEMPT = "start_attempt"
RETRY_ATTEMPT = "retry_attempt"
_MONITORED_STATUSES = ("queued", "waiting_for_release", "retry_scheduled")


class SearchCallback(Protocol):
    def __call__(
        self, request_process_id: int, *, search_run_id: int | None = None
    ) -> Mapping[str, Any] | None: ...


AttemptCallback = Callable[[int], Any]
JobCallback = Callable[[dict[str, Any]], Any]
ScheduleCallback = Callable[[datetime], int]


@dataclass(frozen=True, slots=True)
class SchedulerRun:
    """Counters from one synchronous scheduler pass."""

    reconciled_leases: int
    monitored_enqueued: int
    completed_jobs: int
    failed_jobs: int


class RequestScheduler:
    """Bridge request_process persistence to :class:`DurableJobService`.

    ``search_request`` must return the public, secret-free result of a
    search, including ``accepted_count`` and optionally ``search_run_id``.
    Successful candidates cause a durable start-attempt job; zero candidates
    enter monitored waiting and are rediscovered at ``next_search_at``.
    """

    def __init__(
        self,
        database_path: str,
        *,
        jobs: DurableJobService,
        worker_id: str,
        search_request: SearchCallback,
        start_attempt: AttemptCallback,
        lease_duration: timedelta = timedelta(minutes=2),
        monitor_interval: timedelta = timedelta(hours=6),
        job_handlers: Mapping[str, JobCallback] | None = None,
        schedule_external_jobs: ScheduleCallback | None = None,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if lease_duration <= timedelta():
            raise ValueError("lease_duration must be positive")
        if monitor_interval <= timedelta():
            raise ValueError("monitor_interval must be positive")
        self._database_path = database_path
        self._jobs = jobs
        self._worker_id = worker_id
        self._search_request = search_request
        self._start_attempt = start_attempt
        self._lease_duration = lease_duration
        self._monitor_interval = monitor_interval
        self._job_handlers = dict(job_handlers or {})
        self._schedule_external_jobs = schedule_external_jobs

    def set_job_handler(self, job_type: str, callback: JobCallback | None) -> None:
        if callback is None:
            self._job_handlers.pop(job_type, None)
        else:
            self._job_handlers[job_type] = callback

    def set_external_scheduler(self, callback: ScheduleCallback | None) -> None:
        self._schedule_external_jobs = callback

    def recover_and_schedule(self, *, now: datetime | None = None) -> tuple[int, int]:
        """Recover abandoned leases and enqueue every monitored due search."""
        current = _as_utc(now) if now is not None else _utc_now()
        scheduled = self.schedule_due_monitored_request_processes(now=current)
        if self._schedule_external_jobs is not None:
            scheduled += self._schedule_external_jobs(current)
        return self._jobs.reconcile_expired_leases(now=current), scheduled

    def schedule_due_monitored_request_processes(self, *, now: datetime | None = None) -> int:
        """Durably enqueue each monitored request_process whose search time arrived."""
        current = _as_utc(now) if now is not None else _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, status, next_search_at
                FROM request_processes
                WHERE monitoring_enabled = 1
                  AND next_search_at IS NOT NULL
                  AND status IN (?, ?, ?)
                ORDER BY next_search_at, id
                """,
                _MONITORED_STATUSES,
            ).fetchall()

        enqueued = 0
        for row in rows:
            due_at = _database_time(str(row["next_search_at"]))
            if due_at > current:
                continue
            request_process_id = int(row["id"])
            if str(row["status"]) == "queued":
                job_key = f"search-request:{request_process_id}"
            else:
                job_key = f"search-request:{request_process_id}:{_job_time_key(due_at)}"
            self._jobs.enqueue(
                job_key=job_key,
                job_type=SEARCH_REQUEST,
                payload={"request_process_id": request_process_id},
                run_at=current,
            )
            enqueued += 1
        return enqueued

    def enqueue_attempt(
        self,
        request_process_id: int,
        *,
        search_run_id: int | None = None,
        retry: bool = False,
        retry_number: int | None = None,
        run_at: datetime | None = None,
    ) -> DurableJob:
        """Create one idempotent start or retry attempt job for an request_process."""
        if request_process_id < 1:
            raise ValueError("request_process_id must be positive")
        if retry_number is not None and (not retry or retry_number < 1):
            raise ValueError("retry_number requires a positive retry attempt")
        job_type = RETRY_ATTEMPT if retry else START_ATTEMPT
        suffix = f":{search_run_id}" if search_run_id is not None else ""
        if retry_number is not None:
            suffix += f":retry:{retry_number}"
        return self._jobs.enqueue(
            job_key=f"{job_type.replace('_', '-')}:{request_process_id}{suffix}",
            job_type=job_type,
            payload={"request_process_id": request_process_id},
            run_at=run_at,
        )

    def run_once(self, *, now: datetime | None = None, limit: int = 10) -> SchedulerRun:
        """Run at most ``limit`` currently due jobs in the caller's thread."""
        if limit < 1:
            raise ValueError("limit must be positive")
        current = _as_utc(now) if now is not None else _utc_now()
        reconciled, monitored = self.recover_and_schedule(now=current)
        claimed = self._jobs.claim_due(
            worker_id=self._worker_id,
            lease_duration=self._lease_duration,
            limit=limit,
            now=current,
        )
        completed = 0
        failed = 0
        for job in claimed:
            try:
                self._process(job, now=current)
                self._jobs.complete(job_id=job.id, worker_id=self._worker_id, now=current)
                completed += 1
            except LeaseLostError:
                # Another process recovered the job; it is no longer ours to fail.
                continue
            except Exception as exc:  # noqa: BLE001 - durable failure records callback errors
                try:
                    self._jobs.fail(
                        job_id=job.id,
                        worker_id=self._worker_id,
                        error=_error_summary(exc),
                        now=current,
                    )
                except LeaseLostError:
                    continue
                failed += 1
        return SchedulerRun(reconciled, monitored, completed, failed)

    def _process(self, job: DurableJob, *, now: datetime) -> None:
        external = self._job_handlers.get(job.job_type)
        if external is not None:
            external(job.payload)
            return
        request_process_id = _request_process_id(job)
        if job.job_type == SEARCH_REQUEST:
            interactive = job.payload.get("interactive", False)
            if not isinstance(interactive, bool):
                raise ValueError("interactive must be a boolean")
            queued_run_id = job.payload.get("search_run_id")
            if queued_run_id is not None and (
                isinstance(queued_run_id, bool)
                or not isinstance(queued_run_id, int)
                or queued_run_id < 1
            ):
                raise ValueError("search_run_id must be a positive integer")
            try:
                result = (
                    self._search_request(request_process_id, search_run_id=queued_run_id)
                    if queued_run_id is not None
                    else self._search_request(request_process_id)
                ) or {}
            except Exception as exc:
                if queued_run_id is not None:
                    self._fail_search_run(request_process_id, queued_run_id, exc, now=now)
                raise
            accepted_count = result.get("accepted_count", 0)
            if not isinstance(accepted_count, int) or accepted_count < 0:
                raise ValueError("search result accepted_count must be a non-negative integer")
            if accepted_count:
                search_run_id = result.get("search_run_id")
                if search_run_id is not None and (
                    not isinstance(search_run_id, int) or search_run_id < 1
                ):
                    raise ValueError("search result search_run_id must be a positive integer")
                if interactive:
                    self._mark_interactive_ready(request_process_id, now=now)
                else:
                    self.enqueue_attempt(
                        request_process_id, search_run_id=search_run_id, run_at=now
                    )
            else:
                if interactive:
                    self._mark_interactive_ready(request_process_id, now=now)
                else:
                    self._mark_waiting_for_release(request_process_id, now=now)
            return
        if job.job_type in {START_ATTEMPT, RETRY_ATTEMPT}:
            self._start_attempt(request_process_id)
            return
        raise ValueError(f"unsupported request_process job type: {job.job_type}")

    def _mark_waiting_for_release(self, request_process_id: int, *, now: datetime) -> None:
        next_search = now + self._monitor_interval
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE request_processes
                SET status = 'waiting_for_release', next_search_at = ?, updated_at = ?
                WHERE id = ?
                  AND status NOT IN ('completed', 'cancelled', 'failed')
                """,
                (_encode(next_search), _encode(now), request_process_id),
            )

    def _mark_interactive_ready(self, request_process_id: int, *, now: datetime) -> None:
        """Leave results awaiting an admin choice without disabling monitoring."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT monitoring_enabled FROM request_processes WHERE id=?", (request_process_id,)
            ).fetchone()
            if row is None:
                return
            next_search = now + self._monitor_interval if bool(row["monitoring_enabled"]) else None
            connection.execute(
                """UPDATE request_processes SET status='waiting_for_release', next_search_at=?,
                   updated_at=? WHERE id=?""",
                (_encode(next_search) if next_search else None, _encode(now), request_process_id),
            )

    def _fail_search_run(
        self, request_process_id: int, search_run_id: int, error: Exception, *, now: datetime
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE request_search_runs SET status='failed', completed_at=?,
                   errors_json=? WHERE id=? AND request_process_id=? AND status='running'""",
                (
                    _encode(now),
                    json.dumps({"scheduler": type(error).__name__}),
                    search_run_id,
                    request_process_id,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection


def _request_process_id(job: DurableJob) -> int:
    value = job.payload.get("request_process_id")
    if not isinstance(value, int) or value < 1:
        raise ValueError("job payload requires a positive integer request_process_id")
    return value


def _database_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _job_time_key(value: datetime) -> str:
    return _as_utc(value).strftime("%Y%m%dT%H%M%S%fZ")


def _error_summary(error: Exception) -> str:
    detail = str(error).strip().replace("\n", " ")
    return f"{type(error).__name__}: {detail}"[:500]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _encode(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds")
