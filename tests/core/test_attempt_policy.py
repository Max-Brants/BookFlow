from __future__ import annotations

from datetime import timedelta

import pytest

from bookflow.core.attempt_policy import (
    DEFAULT_RETRY_DELAYS,
    FailureCode,
    FailureDisposition,
    decide_attempt_failure,
    monitoring_backoff,
)


@pytest.mark.parametrize(
    "code",
    [
        FailureCode.NOT_FOUND,
        FailureCode.CORRUPT,
        FailureCode.PASSWORD_PROTECTED,
        FailureCode.WRONG_CONTENT,
        FailureCode.EXECUTABLE_CONTENT,
    ],
)
def test_permanent_release_failure_blocks_candidate(code):
    decision = decide_attempt_failure(code, retries_already_scheduled=0)

    assert decision.disposition is FailureDisposition.BLOCK_CANDIDATE
    assert decision.should_block is True
    assert decision.retry_delay is None


@pytest.mark.parametrize(
    "retry_number, expected",
    list(enumerate(DEFAULT_RETRY_DELAYS)),
)
def test_transient_failures_follow_backoff(retry_number, expected):
    decision = decide_attempt_failure(
        FailureCode.NETWORK,
        retries_already_scheduled=retry_number,
    )

    assert decision.disposition is FailureDisposition.RETRY_CANDIDATE
    assert decision.retry_delay == expected
    assert decision.should_block is False


def test_exhausted_transient_and_config_errors_need_attention_without_blocking():
    exhausted = decide_attempt_failure(
        FailureCode.TIMEOUT,
        retries_already_scheduled=len(DEFAULT_RETRY_DELAYS),
    )
    configuration = decide_attempt_failure(
        FailureCode.CREDENTIALS,
        retries_already_scheduled=0,
    )

    assert exhausted.disposition is FailureDisposition.NEEDS_ATTENTION
    assert configuration.disposition is FailureDisposition.NEEDS_ATTENTION
    assert exhausted.should_block is configuration.should_block is False


def test_monitoring_backoff_caps_at_last_delay():
    assert monitoring_backoff(0) == timedelta(hours=6)
    assert monitoring_backoff(1) == timedelta(hours=12)
    assert monitoring_backoff(50) == timedelta(hours=24)
