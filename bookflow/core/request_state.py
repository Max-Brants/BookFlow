"""Pure domain rules for durable Requests and RequestProcesss.

This module deliberately has no database or Flask dependency.  Persistence layers
may use these rules inside a transaction without giving routes or workers a second
state-machine implementation to maintain.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from enum import StrEnum
from typing import Any


class RequestStatus(StrEnum):
    """User approval lifecycle; technical work belongs to an RequestProcess."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RequestProcessStatus(StrEnum):
    """Technical lifecycle for one shared request_process."""

    QUEUED = "queued"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    RETRY_SCHEDULED = "retry_scheduled"
    WAITING_FOR_RELEASE = "waiting_for_release"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RequestEvent(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    FULFIL = "fulfil"


class StateTransitionError(ValueError):
    """Base error for a requested state transition that is not permitted."""


class TerminalStateError(StateTransitionError):
    """Raised when an event tries to alter an already terminal lifecycle."""


class StaleTransitionError(StateTransitionError):
    """Raised when a caller acts on a state different from its expected state."""


class ProfileSnapshotError(ValueError):
    """Raised when a profile cannot be represented as a deterministic JSON snapshot."""


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

_REQUEST_TERMINAL = frozenset(
    {RequestStatus.FULFILLED, RequestStatus.REJECTED, RequestStatus.CANCELLED}
)
_REQUEST_PROCESS_TERMINAL = frozenset(
    {RequestProcessStatus.COMPLETED, RequestProcessStatus.CANCELLED, RequestProcessStatus.FAILED}
)
_REQUEST_TRANSITIONS: dict[RequestStatus, dict[RequestEvent, RequestStatus]] = {
    RequestStatus.PENDING_APPROVAL: {
        RequestEvent.APPROVE: RequestStatus.APPROVED,
        RequestEvent.REJECT: RequestStatus.REJECTED,
        RequestEvent.CANCEL: RequestStatus.CANCELLED,
    },
    RequestStatus.APPROVED: {
        RequestEvent.CANCEL: RequestStatus.CANCELLED,
        RequestEvent.FULFIL: RequestStatus.FULFILLED,
    },
}
_REQUEST_PROCESS_TRANSITIONS: dict[RequestProcessStatus, frozenset[RequestProcessStatus]] = {
    RequestProcessStatus.QUEUED: frozenset(
        {RequestProcessStatus.SEARCHING, RequestProcessStatus.CANCELLED}
    ),
    RequestProcessStatus.SEARCHING: frozenset(
        {
            RequestProcessStatus.DOWNLOADING,
            RequestProcessStatus.WAITING_FOR_RELEASE,
            RequestProcessStatus.NEEDS_ATTENTION,
            RequestProcessStatus.CANCELLED,
        }
    ),
    RequestProcessStatus.DOWNLOADING: frozenset(
        {
            RequestProcessStatus.IMPORTING,
            RequestProcessStatus.RETRY_SCHEDULED,
            RequestProcessStatus.NEEDS_ATTENTION,
            RequestProcessStatus.CANCELLED,
        }
    ),
    RequestProcessStatus.IMPORTING: frozenset(
        {
            RequestProcessStatus.COMPLETED,
            RequestProcessStatus.RETRY_SCHEDULED,
            RequestProcessStatus.NEEDS_ATTENTION,
            RequestProcessStatus.CANCELLED,
        }
    ),
    RequestProcessStatus.RETRY_SCHEDULED: frozenset(
        {
            RequestProcessStatus.SEARCHING,
            RequestProcessStatus.DOWNLOADING,
            RequestProcessStatus.CANCELLED,
        }
    ),
    RequestProcessStatus.WAITING_FOR_RELEASE: frozenset(
        {RequestProcessStatus.SEARCHING, RequestProcessStatus.CANCELLED}
    ),
    RequestProcessStatus.NEEDS_ATTENTION: frozenset(
        {
            RequestProcessStatus.SEARCHING,
            RequestProcessStatus.DOWNLOADING,
            RequestProcessStatus.RETRY_SCHEDULED,
            RequestProcessStatus.CANCELLED,
            RequestProcessStatus.FAILED,
        }
    ),
}
_RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1))


def is_request_terminal(status: RequestStatus) -> bool:
    """Return whether a Request can no longer change state."""
    return status in _REQUEST_TERMINAL


def is_request_process_terminal(status: RequestProcessStatus) -> bool:
    """Return whether an RequestProcess can no longer change state."""
    return status in _REQUEST_PROCESS_TERMINAL


def transition_request(
    status: RequestStatus,
    event: RequestEvent,
    *,
    expected_status: RequestStatus | None = None,
) -> RequestStatus:
    """Apply one Request event, rejecting stale or invalid mutations.

    Replaying an event that already achieved its target is a no-op.  This makes
    approval/fulfilment handlers safe to retry after a transaction response was
    lost, while preserving terminal-state immutability for every other event.
    """
    if expected_status is not None and status != expected_status:
        raise StaleTransitionError(f"Expected Request status {expected_status}, got {status}")

    target = {
        RequestEvent.APPROVE: RequestStatus.APPROVED,
        RequestEvent.REJECT: RequestStatus.REJECTED,
        RequestEvent.CANCEL: RequestStatus.CANCELLED,
        RequestEvent.FULFIL: RequestStatus.FULFILLED,
    }[event]
    if status == target:
        return status
    if is_request_terminal(status):
        raise TerminalStateError(f"Request in terminal status {status} cannot {event}")
    try:
        return _REQUEST_TRANSITIONS[status][event]
    except KeyError as exc:
        raise StateTransitionError(f"Request cannot {event} from {status}") from exc


def can_transition_request_process(
    current: RequestProcessStatus, target: RequestProcessStatus
) -> bool:
    """Return whether an RequestProcess target state is legal, including a no-op replay."""
    return current == target or target in _REQUEST_PROCESS_TRANSITIONS.get(current, frozenset())


def transition_request_process(
    status: RequestProcessStatus,
    target: RequestProcessStatus,
    *,
    expected_status: RequestProcessStatus | None = None,
) -> RequestProcessStatus:
    """Move an RequestProcess to a legal target state."""
    if expected_status is not None and status != expected_status:
        raise StaleTransitionError(f"Expected Request status {expected_status}, got {status}")
    if status == target:
        return status
    if is_request_process_terminal(status):
        raise TerminalStateError(f"Request in terminal status {status} cannot become {target}")
    if not can_transition_request_process(status, target):
        raise StateTransitionError(f"Request cannot transition from {status} to {target}")
    return target


def retry_delay(retry_number: int) -> timedelta | None:
    """Return the bounded retry backoff for retry 1, 2, or 3."""
    if retry_number < 1:
        raise ValueError("retry_number must be positive")
    if retry_number > len(_RETRY_DELAYS):
        return None
    return _RETRY_DELAYS[retry_number - 1]


def can_schedule_retry(status: RequestProcessStatus, retry_number: int) -> bool:
    """Return whether a transient failure can create another retry job."""
    return status in {RequestProcessStatus.DOWNLOADING, RequestProcessStatus.IMPORTING} and (
        retry_delay(retry_number) is not None
    )


def request_process_claimable(
    status: RequestProcessStatus, *, active_request_attempt_id: int | None
) -> bool:
    """Return whether a worker may claim technical work without double-processing it."""
    return active_request_attempt_id is None and status in {
        RequestProcessStatus.QUEUED,
        RequestProcessStatus.RETRY_SCHEDULED,
        RequestProcessStatus.WAITING_FOR_RELEASE,
        RequestProcessStatus.NEEDS_ATTENTION,
    }


def derive_request_status(
    request_status: RequestStatus,
    request_process_status: RequestProcessStatus | None,
    *,
    file_available: bool,
) -> RequestStatus | RequestProcessStatus:
    """Derive the visible technical state without storing it on a Request.

    A usable file wins over an approved request's technical status and fulfils it;
    request_process errors never make the user's request terminal.
    """
    if request_status != RequestStatus.APPROVED:
        return request_status
    if file_available:
        return RequestStatus.FULFILLED
    return request_process_status or RequestStatus.APPROVED


def profile_snapshot(profile: dict[str, Any]) -> dict[str, JsonValue]:
    """Validate and deep-copy a profile into a JSON-safe immutable-by-convention snapshot."""
    try:
        canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False)
        loaded = json.loads(canonical)
    except (TypeError, ValueError) as exc:
        raise ProfileSnapshotError(
            "Profile must contain only finite JSON values and string keys"
        ) from exc
    if not isinstance(loaded, dict):
        raise ProfileSnapshotError("Profile snapshot must be a JSON object")
    return deepcopy(loaded)


def profile_hash(profile: dict[str, Any]) -> str:
    """Return the stable SHA-256 fingerprint used for sharing compatible work."""
    snapshot = profile_snapshot(profile)
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
