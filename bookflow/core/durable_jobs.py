"""Durable SQLite-backed background-job scheduling primitives.

The service deliberately owns no application work.  It only provides durable,
lease-based coordination that a process-local worker can use safely after a
restart or when more than one BookFlow process is running.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


BACKGROUND_JOBS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS background_jobs (
    id INTEGER PRIMARY KEY,
    job_key TEXT NOT NULL UNIQUE,
    job_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    run_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_background_jobs_due
    ON background_jobs(status, run_at, id);
CREATE INDEX IF NOT EXISTS idx_background_jobs_lease_expiry
    ON background_jobs(status, lease_expires_at);
"""


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LeaseLostError(RuntimeError):
    """Raised when a worker no longer owns an unexpired job lease."""


@dataclass(frozen=True, slots=True)
class DurableJob:
    id: int
    job_key: str
    job_type: str
    payload: dict[str, Any]
    status: JobStatus
    run_at: datetime
    attempt_count: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


def retry_backoff(attempt_count: int) -> timedelta | None:
    """Return the retry delay for an already-claimed attempt, capped at three."""
    if attempt_count < 1:
        raise ValueError("attempt_count must be positive")
    if attempt_count == 1:
        return timedelta(minutes=5)
    if attempt_count == 2:
        return timedelta(minutes=15)
    if attempt_count == 3:
        return timedelta(hours=1)
    return None


class DurableJobService:
    """Lease-backed job repository using short SQLite ``BEGIN IMMEDIATE`` claims."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = str(database_path)

    def create_schema(self) -> None:
        """Create the standalone table and indexes (normally done by migration v6)."""
        with self._connection() as connection:
            connection.executescript(BACKGROUND_JOBS_TABLE_SQL)

    def enqueue(
        self,
        *,
        job_key: str,
        job_type: str,
        payload: dict[str, Any],
        run_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> DurableJob:
        """Create a job once; repeated enqueue calls for a key return the original."""
        if not job_key:
            raise ValueError("job_key must not be empty")
        if not job_type:
            raise ValueError("job_type must not be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        now = _utc_now()
        due_at = _as_utc(run_at) if run_at is not None else now
        payload_json = _canonical_json(payload)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO background_jobs (
                    job_key, job_type, payload_json, status, run_at, max_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_key) DO NOTHING
                """,
                (
                    job_key,
                    job_type,
                    payload_json,
                    JobStatus.QUEUED,
                    _encode(due_at),
                    max_attempts,
                    _encode(now),
                    _encode(now),
                ),
            )
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE job_key = ?", (job_key,)
            ).fetchone()
        if row is None:  # pragma: no cover - guarded by NOT NULL UNIQUE key
            raise RuntimeError("job was not persisted")
        return _job_from_row(row)

    def claim_due(
        self,
        *,
        worker_id: str,
        lease_duration: timedelta,
        limit: int = 1,
        now: datetime | None = None,
    ) -> list[DurableJob]:
        """Atomically lease due jobs to one worker, returning only its successful claims."""
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if lease_duration <= timedelta():
            raise ValueError("lease_duration must be positive")
        if limit < 1:
            raise ValueError("limit must be positive")

        claimed_at = _as_utc(now) if now is not None else _utc_now()
        lease_expires_at = claimed_at + lease_duration
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._reconcile_expired_leases(connection, claimed_at)
            candidates = connection.execute(
                """
                SELECT id FROM background_jobs
                WHERE status = ? AND run_at <= ?
                ORDER BY run_at, id
                LIMIT ?
                """,
                (JobStatus.QUEUED, _encode(claimed_at), limit),
            ).fetchall()
            job_ids = [row["id"] for row in candidates]
            for job_id in job_ids:
                connection.execute(
                    """
                    UPDATE background_jobs
                    SET status = ?, attempt_count = attempt_count + 1, lease_owner = ?,
                        lease_expires_at = ?, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        JobStatus.RUNNING,
                        worker_id,
                        _encode(lease_expires_at),
                        _encode(claimed_at),
                        job_id,
                        JobStatus.QUEUED,
                    ),
                )
            rows = [
                connection.execute(
                    "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                for job_id in job_ids
            ]
            connection.commit()
        return [_job_from_row(row) for row in rows if row is not None]

    def heartbeat(
        self,
        *,
        job_id: int,
        worker_id: str,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> DurableJob:
        """Extend an owned, non-expired lease or raise :class:`LeaseLostError`."""
        if lease_duration <= timedelta():
            raise ValueError("lease_duration must be positive")
        heartbeat_at = _as_utc(now) if now is not None else _utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE background_jobs
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    _encode(heartbeat_at + lease_duration),
                    _encode(heartbeat_at),
                    job_id,
                    JobStatus.RUNNING,
                    worker_id,
                    _encode(heartbeat_at),
                ),
            )
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if cursor.rowcount != 1 or row is None:
            raise LeaseLostError(f"worker {worker_id!r} does not own job {job_id}")
        return _job_from_row(row)

    def complete(self, *, job_id: int, worker_id: str, now: datetime | None = None) -> DurableJob:
        """Mark an owned, non-expired lease as completed."""
        completed_at = _as_utc(now) if now is not None else _utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE background_jobs
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    completed_at = ?, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    JobStatus.COMPLETED,
                    _encode(completed_at),
                    _encode(completed_at),
                    job_id,
                    JobStatus.RUNNING,
                    worker_id,
                    _encode(completed_at),
                ),
            )
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if cursor.rowcount != 1 or row is None:
            raise LeaseLostError(f"worker {worker_id!r} does not own job {job_id}")
        return _job_from_row(row)

    def fail(
        self,
        *,
        job_id: int,
        worker_id: str,
        error: str,
        now: datetime | None = None,
    ) -> DurableJob:
        """Release a failed lease to a backoff retry, or mark final failure."""
        failed_at = _as_utc(now) if now is not None else _utc_now()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or not _valid_lease(row, worker_id, failed_at):
                raise LeaseLostError(f"worker {worker_id!r} does not own job {job_id}")
            attempts = int(row["attempt_count"])
            retry_delay = retry_backoff(attempts)
            terminal = attempts >= int(row["max_attempts"]) or retry_delay is None
            if terminal:
                status = JobStatus.FAILED
                run_at = failed_at
            else:
                status = JobStatus.QUEUED
                if retry_delay is None:  # pragma: no cover - covered by the terminal branch
                    raise RuntimeError("retry delay unexpectedly unavailable")
                run_at = failed_at + retry_delay
            connection.execute(
                """
                UPDATE background_jobs
                SET status = ?, run_at = ?, lease_owner = NULL, lease_expires_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, _encode(run_at), error, _encode(failed_at), job_id),
            )
            updated = connection.execute(
                "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if updated is None:  # pragma: no cover - row was selected in same transaction
            raise RuntimeError("job disappeared during failure handling")
        return _job_from_row(updated)

    def reconcile_expired_leases(self, *, now: datetime | None = None) -> int:
        """Make abandoned running jobs immediately eligible after process startup."""
        reconciled_at = _as_utc(now) if now is not None else _utc_now()
        with self._connection() as connection:
            return self._reconcile_expired_leases(connection, reconciled_at)

    def get(self, job_id: int) -> DurableJob | None:
        """Return a durable job by numeric id."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _job_from_row(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Any:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _reconcile_expired_leases(connection: sqlite3.Connection, now: datetime) -> int:
        cursor = connection.execute(
            """
            UPDATE background_jobs
            SET status = ?, run_at = ?, lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE status = ? AND lease_expires_at <= ?
            """,
            (JobStatus.QUEUED, _encode(now), _encode(now), JobStatus.RUNNING, _encode(now)),
        )
        return cursor.rowcount


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _encode(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds")


def _decode(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _valid_lease(row: sqlite3.Row, worker_id: str, now: datetime) -> bool:
    expires_at = row["lease_expires_at"]
    return (
        row["status"] == JobStatus.RUNNING
        and row["lease_owner"] == worker_id
        and expires_at is not None
        and _decode(expires_at) > now
    )


def _job_from_row(row: sqlite3.Row) -> DurableJob:
    return DurableJob(
        id=int(row["id"]),
        job_key=str(row["job_key"]),
        job_type=str(row["job_type"]),
        payload=json.loads(str(row["payload_json"])),
        status=JobStatus(row["status"]),
        run_at=_decode(str(row["run_at"])),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=_decode(row["lease_expires_at"]) if row["lease_expires_at"] else None,
        last_error=row["last_error"],
        created_at=_decode(str(row["created_at"])),
        updated_at=_decode(str(row["updated_at"])),
        completed_at=_decode(row["completed_at"]) if row["completed_at"] else None,
    )
