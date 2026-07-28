"""Unit tests for the pure Request/RequestProcess state-machine kernel."""

from datetime import timedelta

import pytest

from bookflow.core.request_state import (
    ProfileSnapshotError,
    RequestEvent,
    RequestProcessStatus,
    RequestStatus,
    StaleTransitionError,
    StateTransitionError,
    TerminalStateError,
    can_schedule_retry,
    can_transition_request_process,
    derive_request_status,
    profile_hash,
    profile_snapshot,
    request_process_claimable,
    retry_delay,
    transition_request,
    transition_request_process,
)


def test_duplicate_approval_is_idempotent_but_approval_of_terminal_request_is_not():
    assert (
        transition_request(RequestStatus.APPROVED, RequestEvent.APPROVE) == RequestStatus.APPROVED
    )
    with pytest.raises(TerminalStateError):
        transition_request(RequestStatus.FULFILLED, RequestEvent.APPROVE)


def test_request_transitions_enforce_lifecycle_and_stale_compare_and_swap():
    assert (
        transition_request(RequestStatus.PENDING_APPROVAL, RequestEvent.APPROVE)
        == RequestStatus.APPROVED
    )
    assert (
        transition_request(RequestStatus.APPROVED, RequestEvent.FULFIL) == RequestStatus.FULFILLED
    )
    with pytest.raises(StateTransitionError):
        transition_request(RequestStatus.PENDING_APPROVAL, RequestEvent.FULFIL)
    with pytest.raises(StaleTransitionError):
        transition_request(
            RequestStatus.APPROVED,
            RequestEvent.FULFIL,
            expected_status=RequestStatus.PENDING_APPROVAL,
        )


def test_request_process_transitions_are_explicit_and_terminal_states_are_immutable():
    assert transition_request_process(
        RequestProcessStatus.QUEUED, RequestProcessStatus.SEARCHING
    ) == (RequestProcessStatus.SEARCHING)
    assert transition_request_process(
        RequestProcessStatus.SEARCHING, RequestProcessStatus.SEARCHING
    ) == (RequestProcessStatus.SEARCHING)
    assert not can_transition_request_process(
        RequestProcessStatus.QUEUED, RequestProcessStatus.DOWNLOADING
    )
    with pytest.raises(StateTransitionError):
        transition_request_process(RequestProcessStatus.QUEUED, RequestProcessStatus.DOWNLOADING)
    with pytest.raises(TerminalStateError):
        transition_request_process(RequestProcessStatus.COMPLETED, RequestProcessStatus.SEARCHING)


def test_request_process_recovery_paths_and_stale_transitions_are_supported_safely():
    assert (
        transition_request_process(
            RequestProcessStatus.NEEDS_ATTENTION, RequestProcessStatus.RETRY_SCHEDULED
        )
        == RequestProcessStatus.RETRY_SCHEDULED
    )
    assert (
        transition_request_process(
            RequestProcessStatus.RETRY_SCHEDULED, RequestProcessStatus.DOWNLOADING
        )
        == RequestProcessStatus.DOWNLOADING
    )
    with pytest.raises(StaleTransitionError):
        transition_request_process(
            RequestProcessStatus.SEARCHING,
            RequestProcessStatus.DOWNLOADING,
            expected_status=RequestProcessStatus.QUEUED,
        )


def test_retry_and_claim_rules_bound_retries_and_prevent_concurrent_attempts():
    assert retry_delay(1) == timedelta(minutes=5)
    assert retry_delay(2) == timedelta(minutes=15)
    assert retry_delay(3) == timedelta(hours=1)
    assert retry_delay(4) is None
    with pytest.raises(ValueError):
        retry_delay(0)
    assert can_schedule_retry(RequestProcessStatus.DOWNLOADING, 3)
    assert not can_schedule_retry(RequestProcessStatus.DOWNLOADING, 4)
    assert not can_schedule_retry(RequestProcessStatus.SEARCHING, 1)
    assert request_process_claimable(
        RequestProcessStatus.RETRY_SCHEDULED, active_request_attempt_id=None
    )
    assert not request_process_claimable(
        RequestProcessStatus.RETRY_SCHEDULED, active_request_attempt_id=17
    )
    assert not request_process_claimable(
        RequestProcessStatus.DOWNLOADING, active_request_attempt_id=None
    )


@pytest.mark.parametrize(
    ("request_status", "request_process_status", "file_available", "expected"),
    [
        (
            RequestStatus.PENDING_APPROVAL,
            RequestProcessStatus.SEARCHING,
            False,
            RequestStatus.PENDING_APPROVAL,
        ),
        (
            RequestStatus.APPROVED,
            RequestProcessStatus.WAITING_FOR_RELEASE,
            False,
            RequestProcessStatus.WAITING_FOR_RELEASE,
        ),
        (
            RequestStatus.APPROVED,
            RequestProcessStatus.NEEDS_ATTENTION,
            False,
            RequestProcessStatus.NEEDS_ATTENTION,
        ),
        (RequestStatus.APPROVED, RequestProcessStatus.DOWNLOADING, True, RequestStatus.FULFILLED),
        (RequestStatus.REJECTED, RequestProcessStatus.COMPLETED, True, RequestStatus.REJECTED),
    ],
)
def test_visible_request_status_is_derived_without_mutating_user_lifecycle(
    request_status, request_process_status, file_available, expected
):
    assert (
        derive_request_status(request_status, request_process_status, file_available=file_available)
        == expected
    )


def test_profile_snapshots_are_order_independent_json_safe_and_detached_from_input():
    profile = {"formats": ["epub", "kepub"], "language": "nl", "weights": {"title": 20}}
    snapshot = profile_snapshot(profile)
    profile["formats"].append("pdf")
    assert snapshot == {"formats": ["epub", "kepub"], "language": "nl", "weights": {"title": 20}}
    assert profile_hash(snapshot) == profile_hash(
        {"weights": {"title": 20}, "language": "nl", "formats": ["epub", "kepub"]}
    )
    assert len(profile_hash(snapshot)) == 64


def test_profile_snapshot_rejects_non_json_values():
    with pytest.raises(ProfileSnapshotError):
        profile_snapshot({"formats": {"epub"}})
