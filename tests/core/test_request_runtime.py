from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from bookflow.core.release_candidates import ReleaseCandidate, ReleaseProfile
from bookflow.core.request_runtime import RequestRuntime, decode_source_reference
from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.core.user_db import UserDB


def _seed(database_path: Path) -> tuple[int, list[int]]:
    users = UserDB(str(database_path))
    users.initialize()
    admin = users.create_user(username="admin", role="admin")
    members = [users.create_user(username="alice"), users.create_user(username="bob")]
    with sqlite3.connect(database_path) as connection:
        book_id = connection.execute(
            "INSERT INTO books (metadata_provider, provider_book_id, title) VALUES ('test', 'dune', 'Dune')"
        ).lastrowid
    assert book_id is not None
    service = RequestWorkflowService(database_path)
    request_process_id = 0
    for member in members:
        request = service.create_request(
            user_id=member["id"],
            book_id=book_id,
            profile={"formats": ["epub"]},
            content_type="ebook",
        )
        _request, request_process, _created = service.approve_request(
            request["id"], reviewer_user_id=admin["id"]
        )
        assert request_process is not None
        request_process_id = int(request_process["id"])
    return request_process_id, [int(member["id"]) for member in members]


def _runtime(database_path: Path, library: Path, queued: list[dict]) -> RequestRuntime:
    library.mkdir()

    def queue_release(payload, priority, user_id=None, username=None):
        queued.append(payload)
        return True, None

    return RequestRuntime(str(database_path), queue_release=queue_release, library_root=library)


def _search(
    runtime: RequestRuntime,
    request_process_id: int,
    candidates: list[ReleaseCandidate],
    *,
    allowed_formats: tuple[str, ...] = ("epub",),
) -> None:
    runtime._search.run_search(
        request_process_id,
        profile=ReleaseProfile(
            title="Dune", allowed_formats=allowed_formats, allowed_protocols=("direct",)
        ),
        sources={"direct_download": lambda: candidates},
    )


def test_terminal_completion_imports_once_and_fulfils_all_recipients(tmp_path: Path) -> None:
    database_path = tmp_path / "users.db"
    request_process_id, users = _seed(database_path)
    queued: list[dict] = []
    runtime = _runtime(database_path, tmp_path / "library", queued)
    candidate = ReleaseCandidate(
        source="direct_download",
        title="Dune",
        format="epub",
        protocol="direct",
        metadata={"payload_reference": "source:direct_download:ZHVuZS1yZWxlYXNl"},
    )
    _search(runtime, request_process_id, [candidate])

    attempt = runtime.start_attempt(request_process_id)
    assert attempt is not None
    assert queued[0]["source_id"] == "dune-release"
    assert queued[0]["library_book_id"] is not None
    assert queued[0]["content_type"] == "ebook"
    assert queued[0]["_request_id"] is not None
    assert (
        decode_source_reference(
            "source:direct_download:ZHVuZS1yZWxlYXNl", expected_source="direct_download"
        )
        == "dune-release"
    )
    artifact = tmp_path / "library" / "Dune.epub"
    artifact.write_bytes(b"an ebook")
    runtime.handle_terminal(
        SimpleNamespace(
            task_id="dune-release",
            source="direct_download",
            library_paths=[str(artifact)],
            download_path=str(artifact),
            status_message=None,
        ),
        status="complete",
    )

    with sqlite3.connect(database_path) as connection:
        statuses = connection.execute("SELECT status FROM requests ORDER BY user_id").fetchall()
        entitlements = connection.execute(
            "SELECT user_id FROM user_file_entitlements ORDER BY user_id"
        ).fetchall()
        acquired = connection.execute(
            "SELECT status FROM request_processes WHERE id = ?", (request_process_id,)
        ).fetchone()
    assert statuses == [("fulfilled",), ("fulfilled",)]
    assert [row[0] for row in entitlements] == users
    assert acquired == ("completed",)


def test_permanent_failure_enqueues_next_candidate(tmp_path: Path) -> None:
    database_path = tmp_path / "users.db"
    request_process_id, _users = _seed(database_path)
    queued: list[dict] = []
    runtime = _runtime(database_path, tmp_path / "library", queued)
    _search(
        runtime,
        request_process_id,
        [
            ReleaseCandidate(
                source="direct_download",
                indexer="local",
                guid="first",
                title="Dune",
                format="epub",
                protocol="direct",
                metadata={"payload_reference": "source:direct_download:Zmlyc3Q"},
            ),
            ReleaseCandidate(
                source="direct_download",
                indexer="local",
                guid="second",
                title="Dune",
                format="epub",
                protocol="direct",
                metadata={"payload_reference": "source:direct_download:c2Vjb25k"},
            ),
        ],
    )
    first = runtime.start_attempt(request_process_id)
    assert first is not None
    runtime.handle_terminal(
        SimpleNamespace(
            task_id="first",
            source="direct_download",
            last_error_type="ArchiveExtractionError",
            last_error_message="invalid archive",
            status_message=None,
        ),
        status="error",
    )
    runtime._scheduler.run_once()
    assert [payload["source_id"] for payload in queued] == ["first", "second"]


def test_restart_recovery_claims_a_due_monitored_search(tmp_path: Path) -> None:
    database_path = tmp_path / "users.db"
    request_process_id, _users = _seed(database_path)
    queued: list[dict] = []
    runtime = _runtime(database_path, tmp_path / "library", queued)
    now = datetime(2031, 1, 2, 3, 4, 5, tzinfo=UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """UPDATE request_processes SET status = 'waiting_for_release', monitoring_enabled = 1,
            next_search_at = ? WHERE id = ?""",
            ((now - timedelta(minutes=1)).isoformat(), request_process_id),
        )
    searched: list[int] = []
    runtime._scheduler._search_request = lambda current_id: (  # type: ignore[attr-defined]
        searched.append(current_id) or {"accepted_count": 0}
    )

    recovered, enqueued = runtime._scheduler.recover_and_schedule(now=now)
    run = runtime._scheduler.run_once(now=now)

    assert recovered == 0
    assert enqueued == 1
    assert run.completed_jobs == 1
    assert searched == [request_process_id]
