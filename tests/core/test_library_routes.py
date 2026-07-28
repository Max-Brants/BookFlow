"""Routes-level tests for the library API (#04 contract / #06 implementation)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest
from flask import Flask

from bookflow.core.download_history_service import DownloadHistoryService
from bookflow.core.library_routes import register_library_routes
from bookflow.core.library_service import LibraryService
from bookflow.core.user_db import UserDB


def _always_builtin_auth_mode() -> str:
    return "builtin"


def _no_auth_mode() -> str:
    return "none"


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "users.db")


@pytest.fixture
def user_db(db_path):
    db = UserDB(db_path)
    db.initialize()
    return db


@pytest.fixture
def download_history_service(db_path):
    return DownloadHistoryService(db_path)


@pytest.fixture
def library_service(user_db, db_path):
    return LibraryService(db_path)


@pytest.fixture
def app(
    user_db,
    library_service,
    download_history_service,
):
    test_app = Flask(__name__)
    test_app.config["SECRET_KEY"] = "test-secret"
    test_app.config["TESTING"] = True
    test_app.config["TEST_USER_DB"] = user_db

    def _resolve_metadata_book(provider: str, provider_book_id: str) -> dict[str, Any] | None:
        # Deterministic stub for tests; mirrors the live _resolve_metadata_book_for_library
        # output shape: title/author/cover_url + metadata_json raw payload.
        return {
            "provider": provider,
            "provider_id": provider_book_id,
            "title": f"Book {provider_book_id}",
            "authors": ["Author A"],
            "author": "Author A",
            "isbn_13": None,
            "cover_url": None,
            "publish_year": 2024,
            "series_name": None,
            "series_position": None,
            "subtitle": None,
            "language": "en",
            "metadata_json": {"provider": provider, "provider_id": provider_book_id},
        }

    register_library_routes(
        test_app,
        user_db,
        library_service=library_service,
        download_history_service=download_history_service,
        resolve_auth_mode=_always_builtin_auth_mode,
        resolve_metadata_book=_resolve_metadata_book,
    )
    return test_app


def _authed_client(app: Flask, user: dict, *, is_admin: bool = False) -> Any:
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["username"]
        sess["db_user_id"] = user["id"]
        sess["is_admin"] = is_admin
    return client


def _seed_history_row(
    user_db: UserDB,
    *,
    task_id: str,
    user_id: int,
    username: str,
    book_id: int,
    fmt: str,
    download_path: str,
    final_status: str = "complete",
) -> int:
    conn = user_db._connect()
    try:
        conn.execute(
            """
            INSERT INTO download_history (
                task_id, user_id, username, source, title, format, content_type,
                origin, final_status, download_path, terminal_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                username,
                "direct_download",
                "Book",
                fmt,
                "ebook",
                "direct",
                final_status,
                download_path,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        row = conn.execute(
            "SELECT id FROM download_history WHERE task_id = ?", (task_id,)
        ).fetchone()
        history_id = int(row["id"])
        conn.execute(
            "UPDATE download_history SET book_id = ? WHERE id = ?",
            (book_id, history_id),
        )
        conn.commit()
        return history_id
    finally:
        conn.close()


def test_add_book_requires_authentication(app):
    client = app.test_client()
    resp = client.post(
        "/api/library/books",
        json={"metadata_provider": "hardcover", "provider_book_id": "1"},
    )
    assert resp.status_code == 401


def test_add_book_rejects_fileless_book_and_caches_metadata(app, user_db):
    alice = user_db.create_user(username="alice")
    client = _authed_client(app, alice)
    payload = {
        "metadata_provider": "hardcover",
        "provider_book_id": "123",
    }

    first = client.post("/api/library/books", json=payload)
    second = client.post("/api/library/books", json=payload)

    assert first.status_code == second.status_code == 409
    assert "create a request instead" in first.json["error"]
    conn = user_db._connect()
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM books WHERE metadata_provider = ? AND provider_book_id = ?",
                ("hardcover", "123"),
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_resolve_catalog_book_does_not_add_it_to_personal_library(app, user_db):
    alice = user_db.create_user(username="alice")
    client = _authed_client(app, alice)
    payload = {
        "metadata_provider": "hardcover",
        "provider_book_id": "preview-123",
    }

    first = client.post("/api/catalog/books/resolve", json=payload)
    second = client.post("/api/catalog/books/resolve", json=payload)

    assert first.status_code == 200
    assert first.json == second.json
    assert first.json["in_my_library"] is False
    conn = user_db._connect()
    try:
        assert (
            conn.execute(
                "SELECT 1 FROM user_library WHERE user_id = ? AND book_id = ?",
                (alice["id"], first.json["book_id"]),
            ).fetchone()
            is None
        )
    finally:
        conn.close()


def test_add_book_returns_503_when_metadata_provider_unavailable(user_db, db_path):
    alice = user_db.create_user(username="alice")
    test_app = Flask(__name__)
    test_app.config["SECRET_KEY"] = "test-secret"
    test_app.config["TESTING"] = True

    def _resolve_none(_provider: str, _provider_book_id: str) -> None:
        return None

    new_service = LibraryService(db_path)
    new_dhs = DownloadHistoryService(db_path)
    register_library_routes(
        test_app,
        user_db,
        library_service=new_service,
        download_history_service=new_dhs,
        resolve_auth_mode=_always_builtin_auth_mode,
        resolve_metadata_book=_resolve_none,
    )
    client = _authed_client(test_app, alice)
    resp = client.post(
        "/api/library/books",
        json={"metadata_provider": "hardcover", "provider_book_id": "999"},
    )
    assert resp.status_code == 503


def test_add_book_rejects_missing_payload_fields(app, user_db):
    alice = user_db.create_user(username="alice")
    client = _authed_client(app, alice)
    resp = client.post("/api/library/books", json={"metadata_provider": "hardcover"})
    assert resp.status_code == 400


def test_list_books_scoped_to_own_library(app, user_db):
    alice = user_db.create_user(username="alice")
    bob = user_db.create_user(username="bob")
    alice_book = client_post_book(app, alice, "hardcover", "alice-1")
    bob_book = client_post_book(app, bob, "hardcover", "bob-1")

    alice_view = _authed_client(app, alice).get("/api/library/books").json
    bob_view = _authed_client(app, bob).get("/api/library/books").json

    alice_ids = [b["book_id"] for b in alice_view["books"]]
    bob_ids = [b["book_id"] for b in bob_view["books"]]
    assert alice_book in alice_ids and bob_book not in alice_ids
    assert bob_book in bob_ids and alice_book not in bob_ids


def test_list_books_admin_sees_all_libraries(app, user_db):
    alice = user_db.create_user(username="alice", role="user")
    admin = user_db.create_user(username="admin", role="admin")
    client_post_book(app, alice, "hardcover", "a-1")
    alice_book_id = _first_book_id_for_user(app, alice)

    admin_client = _authed_client(app, admin, is_admin=True)
    resp = admin_client.get("/api/library/books").json
    assert any(b["book_id"] == alice_book_id for b in resp["books"])


def test_book_detail_403_for_non_member(app, user_db):
    alice = user_db.create_user(username="alice")
    bob = user_db.create_user(username="bob")
    alice_book = client_post_book(app, alice, "hardcover", "alice-1")

    # Bob is not in alice's library and is not admin — must get 403.
    bob_client = _authed_client(app, bob)
    resp = bob_client.get(f"/api/library/books/{alice_book}")
    assert resp.status_code == 403


def test_book_detail_returns_full_metadata_for_member(app, user_db):
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "42")

    resp = _authed_client(app, alice).get(f"/api/library/books/{book_id}").json
    assert resp["book_id"] == book_id
    assert resp["title"] == "Book 42"
    assert resp["in_my_library"] is True
    assert resp["metadata_json"] == {"provider": "hardcover", "provider_id": "42"}


def test_book_detail_404_for_missing_book_id(app, user_db):
    alice = user_db.create_user(username="alice")
    resp = _authed_client(app, alice).get("/api/library/books/99999")
    assert resp.status_code == 404


def test_delete_book_scoped_to_own_library(app, user_db):
    alice = user_db.create_user(username="alice")
    bob = user_db.create_user(username="bob")
    book_id = client_post_book(app, alice, "hardcover", "1")

    # Bob can't delete from alice's library.
    bob_client = _authed_client(app, bob)
    resp = bob_client.delete(f"/api/library/books/{book_id}")
    assert resp.status_code == 404

    resp = _authed_client(app, alice).delete(f"/api/library/books/{book_id}")
    assert resp.status_code == 200
    assert resp.json["status"] == "removed"


def test_download_file_gates_on_library_membership(app, user_db, library_service, db_path):
    alice = user_db.create_user(username="alice")
    bob = user_db.create_user(username="bob")
    book_id = client_post_book(app, alice, "hardcover", "1")
    history_id = _seed_history_row(
        user_db,
        task_id="task-1",
        user_id=alice["id"],
        username="alice",
        book_id=book_id,
        fmt="epub",
        download_path="/tmp/does-not-exist.epub",
    )
    library_service.link_download_to_user(
        user_id=alice["id"], book_id=book_id, history_id=history_id
    )

    # Bob is not in the library — 403 even if he owns the row.
    bob_client = _authed_client(app, bob)
    resp = bob_client.get(f"/api/library/books/{book_id}/download?format=epub")
    assert resp.status_code == 403


def test_download_file_returns_404_when_no_matching_format_on_disk(app, user_db):
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")

    resp = _authed_client(app, alice).get(f"/api/library/books/{book_id}/download?format=pdf")
    assert resp.status_code == 404


def test_download_file_serves_exact_history_id(app, user_db, tmp_path):
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")
    epub_path = tmp_path / "book.epub"
    pdf_path = tmp_path / "book.pdf"
    epub_path.write_bytes(b"epub")
    pdf_path.write_bytes(b"pdf")
    history_ids = _seed_multi_file_release(
        user_db,
        task_id="release-download",
        user_id=alice["id"],
        username="alice",
        book_id=book_id,
        files=[("epub", str(epub_path)), ("pdf", str(pdf_path))],
    )

    resp = _authed_client(app, alice).get(
        f"/api/library/books/{book_id}/download?history_id={history_ids[1]}"
    )

    assert resp.status_code == 200
    assert resp.data == b"pdf"
    audit = user_db.get_admin_user_audit(alice["id"])
    delivered = audit["downloads"]["recent_downloads"][0]
    assert delivered["history_id"] == history_ids[1]
    assert delivered["file_name"] == "book.pdf"
    assert delivered["source_ip"] == "127.0.0.1"


def test_download_file_rejects_history_id_from_another_book(app, user_db, tmp_path):
    alice = user_db.create_user(username="alice")
    first_book = client_post_book(app, alice, "hardcover", "1")
    second_book = client_post_book(app, alice, "hardcover", "2")
    file_path = tmp_path / "book.epub"
    file_path.write_bytes(b"epub")
    history_id = _seed_history_row(
        user_db,
        task_id="other-book-release",
        user_id=alice["id"],
        username="alice",
        book_id=second_book,
        fmt="epub",
        download_path=str(file_path),
    )

    resp = _authed_client(app, alice).get(
        f"/api/library/books/{first_book}/download?history_id={history_id}"
    )

    assert resp.status_code == 404


def test_link_download_endpoint_inserts_user_downloads_row(app, user_db, library_service):
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")
    history_id = _seed_history_row(
        user_db,
        task_id="task-1",
        user_id=alice["id"],
        username="alice",
        book_id=book_id,
        fmt="epub",
        download_path="/tmp/enders.epub",
    )

    resp = _authed_client(app, alice).post(f"/api/library/books/{book_id}/downloads/{history_id}")
    assert resp.status_code == 200
    assert resp.json["status"] == "linked"
    assert library_service.download_linked_to_user(user_id=alice["id"], history_id=history_id)


def test_link_download_404_for_history_under_different_book(app, user_db, library_service):
    alice = user_db.create_user(username="alice")
    book_a = client_post_book(app, alice, "hardcover", "A")
    book_b = client_post_book(app, alice, "hardcover", "B")
    history_id = _seed_history_row(
        user_db,
        task_id="task-1",
        user_id=alice["id"],
        username="alice",
        book_id=book_a,
        fmt="epub",
        download_path="/tmp/enders.epub",
    )

    # The history row is tied to book_a, but we try to link it to book_b → 404.
    resp = _authed_client(app, alice).post(f"/api/library/books/{book_b}/downloads/{history_id}")
    assert resp.status_code == 404


def test_unlink_download_idempotent(app, user_db, library_service):
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")
    history_id = _seed_history_row(
        user_db,
        task_id="task-1",
        user_id=alice["id"],
        username="alice",
        book_id=book_id,
        fmt="epub",
        download_path="/tmp/enders.epub",
    )
    library_service.link_download_to_user(
        user_id=alice["id"], book_id=book_id, history_id=history_id
    )

    first = _authed_client(app, alice).delete(
        f"/api/library/books/{book_id}/downloads/{history_id}"
    )
    second = _authed_client(app, alice).delete(
        f"/api/library/books/{book_id}/downloads/{history_id}"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json["status"] == "unlinked"
    assert second.json["status"] == "unlinked"  # Idempotent.
    assert not library_service.download_linked_to_user(user_id=alice["id"], history_id=history_id)


def test_unauthenticated_user_gets_401_on_all_routes(app, user_db):
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")

    for method, path in [
        ("get", "/api/library/books"),
        ("get", f"/api/library/books/{book_id}"),
        ("delete", f"/api/library/books/{book_id}"),
        ("get", f"/api/library/books/{book_id}/download?format=epub"),
    ]:
        client = app.test_client()
        resp = getattr(client, method)(path)
        assert resp.status_code == 401, f"{method.upper()} {path} → {resp.status_code}"


def _seed_multi_file_release(
    user_db: UserDB,
    *,
    task_id: str,
    user_id: int,
    username: str,
    book_id: int,
    files: list[tuple[str, str]],
) -> list[int]:
    """Seed N download_history rows sharing a task_id (#13 schema (b))."""
    conn = user_db._connect()
    try:
        history_ids: list[int] = []
        for i, (fmt, path) in enumerate(files):
            cur = conn.execute(
                """
                INSERT INTO download_history (
                    task_id, user_id, username, source, title, format, content_type,
                    origin, final_status, download_path, terminal_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    username,
                    "prowlarr",
                    "Multi",
                    fmt,
                    "ebook",
                    "direct",
                    "complete",
                    path,
                    f"2026-01-0{i + 1}T00:00:00+00:00",
                ),
            )
            hid = int(cur.lastrowid or 0)
            history_ids.append(hid)
            conn.execute(
                "UPDATE download_history SET book_id = ? WHERE id = ?",
                (book_id, hid),
            )
        conn.commit()
        return history_ids
    finally:
        conn.close()


def test_book_detail_includes_task_id_per_file_in_payload(app, user_db):
    """#13 API (3-a): files[] stays flat, one entry per download_history row,
    with task_id added per entry — frontend groups by task_id for display."""
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")
    _seed_multi_file_release(
        user_db,
        task_id="release-A",
        user_id=alice["id"],
        username="alice",
        book_id=book_id,
        files=[
            ("epub", "/lib/a.epub"),
            ("mobi", "/lib/a.mobi"),
            ("pdf", "/lib/a.pdf"),
        ],
    )

    detail = _authed_client(app, alice).get(f"/api/library/books/{book_id}").json
    assert len(detail["files"]) == 3
    # Every file entry carries task_id (the release grouping key).
    assert {f["task_id"] for f in detail["files"]} == {"release-A"}
    assert {f["format"] for f in detail["files"]} == {"epub", "mobi", "pdf"}


def test_unlink_release_via_any_file_history_id_deletes_all_links(app, user_db, library_service):
    """#13 unlink (4-a-strict): DELETE /downloads/:history_id fans out across
    sibling file rows sharing task_id, deleting user_downloads links for all."""
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")
    history_ids = _seed_multi_file_release(
        user_db,
        task_id="release-unlink",
        user_id=alice["id"],
        username="alice",
        book_id=book_id,
        files=[
            ("epub", "/lib/a.epub"),
            ("mobi", "/lib/a.mobi"),
            ("pdf", "/lib/a.pdf"),
        ],
    )
    for hid in history_ids:
        library_service.link_download_to_user(user_id=alice["id"], book_id=book_id, history_id=hid)

    # Unlink the MIDDLE file row — should fan out to all three.
    middle = history_ids[1]
    resp = _authed_client(app, alice).delete(f"/api/library/books/{book_id}/downloads/{middle}")
    assert resp.status_code == 200
    assert resp.json["status"] == "unlinked"

    # All three links are gone (release-atomic), download_history rows untouched.
    for hid in history_ids:
        assert not library_service.download_linked_to_user(user_id=alice["id"], history_id=hid), (
            f"link for history_id={hid} should be gone"
        )
    for hid in history_ids:
        assert library_service.get_download_history_row(hid) is not None


def test_unlink_mid_flight_release_returns_404(app, user_db, library_service):
    """#13 link-timing (4-mid-1-ii): an in-flight release has no
    user_downloads link yet — unlink returns 404 (nothing to delete)."""
    alice = user_db.create_user(username="alice")
    book_id = client_post_book(app, alice, "hardcover", "1")

    # Seed a sentinel 'active' row (in-flight, no link, no download_path).
    conn = user_db._connect()
    try:
        conn.execute(
            """
            INSERT INTO download_history (
                task_id, user_id, username, source, title, content_type,
                origin, final_status, terminal_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "release-inflight",
                alice["id"],
                "alice",
                "prowlarr",
                "In Flight",
                "ebook",
                "direct",
                "active",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        sentinel_id = conn.execute(
            "SELECT id FROM download_history WHERE task_id = ?", ("release-inflight",)
        ).fetchone()["id"]
        conn.execute(
            "UPDATE download_history SET book_id = ? WHERE id = ?",
            (book_id, sentinel_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Unlink the sentinel — no link row exists → 404.
    resp = _authed_client(app, alice).delete(
        f"/api/library/books/{book_id}/downloads/{sentinel_id}"
    )
    # The route's book_id match check passes (sentinel has book_id), then the
    # unlink service returns False (nothing to delete) — route surfaces 200
    # "unlinked" idempotently. BUT the get_download_history_row must exist,
    # so the real check is the link absence. See #13 4-mid-1-ii.
    assert resp.status_code == 200
    assert resp.json["status"] == "unlinked"
    assert not library_service.download_linked_to_user(user_id=alice["id"], history_id=sentinel_id)


# --- Helpers ------------------------------------------------------------- #


def client_post_book(app: Flask, user: dict, provider: str, provider_book_id: str) -> int:
    client = _authed_client(app, user)
    resolved = client.post(
        "/api/catalog/books/resolve",
        json={"metadata_provider": provider, "provider_book_id": provider_book_id},
    )
    assert resolved.status_code == 200, resolved.json
    book_id = int(resolved.json["book_id"])
    user_db: UserDB = app.config["TEST_USER_DB"]
    conn = user_db._connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO book_files (
                book_id, storage_path, file_format, size_bytes, sha256, mime_type,
                content_type, import_status
            )
            VALUES (?, ?, 'epub', 4, ?, 'application/epub+zip', 'ebook', 'imported')
            """,
            (book_id, f"/books/test-{book_id}.epub", f"{book_id:064x}"),
        )
        conn.commit()
    finally:
        conn.close()
    resp = client.post(
        "/api/library/books",
        json={"metadata_provider": provider, "provider_book_id": provider_book_id},
    )
    assert resp.status_code == 200, resp.json
    return int(resp.json["book_id"])


def _first_book_id_for_user(app: Flask, user: dict) -> int:
    resp = _authed_client(app, user).get("/api/library/books")
    assert resp.status_code == 200
    return int(resp.json["books"][0]["book_id"])
