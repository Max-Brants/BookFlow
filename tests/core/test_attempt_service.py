from __future__ import annotations

import sqlite3

from bookflow.core.attempt_policy import FailureCode, FailureDisposition
from bookflow.core.attempt_service import AttemptService
from bookflow.core.release_candidates import ReleaseCandidate, ReleaseProfile
from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.core.search_service import SearchService
from bookflow.core.user_db import UserDB


class FakeAdapter:
    def __init__(self):
        self.added = []

    def add(self, candidate, *, idempotency_key):
        self.added.append((candidate, idempotency_key))
        return f"job-{len(self.added)}"


def _seed(db_path):
    db = UserDB(str(db_path))
    db.initialize()
    admin = db.create_user(username="admin", role="admin")
    alice = db.create_user(username="alice")
    bob = db.create_user(username="bob")
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO books (metadata_provider, provider_book_id, title) VALUES ('t', '1', 'Dune')"
    )
    book_id = cursor.lastrowid
    conn.commit()
    conn.close()
    assert book_id is not None
    request_service = RequestWorkflowService(db_path)
    request_process_id = None
    request_ids = []
    for user in (alice, bob):
        request = request_service.create_request(
            user_id=user["id"],
            book_id=book_id,
            profile={"formats": ["epub"]},
        )
        request_ids.append(request["id"])
        _, request_process, _ = request_service.approve_request(
            request["id"],
            reviewer_user_id=admin["id"],
        )
        assert request_process is not None
        request_process_id = request_process["id"]
    assert request_process_id is not None
    SearchService(db_path).run_search(
        request_process_id,
        profile=ReleaseProfile(
            title="Dune",
            allowed_formats=("epub",),
            allowed_protocols=("torrent",),
        ),
        sources={
            "source": lambda: [
                ReleaseCandidate(
                    source="source",
                    indexer="one",
                    guid="best",
                    title="Dune",
                    format="epub",
                    protocol="torrent",
                    seeders=50,
                ),
                ReleaseCandidate(
                    source="source",
                    indexer="two",
                    guid="fallback",
                    title="Dune",
                    format="epub",
                    protocol="torrent",
                    seeders=10,
                ),
            ]
        },
    )
    return alice, bob, book_id, request_process_id, request_ids


def test_permanent_failure_blocks_first_candidate_and_next_starts(tmp_path):
    db_path = tmp_path / "users.db"
    _alice, _bob, _book_id, request_process_id, _request_ids = _seed(db_path)
    adapter = FakeAdapter()
    service = AttemptService(db_path)

    first = service.start_next_candidate(
        request_process_id,
        adapter_name="fake",
        adapter=adapter,
    )
    assert first is not None
    disposition = service.record_failure(first["id"], FailureCode.CORRUPT)
    second = service.start_next_candidate(
        request_process_id,
        adapter_name="fake",
        adapter=adapter,
    )

    assert disposition is FailureDisposition.BLOCK_CANDIDATE
    assert second is not None
    assert second["candidate_id"] != first["candidate_id"]
    assert adapter.added[0][1] != adapter.added[1][1]
    conn = sqlite3.connect(db_path)
    assert (
        conn.execute("SELECT COUNT(*) FROM blocked_releases WHERE unblocked_at IS NULL").fetchone()[
            0
        ]
        == 1
    )
    conn.close()


def test_transient_failure_schedules_same_candidate_retry_without_block(tmp_path):
    db_path = tmp_path / "users.db"
    _alice, _bob, _book_id, request_process_id, _request_ids = _seed(db_path)
    service = AttemptService(db_path)
    adapter = FakeAdapter()
    attempt = service.start_next_candidate(
        request_process_id,
        adapter_name="fake",
        adapter=adapter,
    )
    assert attempt is not None

    disposition = service.record_failure(attempt["id"], FailureCode.TIMEOUT)

    conn = sqlite3.connect(db_path)
    stored = conn.execute(
        "SELECT status, retry_count FROM request_attempts WHERE id = ?",
        (attempt["id"],),
    ).fetchone()
    blocks = conn.execute("SELECT COUNT(*) FROM blocked_releases").fetchone()[0]
    conn.close()
    assert disposition is FailureDisposition.RETRY_CANDIDATE
    assert stored == ("retry_scheduled", 1)
    assert blocks == 0

    retried = service.start_next_candidate(
        request_process_id,
        adapter_name="fake",
        adapter=adapter,
    )
    assert retried is not None
    assert retried["id"] == attempt["id"]
    assert retried["candidate_id"] == attempt["candidate_id"]
    assert adapter.added[0][1] == adapter.added[1][1]


def test_admin_selected_blocked_candidate_is_attempted_first(tmp_path):
    db_path = tmp_path / "users.db"
    _alice, _bob, _book_id, request_process_id, _request_ids = _seed(db_path)
    conn = sqlite3.connect(db_path)
    candidates = conn.execute(
        "SELECT id, fingerprint FROM release_candidates WHERE request_process_id = ? "
        "ORDER BY total_score ASC",
        (request_process_id,),
    ).fetchall()
    selected_id, selected_fingerprint = candidates[0]
    conn.execute(
        "INSERT INTO blocked_releases "
        "(fingerprint, scope, request_process_id, reason) VALUES (?, 'request_process', ?, 'bad')",
        (selected_fingerprint, request_process_id),
    )
    conn.execute(
        "UPDATE release_candidates SET selected_by = 1, selected_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (selected_id,),
    )
    conn.commit()
    conn.close()

    attempt = AttemptService(db_path).start_next_candidate(
        request_process_id,
        adapter_name="fake",
        adapter=FakeAdapter(),
    )

    assert attempt is not None
    assert attempt["candidate_id"] == selected_id


def test_completed_import_fulfils_all_recipients_and_grants_one_file(tmp_path):
    db_path = tmp_path / "users.db"
    alice, bob, book_id, request_process_id, request_ids = _seed(db_path)
    service = AttemptService(db_path)
    attempt = service.start_next_candidate(
        request_process_id,
        adapter_name="fake",
        adapter=FakeAdapter(),
    )
    assert attempt is not None
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """
        INSERT INTO book_files (
            book_id, storage_path, file_format, size_bytes, sha256, mime_type, import_status
        )
        VALUES (?, '/books/dune.epub', 'epub', 4, ?, 'application/epub+zip', 'imported')
        """,
        (book_id, "d" * 64),
    )
    file_id = cursor.lastrowid
    conn.commit()
    conn.close()
    assert file_id is not None

    fulfilled = service.complete_import(attempt["id"], file_id=file_id)

    conn = sqlite3.connect(db_path)
    entitlements = conn.execute(
        "SELECT user_id, file_id FROM user_file_entitlements ORDER BY user_id"
    ).fetchall()
    request_process_status = conn.execute(
        "SELECT status FROM request_processes WHERE id = ?",
        (request_process_id,),
    ).fetchone()[0]
    conn.close()
    assert sorted(fulfilled) == sorted(request_ids)
    assert entitlements == [(alice["id"], file_id), (bob["id"], file_id)]
    assert request_process_status == "completed"
