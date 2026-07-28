"""Contract tests for the personal v1 dashboard request feed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask

from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor, register_v1_api


def _database(tmp_path: Path) -> tuple[Path, int, int]:
    path = tmp_path / "requests.sqlite"
    db = UserDB(str(path))
    db.initialize()
    reader = db.create_user(username="reader")
    other = db.create_user(username="other")
    return path, int(reader["id"]), int(other["id"])


def _insert_book(conn: sqlite3.Connection, *, provider_id: str, title: str, cover_url: str) -> int:
    cursor = conn.execute(
        """
        INSERT INTO books (metadata_provider, provider_book_id, title, author, cover_url)
        VALUES ('test', ?, ?, 'Book Author', ?)
        """,
        (provider_id, title, cover_url),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_request(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    book_id: int,
    request_id: int,
    created_at: str,
    status: str = "pending_approval",
    request_process_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO requests (
            id, user_id, book_id, request_process_id, content_type, profile_hash,
            profile_snapshot_json, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'ebook', ?, '{}', ?, ?, ?)
        """,
        (
            request_id,
            user_id,
            book_id,
            request_process_id,
            "a" * 64,
            status,
            created_at,
            created_at,
        ),
    )


def _client(path: Path, actor: V1Actor | None):
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_v1_api(app, database_path=path, resolve_actor=lambda: actor)
    return app.test_client()


def test_current_user_requests_requires_authentication(tmp_path: Path) -> None:
    path, _reader_id, _other_id = _database(tmp_path)

    response = _client(path, None).get("/api/v1/users/me/requests")

    assert response.status_code == 401
    assert response.json["error"]["code"] == "unauthorized"


def test_current_user_requests_are_scoped_sorted_and_include_book_data(tmp_path: Path) -> None:
    path, reader_id, other_id = _database(tmp_path)
    with sqlite3.connect(path) as conn:
        oldest_book = _insert_book(
            conn, provider_id="oldest", title="Oldest owned", cover_url="https://covers/old.jpg"
        )
        newest_book = _insert_book(
            conn, provider_id="newest", title="Newest owned", cover_url="https://covers/new.jpg"
        )
        private_book = _insert_book(
            conn,
            provider_id="private",
            title="Other reader",
            cover_url="https://covers/private.jpg",
        )
        conn.execute(
            """
            INSERT INTO request_processes (id, book_id, content_type, profile_hash, profile_snapshot_json,
                                      status, monitoring_enabled)
            VALUES (90, ?, 'ebook', ?, '{}', 'downloading', 1)
            """,
            (newest_book, "b" * 64),
        )
        _insert_request(
            conn,
            user_id=reader_id,
            book_id=oldest_book,
            request_id=10,
            created_at="2026-01-01T09:00:00+00:00",
            status="fulfilled",
        )
        _insert_request(
            conn,
            user_id=reader_id,
            book_id=newest_book,
            request_id=11,
            created_at="2026-01-02T09:00:00+00:00",
            request_process_id=90,
        )
        _insert_request(
            conn,
            user_id=other_id,
            book_id=private_book,
            request_id=12,
            created_at="2026-01-03T09:00:00+00:00",
        )

    response = _client(path, V1Actor(reader_id)).get("/api/v1/users/me/requests")

    assert response.status_code == 200
    assert response.json["total"] == 2
    assert response.json["offset"] == 0
    assert response.json["limit"] == 10
    assert [item["id"] for item in response.json["items"]] == [11, 10]
    newest, oldest = response.json["items"]
    assert newest == {
        "id": 11,
        "book_id": newest_book,
        "title": "Newest owned",
        "author": "Book Author",
        "cover_url": "https://covers/new.jpg",
        "request_process_id": 90,
        "content_type": "ebook",
        "status": "pending_approval",
        "add_to_kobo_when_available": 0,
        "profile_id": None,
        "profile_name": None,
        "delivery_state": "downloading",
        "created_at": "2026-01-02T09:00:00+00:00",
        "updated_at": "2026-01-02T09:00:00+00:00",
    }
    assert oldest["delivery_state"] == "available"
    assert all(item["title"] != "Other reader" for item in response.json["items"])


def test_current_user_requests_paginates_newest_first(tmp_path: Path) -> None:
    path, reader_id, _other_id = _database(tmp_path)
    with sqlite3.connect(path) as conn:
        for request_id in range(1, 4):
            book_id = _insert_book(
                conn,
                provider_id=f"book-{request_id}",
                title=f"Book {request_id}",
                cover_url=f"https://covers/{request_id}.jpg",
            )
            _insert_request(
                conn,
                user_id=reader_id,
                book_id=book_id,
                request_id=request_id,
                created_at=f"2026-01-0{request_id}T09:00:00+00:00",
            )

    response = _client(path, V1Actor(reader_id)).get("/api/v1/users/me/requests?offset=1&limit=1")

    assert response.status_code == 200
    assert response.json["total"] == 3
    assert response.json["offset"] == 1
    assert response.json["limit"] == 1
    assert [item["id"] for item in response.json["items"]] == [2]
