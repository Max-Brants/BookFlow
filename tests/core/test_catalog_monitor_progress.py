"""Contract tests for the shared catalog, monitors and reading progress."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask

from bookflow.core.catalog_monitor_service import CatalogMonitorService
from bookflow.core.library_service import LibraryService
from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor, register_v1_api


def _database(tmp_path: Path) -> tuple[Path, int, int]:
    path = tmp_path / "users.db"
    db = UserDB(str(path))
    db.initialize()
    user = db.create_user(username="reader")
    other = db.create_user(username="other")
    with sqlite3.connect(path) as conn:
        book_id = conn.execute(
            "INSERT INTO books(metadata_provider, provider_book_id, title, author, series_name, metadata_json) VALUES ('test', 'one', 'The Dune', 'Frank Herbert', 'Dune', '{\"description\":\"desert planet\"}')"
        ).lastrowid
        conn.execute(
            "INSERT INTO user_library(user_id, book_id) VALUES (?, ?)", (user["id"], book_id)
        )
        conn.execute(
            "INSERT INTO user_library(user_id, book_id) VALUES (?, ?)", (other["id"], book_id)
        )
        file_id = conn.execute(
            """INSERT INTO book_files(book_id, storage_path, file_format, size_bytes, sha256, import_status)
               VALUES (?, ?, 'epub', 1, ?, 'imported')""",
            (book_id, str(tmp_path / "reader.epub"), "a" * 64),
        ).lastrowid
        conn.execute(
            "INSERT INTO user_file_entitlements(user_id, file_id) VALUES (?, ?)",
            (user["id"], file_id),
        )
    return path, int(user["id"]), int(book_id)


def test_catalog_recent_is_deduplicated_and_fts_searches(tmp_path: Path) -> None:
    path, _user_id, book_id = _database(tmp_path)
    service = CatalogMonitorService(str(path))

    recent = service.recent(offset=0, limit=50)
    searched = service.catalog_books(
        query="desert", author_id=None, series_id=None, offset=0, limit=50
    )
    assert recent["total"] == 1
    assert recent["items"][0]["id"] == book_id
    assert searched["items"][0]["id"] == book_id
    assert (
        service.catalog_entities(entity="authors", query="Herbert", offset=0, limit=10)["items"][0][
            "book_count"
        ]
        == 1
    )


def test_catalog_recent_uses_file_import_time_without_library_membership(tmp_path: Path) -> None:
    path = tmp_path / "recent-import.db"
    db = UserDB(str(path))
    db.initialize()
    with sqlite3.connect(path) as conn:
        book_id = conn.execute(
            """
            INSERT INTO books(metadata_provider, provider_book_id, title, metadata_json)
            VALUES ('test', 'recent-import', 'Recently imported', '{}')
            """
        ).lastrowid
        conn.execute(
            """
            INSERT INTO book_files(
                book_id, storage_path, file_format, size_bytes, sha256,
                import_status, imported_at
            ) VALUES (?, ?, 'epub', 1, ?, 'imported', '2026-07-28T10:00:00+00:00')
            """,
            (book_id, str(tmp_path / "recent.epub"), "b" * 64),
        )

    recent = CatalogMonitorService(str(path)).recent(offset=0, limit=10)

    assert recent["total"] == 1
    assert recent["items"][0]["id"] == book_id
    assert recent["items"][0]["added_at"] == "2026-07-28T10:00:00+00:00"


def test_catalog_hides_library_metadata_without_an_imported_file(tmp_path: Path) -> None:
    path, user_id, _book_id = _database(tmp_path)
    with sqlite3.connect(path) as conn:
        hidden_id = conn.execute(
            """INSERT INTO books(metadata_provider, provider_book_id, title, author, metadata_json)
               VALUES ('test', 'pending', 'Pending import', 'No Files', '{}')"""
        ).lastrowid
        conn.execute(
            "INSERT INTO user_library(user_id, book_id) VALUES (?, ?)", (user_id, hidden_id)
        )
    service = CatalogMonitorService(str(path))

    assert (
        service.catalog_books(query=None, author_id=None, series_id=None, offset=0, limit=50)[
            "total"
        ]
        == 1
    )
    assert service.recent(offset=0, limit=50)["total"] == 1
    assert all(
        item["name"] != "No Files"
        for item in service.catalog_entities(entity="authors", query=None, offset=0, limit=50)[
            "items"
        ]
    )


def test_catalog_groups_legacy_rows_with_the_same_isbn(tmp_path: Path) -> None:
    path, user_id, first_book_id = _database(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE books SET isbn_13 = '9789026175220' WHERE id = ?",
            (first_book_id,),
        )
        duplicate_id = int(
            conn.execute(
                """
                INSERT INTO books (
                    metadata_provider, provider_book_id, title, author, isbn_13, metadata_json
                ) VALUES ('other', 'duplicate-edition', 'The Dune duplicate',
                          'Frank Herbert', '9789026175220', '{}')
                """
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO user_library(user_id, book_id) VALUES (?, ?)",
            (user_id, duplicate_id),
        )
        conn.execute(
            """
            INSERT INTO book_files (
                book_id, storage_path, file_format, size_bytes, sha256, import_status
            ) VALUES (?, ?, 'pdf', 2, ?, 'imported')
            """,
            (duplicate_id, str(tmp_path / "duplicate.pdf"), "b" * 64),
        )

    service = CatalogMonitorService(str(path))
    catalog = service.catalog_books(query=None, author_id=None, series_id=None, offset=0, limit=50)
    recent = service.recent(offset=0, limit=50)

    assert catalog["total"] == 1
    assert [item["id"] for item in catalog["items"]] == [first_book_id]
    assert recent["total"] == 1


def test_provider_author_order_is_materialized_in_catalog_relations(tmp_path: Path) -> None:
    path, _user_id, _book_id = _database(tmp_path)
    created = LibraryService(str(path)).upsert_book_from_metadata(
        metadata_provider="test",
        provider_book_id="multi-author",
        title="Shared Work",
        author="First Writer",
        subtitle=None,
        publish_year=2026,
        isbn_13=None,
        cover_url=None,
        series_name="Shared Series",
        series_position=2.0,
        language="en",
        metadata_json={"authors": ["First Writer", "Second Writer"]},
    )
    with sqlite3.connect(path) as conn:
        authors = conn.execute(
            """
            SELECT ca.name
            FROM book_catalog_authors bca
            JOIN catalog_authors ca ON ca.id = bca.author_id
            WHERE bca.book_id = ?
            ORDER BY bca.position
            """,
            (created["id"],),
        ).fetchall()
    assert authors == [("First Writer",), ("Second Writer",)]


def test_monitor_is_owned_and_progress_is_monotone(tmp_path: Path) -> None:
    path, user_id, book_id = _database(tmp_path)
    service = CatalogMonitorService(str(path))
    monitor = service.create_monitor(
        user_id=user_id,
        payload={
            "type": "author",
            "provider": "openlibrary",
            "provider_id": "/authors/OL123A",
            "query": "Frank Herbert",
            "search_profile": {
                "language": "en",
                "limit": 25,
                "request_process_profile": {"formats": ["epub"]},
            },
        },
        is_admin=False,
        library_capability="download-capable",
    )
    assert monitor["provider_id"] == "/authors/OL123A"
    assert monitor["search_profile"]["limit"] == 25
    assert service.list_monitors(user_id=user_id, offset=0, limit=10)["total"] == 1
    updated_monitor = service.update_monitor(
        user_id=user_id,
        monitor_id=monitor["id"],
        payload={"scan_interval_seconds": 7200, "search_profile": {"limit": 10}},
        is_admin=False,
        library_capability="download-capable",
    )
    assert updated_monitor is not None
    assert updated_monitor["scan_interval_seconds"] == 7200
    assert updated_monitor["search_profile"] == {"limit": 10}
    assert service.schedule_scan(user_id=user_id, monitor_id=monitor["id"])
    assert (
        service.set_progress(user_id=user_id, book_id=book_id, progress=37, source="web")["active"]
        == 1
    )
    try:
        service.set_progress(user_id=user_id, book_id=book_id, progress=2, source="web")
    except ValueError as exc:
        assert "decrease" in str(exc)
    else:
        raise AssertionError("a non-reset decrease must be rejected")
    completed = service.set_progress(user_id=user_id, book_id=book_id, progress=100, source="web")
    assert completed["active"] == 0
    assert service.list_active_progress(user_id=user_id, offset=0, limit=10)["total"] == 0


def test_request_only_user_cannot_escalate_monitor_action(tmp_path: Path) -> None:
    path, user_id, _book_id = _database(tmp_path)
    service = CatalogMonitorService(str(path))
    monitor = service.create_monitor(
        user_id=user_id,
        payload={"type": "author", "provider": "openlibrary", "query": "Frank Herbert"},
        is_admin=False,
        library_capability="request-only",
    )
    try:
        service.update_monitor(
            user_id=user_id,
            monitor_id=monitor["id"],
            payload={"action": "auto_acquire"},
            is_admin=False,
            library_capability="request-only",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("request-only users must not enable auto request_process")


def test_monitor_owner_can_ignore_and_restore_discovery(tmp_path: Path) -> None:
    path, user_id, _book_id = _database(tmp_path)
    service = CatalogMonitorService(str(path))
    monitor = service.create_monitor(
        user_id=user_id,
        payload={"type": "author", "provider": "openlibrary", "query": "Frank Herbert"},
        is_admin=False,
        library_capability="request-only",
    )
    with sqlite3.connect(path) as conn:
        discovery_id = conn.execute(
            """INSERT INTO monitor_discoveries(monitor_id, provider, provider_book_id)
               VALUES (?, 'openlibrary', 'OL123')""",
            (monitor["id"],),
        ).lastrowid
    assert discovery_id is not None

    ignored = service.set_discovery_state(
        user_id=user_id, monitor_id=monitor["id"], discovery_id=discovery_id, state="ignored"
    )
    restored = service.set_discovery_state(
        user_id=user_id, monitor_id=monitor["id"], discovery_id=discovery_id, state="discovered"
    )

    assert ignored is not None and ignored["state"] == "ignored"
    assert restored is not None and restored["state"] == "discovered"


def test_v1_progress_is_user_scoped(tmp_path: Path) -> None:
    path, user_id, book_id = _database(tmp_path)
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_v1_api(app, database_path=path, resolve_actor=lambda: V1Actor(user_id))
    client = app.test_client()

    updated = client.patch(f"/api/v1/users/me/reading-progress/{book_id}", json={"progress": 42})
    non_boolean_reset = client.patch(
        f"/api/v1/users/me/reading-progress/{book_id}",
        json={"progress": 10, "reset": "false"},
    )
    active = client.get("/api/v1/users/me/reading-progress?active=true")
    recent = client.get("/api/v1/catalog/recent")

    assert updated.status_code == 200
    assert updated.json["progress"]["progress"] == 42
    assert non_boolean_reset.status_code == 400
    assert non_boolean_reset.json["error"]["code"] == "invalid_progress"
    assert active.status_code == 200
    assert active.json["total"] == 1
    assert active.json["items"][0]["book_id"] == book_id
    assert active.json["items"][0]["progress"] == 42.0
    assert active.json["items"][0]["active"] == 1
    assert active.json["items"][0]["title"] == "The Dune"
    assert recent.status_code == 200
    assert recent.json["total"] == 1


def test_personal_library_search_filters_sort_and_total_are_server_side(tmp_path: Path) -> None:
    path, user_id, book_id = _database(tmp_path)
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_v1_api(app, database_path=path, resolve_actor=lambda: V1Actor(user_id))
    client = app.test_client()

    result = client.get(
        "/api/v1/library/books?q=desert&file_state=with-files&format=epub&sort=title&limit=1"
    )
    invalid = client.get("/api/v1/library/books?sort=unknown")

    assert result.status_code == 200
    assert result.json["total"] == 1
    assert result.json["items"][0]["id"] == book_id
    assert result.json["offset"] == 0
    assert result.json["limit"] == 1
    assert invalid.status_code == 400
    assert invalid.json["error"]["code"] == "invalid_library_query"
