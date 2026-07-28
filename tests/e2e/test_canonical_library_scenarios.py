"""Literal end-to-end acceptance scenarios for the canonical library workflow."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from bookflow.core.kobo_services import KoboEntitlementError, KoboSyncService, TokenService
from bookflow.core.release_candidates import ReleaseCandidate, ReleaseProfile
from bookflow.core.request_runtime import RequestRuntime
from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.core.user_db import UserDB

pytestmark = pytest.mark.e2e


def _seed_users_and_book(database_path: Path) -> tuple[int, int, int, int, int]:
    users = UserDB(str(database_path))
    users.initialize()
    admin_id = int(users.create_user(username="admin", role="admin")["id"])
    henkie_id = int(users.create_user(username="henkie")["id"])
    eline_id = int(users.create_user(username="eline")["id"])
    outsider_id = int(users.create_user(username="outsider")["id"])
    with sqlite3.connect(database_path) as connection:
        book_id = connection.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, author)
            VALUES ('fake-metadata', 'shared-book', 'Shared Book', 'BookFlow')
            """
        ).lastrowid
    assert book_id is not None
    return admin_id, henkie_id, eline_id, outsider_id, int(book_id)


def _approve_shared_requests(
    database_path: Path,
    *,
    admin_id: int,
    book_id: int,
    user_ids: tuple[int, int],
) -> tuple[RequestWorkflowService, int, list[int]]:
    service = RequestWorkflowService(database_path)
    request_ids: list[int] = []
    request_process_ids: list[int] = []
    for user_id in user_ids:
        request = service.create_request(
            user_id=user_id,
            book_id=book_id,
            profile={"formats": ["epub"], "protocols": ["direct"]},
            add_to_kobo_when_available=True,
        )
        request_ids.append(int(request["id"]))
        _approved, request_process, _created = service.approve_request(
            int(request["id"]),
            reviewer_user_id=admin_id,
        )
        assert request_process is not None
        request_process_ids.append(int(request_process["id"]))
    assert len(set(request_process_ids)) == 1
    return service, request_process_ids[0], request_ids


def _runtime(
    database_path: Path,
    library_root: Path,
    queued: list[dict[str, object]],
) -> RequestRuntime:
    library_root.mkdir(exist_ok=True)

    def queue_release(
        payload: dict[str, object],
        _priority: int,
        user_id: int | None = None,
        username: str | None = None,
    ) -> tuple[bool, None]:
        queued.append({**payload, "queued_user_id": user_id, "queued_username": username})
        return True, None

    return RequestRuntime(
        str(database_path),
        queue_release=queue_release,
        library_root=library_root,
    )


def _persist_two_candidates(runtime: RequestRuntime, request_process_id: int) -> None:
    runtime._search.run_search(
        request_process_id,
        profile=ReleaseProfile(
            title="Shared Book",
            allowed_formats=("epub",),
            allowed_protocols=("direct",),
        ),
        sources={
            "direct_download": lambda: [
                ReleaseCandidate(
                    source="direct_download",
                    indexer="fake",
                    guid="broken",
                    title="Shared Book",
                    format="epub",
                    protocol="direct",
                    metadata={"payload_reference": "source:direct_download:YnJva2VuLXJlbGVhc2U"},
                ),
                ReleaseCandidate(
                    source="direct_download",
                    indexer="fake",
                    guid="working",
                    title="Shared Book",
                    format="epub",
                    protocol="direct",
                    metadata={"payload_reference": "source:direct_download:d29ya2luZy1yZWxlYXNl"},
                ),
            ]
        },
    )


def test_two_readers_share_one_request_process_with_automatic_candidate_fallback(
    tmp_path: Path,
) -> None:
    """Henkie and Eline converge on one Book, file and request_process."""
    database_path = tmp_path / "users.db"
    admin_id, henkie_id, eline_id, outsider_id, book_id = _seed_users_and_book(database_path)
    service, request_process_id, request_ids = _approve_shared_requests(
        database_path,
        admin_id=admin_id,
        book_id=book_id,
        user_ids=(henkie_id, eline_id),
    )
    queued: list[dict[str, object]] = []
    runtime = _runtime(database_path, tmp_path / "library", queued)
    _persist_two_candidates(runtime, request_process_id)

    first_attempt = runtime.start_attempt(request_process_id)
    assert first_attempt is not None
    assert [item["source_id"] for item in queued] == ["broken-release"]
    runtime.handle_terminal(
        SimpleNamespace(
            task_id="broken-release",
            source="direct_download",
            last_error_type="ArchiveExtractionError",
            last_error_message="invalid archive",
            status_message=None,
        ),
        status="error",
    )
    runtime._scheduler.run_once()
    assert [item["source_id"] for item in queued] == ["broken-release", "working-release"]

    artifact = tmp_path / "library" / "working.epub"
    artifact.write_bytes(b"one canonical ebook")
    runtime.handle_terminal(
        SimpleNamespace(
            task_id="working-release",
            source="direct_download",
            library_paths=[str(artifact)],
            download_path=str(artifact),
            status_message=None,
        ),
        status="complete",
    )

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        counts = {
            "books": connection.execute("SELECT COUNT(*) FROM books").fetchone()[0],
            "files": connection.execute("SELECT COUNT(*) FROM book_files").fetchone()[0],
            "request_processes": connection.execute(
                "SELECT COUNT(*) FROM request_processes"
            ).fetchone()[0],
        }
        requests = connection.execute(
            "SELECT id, status, fulfilled_file_id FROM requests ORDER BY id"
        ).fetchall()
        entitled_users = {
            int(row[0])
            for row in connection.execute(
                "SELECT user_id FROM user_file_entitlements ORDER BY user_id"
            ).fetchall()
        }
        blocked = connection.execute(
            "SELECT reason FROM blocked_releases WHERE request_process_id = ?",
            (request_process_id,),
        ).fetchone()
    assert counts == {"books": 1, "files": 1, "request_processes": 1}
    assert [int(row["id"]) for row in requests] == request_ids
    assert all(row["status"] == "fulfilled" and row["fulfilled_file_id"] for row in requests)
    assert entitled_users == {henkie_id, eline_id}
    assert outsider_id not in entitled_users
    assert blocked is not None and blocked["reason"] == "corrupt"

    later = service.create_request(
        user_id=henkie_id,
        book_id=book_id,
        profile={"formats": ["epub"], "protocols": ["direct"]},
    )
    assert later["status"] == "fulfilled"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM request_processes").fetchone()[0] == 1


def test_personal_kobo_state_and_monitoring_survive_independently(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both readers sync one central file; removal and recovery remain isolated."""
    database_path = tmp_path / "users.db"
    admin_id, henkie_id, eline_id, outsider_id, book_id = _seed_users_and_book(database_path)
    _service, request_process_id, _request_ids = _approve_shared_requests(
        database_path,
        admin_id=admin_id,
        book_id=book_id,
        user_ids=(henkie_id, eline_id),
    )
    queued: list[dict[str, object]] = []
    runtime = _runtime(database_path, tmp_path / "library", queued)
    runtime._search.run_search(
        request_process_id,
        profile=ReleaseProfile(
            title="Shared Book",
            allowed_formats=("epub",),
            allowed_protocols=("direct",),
        ),
        sources={
            "direct_download": lambda: [
                ReleaseCandidate(
                    source="direct_download",
                    title="Shared Book",
                    format="epub",
                    protocol="direct",
                    metadata={"payload_reference": "source:direct_download:c2hhcmVk"},
                )
            ]
        },
    )
    runtime.start_attempt(request_process_id)
    artifact = tmp_path / "library" / "shared.epub"
    artifact.write_bytes(b"shared central ebook")
    runtime.handle_terminal(
        SimpleNamespace(
            task_id="shared",
            source="direct_download",
            library_paths=[str(artifact)],
            download_path=str(artifact),
            status_message=None,
        ),
        status="complete",
    )
    with sqlite3.connect(database_path) as connection:
        file_id = int(connection.execute("SELECT id FROM book_files").fetchone()[0])

    sync = KoboSyncService(str(database_path), cursor_secret="e2e-cursor-secret")
    for user_id in (henkie_id, eline_id, outsider_id):
        sync.enable_user(user_id=user_id)
    sync.set_book(user_id=henkie_id, book_id=book_id, file_id=file_id)
    sync.set_book(user_id=eline_id, book_id=book_id, file_id=file_id)
    assert [change["type"] for change in sync.sync(user_id=henkie_id).changes] == ["upsert"]
    assert [change["type"] for change in sync.sync(user_id=eline_id).changes] == ["upsert"]
    with pytest.raises(KoboEntitlementError):
        sync.set_book(user_id=outsider_id, book_id=book_id, file_id=file_id)

    sync.delete_book(user_id=henkie_id, book_id=book_id)
    assert [change["type"] for change in sync.sync(user_id=henkie_id).changes] == [
        "upsert",
        "delete",
    ]
    assert [change["type"] for change in sync.sync(user_id=eline_id).changes] == ["upsert"]
    assert sync.get_book_metadata(user_id=eline_id, book_id=book_id)["id"] == book_id

    caplog.set_level(logging.DEBUG)
    token = (
        TokenService(str(database_path), pepper="e2e-token-pepper")
        .issue_token(user_id=eline_id)
        .token
    )
    assert token not in caplog.text

    now = datetime.now(UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE request_processes
            SET status = 'waiting_for_release', monitoring_enabled = 1,
                next_search_at = ?, active_request_attempt_id = NULL
            WHERE id = ?
            """,
            ((now - timedelta(minutes=1)).isoformat(), request_process_id),
        )
    recovered_searches: list[int] = []
    restarted = _runtime(database_path, tmp_path / "library", [])
    restarted._scheduler._search_request = lambda current_id: (  # type: ignore[attr-defined]
        recovered_searches.append(current_id) or {"accepted_count": 0}
    )
    _recovered, enqueued = restarted._scheduler.recover_and_schedule(now=now)
    result = restarted._scheduler.run_once(now=now)
    assert enqueued == 1
    assert result.completed_jobs == 1
    assert recovered_searches == [request_process_id]
