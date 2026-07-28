"""Deterministic request_process attempt failure and retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class FailureDisposition(StrEnum):
    """Effect a failure has on the current release candidate."""

    RETRY_CANDIDATE = "retry_candidate"
    BLOCK_CANDIDATE = "block_candidate"
    NEEDS_ATTENTION = "needs_attention"


class FailureCode(StrEnum):
    """Stable machine-readable failure classes."""

    NETWORK = "network"
    TIMEOUT = "timeout"
    CLIENT_UNAVAILABLE = "client_unavailable"
    NOT_FOUND = "not_found"
    CORRUPT = "corrupt"
    PASSWORD_PROTECTED = "password_protected"  # noqa: S105
    WRONG_CONTENT = "wrong_content"
    EXECUTABLE_CONTENT = "executable_content"
    CREDENTIALS = "credentials"
    CONFIGURATION = "configuration"
    STORAGE = "storage"
    UNKNOWN = "unknown"


_PERMANENT_FAILURES = frozenset(
    {
        FailureCode.NOT_FOUND,
        FailureCode.CORRUPT,
        FailureCode.PASSWORD_PROTECTED,
        FailureCode.WRONG_CONTENT,
        FailureCode.EXECUTABLE_CONTENT,
    }
)
_TRANSIENT_FAILURES = frozenset(
    {
        FailureCode.NETWORK,
        FailureCode.TIMEOUT,
        FailureCode.CLIENT_UNAVAILABLE,
    }
)
DEFAULT_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)


@dataclass(frozen=True, slots=True)
class AttemptDecision:
    disposition: FailureDisposition
    retry_delay: timedelta | None
    should_block: bool


def decide_attempt_failure(
    code: FailureCode | str,
    *,
    retries_already_scheduled: int,
    retry_delays: tuple[timedelta, ...] = DEFAULT_RETRY_DELAYS,
) -> AttemptDecision:
    """Classify a failure without accidentally blocklisting configuration errors."""
    normalized = FailureCode(code)
    if retries_already_scheduled < 0:
        raise ValueError("retries_already_scheduled cannot be negative")
    if any(delay.total_seconds() <= 0 for delay in retry_delays):
        raise ValueError("retry delays must be positive")

    if normalized in _PERMANENT_FAILURES:
        return AttemptDecision(
            disposition=FailureDisposition.BLOCK_CANDIDATE,
            retry_delay=None,
            should_block=True,
        )
    if normalized in _TRANSIENT_FAILURES and retries_already_scheduled < len(retry_delays):
        return AttemptDecision(
            disposition=FailureDisposition.RETRY_CANDIDATE,
            retry_delay=retry_delays[retries_already_scheduled],
            should_block=False,
        )
    return AttemptDecision(
        disposition=FailureDisposition.NEEDS_ATTENTION,
        retry_delay=None,
        should_block=False,
    )


def monitoring_backoff(
    consecutive_empty_searches: int,
    *,
    delays: tuple[timedelta, ...] = (
        timedelta(hours=6),
        timedelta(hours=12),
        timedelta(hours=24),
    ),
) -> timedelta:
    """Return capped delay for a monitored request_process with no candidates."""
    if consecutive_empty_searches < 0:
        raise ValueError("consecutive_empty_searches cannot be negative")
    if not delays or any(delay.total_seconds() <= 0 for delay in delays):
        raise ValueError("monitoring delays must be non-empty and positive")
    return delays[min(consecutive_empty_searches, len(delays) - 1)]
