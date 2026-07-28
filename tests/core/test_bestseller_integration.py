from __future__ import annotations

import sqlite3

from flask import Flask

from bookflow.core.catalog_monitor_service import CatalogMonitorService
from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor, register_v1_api


def test_migration_adds_bestseller_storage_and_hidden_catalog_books(tmp_path) -> None:
    database_path = tmp_path / "users.db"
    database = UserDB(str(database_path))
    database.initialize()

    with sqlite3.connect(database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(books)").fetchall()}
        migration = connection.execute(
            "SELECT name, status FROM schema_migrations WHERE version = 13"
        ).fetchone()

    assert {
        "bestseller_sync_state",
        "bestseller_snapshots",
        "bestseller_entries",
        "bestseller_metadata_enrichment",
    } <= tables
    assert "catalog_visible" in columns
    assert migration == ("bestseller60-suggestions", "completed")


def test_request_does_not_promote_undownloaded_suggestion_into_catalog(tmp_path) -> None:
    database_path = tmp_path / "users.db"
    database = UserDB(str(database_path))
    database.initialize()
    reader = database.create_user(username="reader")

    with sqlite3.connect(database_path) as connection:
        book_id = connection.execute(
            """
            INSERT INTO books (
                metadata_provider, provider_book_id, title, author, isbn_13,
                catalog_visible
            )
            VALUES ('bestseller60', '9780306406157', 'Verborgen suggestie',
                    'Auteur', '9780306406157', 0)
            """
        ).lastrowid

    assert book_id is not None
    catalog = CatalogMonitorService(str(database_path))
    before = catalog.catalog_books(
        query=None,
        author_id=None,
        series_id=None,
        offset=0,
        limit=50,
    )
    assert before["items"] == []

    RequestWorkflowService(str(database_path)).create_request(
        user_id=int(reader["id"]),
        book_id=int(book_id),
        profile={"formats": ["epub"]},
    )

    after = catalog.catalog_books(
        query=None,
        author_id=None,
        series_id=None,
        offset=0,
        limit=50,
    )
    assert after["items"] == []


def test_authenticated_suggestion_api_returns_grouped_and_paged_lists(tmp_path) -> None:
    database_path = tmp_path / "users.db"
    database = UserDB(str(database_path))
    database.initialize()
    reader = database.create_user(username="reader")
    with sqlite3.connect(database_path) as connection:
        book_id = connection.execute(
            """
            INSERT INTO books (
                metadata_provider, provider_book_id, title, author, isbn_13,
                catalog_visible
            )
            VALUES ('bestseller60', '9780306406157', 'Suggestie',
                    'Auteur', '9780306406157', 0)
            """
        ).lastrowid
        snapshot_id = connection.execute(
            """
            INSERT INTO bestseller_snapshots (
                source_year, source_week, status, is_active, fetched_at, completed_at
            )
            VALUES (2026, 30, 'completed', 1, '2026-07-22T20:00:00+00:00',
                    '2026-07-22T20:00:00+00:00')
            """
        ).lastrowid
        connection.execute(
            """
            INSERT INTO bestseller_entries (
                snapshot_id, list_key, list_rank, isbn_13, book_id,
                source_title, source_author
            )
            VALUES (?, 'overall', 1, '9780306406157', ?, 'Suggestie', 'Auteur')
            """,
            (snapshot_id, book_id),
        )

    app = Flask(__name__)
    app.config["TESTING"] = True
    register_v1_api(
        app,
        database_path=database_path,
        resolve_actor=lambda: V1Actor(int(reader["id"])),
    )
    client = app.test_client()

    grouped = client.get("/api/v1/suggestions")
    paged = client.get("/api/v1/suggestions/overall?offset=0&limit=30")
    invalid = client.get("/api/v1/suggestions/unknown")

    assert grouped.status_code == 200
    assert grouped.json["snapshot"]["week"] == 30
    assert grouped.json["lists"][0]["total"] == 1
    assert grouped.json["lists"][0]["items"][0]["title"] == "Suggestie"
    assert "list_rank" not in grouped.json["lists"][0]["items"][0]
    assert paged.status_code == 200
    assert paged.json["label"] == "Bestseller 60"
    assert paged.json["total"] == 1
    assert invalid.status_code == 400
    assert invalid.json["error"]["code"] == "invalid_suggestion_list"


def test_admin_bestseller_status_and_manual_sync_are_durable_and_admin_only(tmp_path) -> None:
    database_path = tmp_path / "users.db"
    database = UserDB(str(database_path))
    database.initialize()
    admin = database.create_user(username="admin")

    with sqlite3.connect(database_path) as connection:
        snapshot_id = connection.execute(
            """
            INSERT INTO bestseller_snapshots (
                source_year, source_week, status, is_active, fetched_at, completed_at
            ) VALUES (2026, 30, 'completed', 1, '2026-07-22T20:00:00+00:00',
                      '2026-07-22T20:01:00+00:00')
            """
        ).lastrowid
        connection.execute(
            """
            UPDATE bestseller_sync_state
            SET last_checked_at = '2026-07-23T10:00:00+00:00',
                last_success_snapshot_id = ?, last_error = 'previous failure'
            WHERE id = 1
            """,
            (snapshot_id,),
        )

    is_admin = False
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_v1_api(
        app,
        database_path=database_path,
        resolve_actor=lambda: V1Actor(int(admin["id"]), is_admin=is_admin),
    )
    client = app.test_client()

    assert client.get("/api/v1/admin/bestseller/status").status_code == 403
    assert client.post("/api/v1/admin/bestseller/sync").status_code == 403

    is_admin = True
    status = client.get("/api/v1/admin/bestseller/status")
    scheduled = client.post("/api/v1/admin/bestseller/sync")

    assert status.status_code == 200
    assert status.json["last_checked_at"] == "2026-07-23T10:00:00+00:00"
    assert status.json["last_error"] == "previous failure"
    assert status.json["next_check_at"] is not None
    assert status.json["lease_expires_at"] is None
    assert status.json["active_snapshot"] == {
        "completed_at": "2026-07-22T20:01:00+00:00",
        "fetched_at": "2026-07-22T20:00:00+00:00",
        "week": 30,
        "year": 2026,
    }
    assert status.json["last_success"] == status.json["active_snapshot"]
    assert scheduled.status_code == 202
    assert scheduled.json["scheduled"] is True
    with sqlite3.connect(database_path) as connection:
        job = connection.execute(
            "SELECT job_type, payload_json, status FROM background_jobs WHERE id = ?",
            (scheduled.json["job_id"],),
        ).fetchone()
    assert job == ("sync_bestseller60", '{"trigger":"admin"}', "queued")
