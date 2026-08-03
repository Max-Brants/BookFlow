from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask

from bookflow.core.attempt_policy import FailureCode
from bookflow.core.attempt_service import AttemptService
from bookflow.core.release_candidates import ReleaseCandidate, ReleaseProfile
from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.core.search_service import SearchService
from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor, register_v1_api


class _Adapter:
    def add(self, candidate, *, idempotency_key):
        del candidate, idempotency_key
        return "source:legacy-task"


def _seed_retryable_candidate(path: Path) -> tuple[int, int]:
    users = UserDB(str(path))
    users.initialize()
    admin = users.create_user(username="admin", role="admin")
    reader = users.create_user(username="reader")
    with sqlite3.connect(path) as connection:
        book_id = connection.execute(
            "INSERT INTO books (metadata_provider, provider_book_id, title) VALUES ('test', 'book', 'Book')"
        ).lastrowid
    assert book_id is not None
    workflow = RequestWorkflowService(path)
    request = workflow.create_request(user_id=reader["id"], book_id=book_id, profile={})
    _request, process, _created = workflow.approve_request(
        request["id"], reviewer_user_id=admin["id"]
    )
    assert process is not None
    process_id = int(process["id"])
    SearchService(path).run_search(
        process_id,
        profile=ReleaseProfile(title="Book", allowed_formats=("epub",)),
        sources={
            "source": lambda: [
                ReleaseCandidate(source="source", title="Book", format="epub", protocol="direct")
            ]
        },
    )
    attempts = AttemptService(path)
    attempt = attempts.start_next_candidate(
        process_id, adapter_name="legacy_queue", adapter=_Adapter()
    )
    assert attempt is not None
    candidate_id = int(attempt["candidate_id"])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE release_candidates SET selected_by = ?, selected_at = CURRENT_TIMESTAMP WHERE id = ?",
            (admin["id"], candidate_id),
        )
    attempts.record_failure(
        int(attempt["id"]), FailureCode.CONFIGURATION, error_message="path mapping missing"
    )
    return process_id, candidate_id


def test_candidate_retry_is_admin_only_and_candidate_response_exposes_availability(
    tmp_path: Path,
) -> None:
    path = tmp_path / "users.db"
    process_id, candidate_id = _seed_retryable_candidate(path)
    actor = {"value": V1Actor(1, is_admin=False)}
    attempts = AttemptService(path)

    def retry(candidate: int) -> dict[str, int]:
        claim = attempts.claim_selected_candidate_retry(candidate)
        return {
            "candidate_id": claim.candidate_id,
            "request_process_id": claim.request_process_id,
            "request_attempt_id": claim.request_attempt_id,
        }

    app = Flask(__name__)
    register_v1_api(
        app,
        database_path=path,
        resolve_actor=lambda: actor["value"],
        retry_candidate=retry,
    )
    client = app.test_client()

    forbidden = client.post(f"/api/v1/admin/candidates/{candidate_id}/retry")
    assert forbidden.status_code == 403

    actor["value"] = V1Actor(1, is_admin=True)
    candidates = client.get(f"/api/v1/admin/request-processes/{process_id}/candidates")
    assert candidates.status_code == 200
    assert candidates.json["items"][0]["retry_available"] == 1

    retried = client.post(f"/api/v1/admin/candidates/{candidate_id}/retry")
    assert retried.status_code == 202
    assert retried.json["candidate_id"] == candidate_id
    assert retried.json["retried"] is True

    duplicate = client.post(f"/api/v1/admin/candidates/{candidate_id}/retry")
    assert duplicate.status_code == 409
    assert duplicate.json["error"]["code"] == "candidate_retry_conflict"

    missing = client.post("/api/v1/admin/candidates/999999/retry")
    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "candidate_not_found"
