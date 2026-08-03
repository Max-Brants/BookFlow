from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path

from flask import Flask

from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor, register_v1_api


def _epub_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
        )
        archive.writestr("book.opf", '<package version="3.0"></package>')
    return output.getvalue()


def _setup(tmp_path: Path):
    database = tmp_path / "users.db"
    library = tmp_path / "library"
    library.mkdir()
    users = UserDB(str(database))
    users.initialize()
    admin = users.create_user(username="admin", role="admin")
    reader = users.create_user(username="reader", role="user")
    with sqlite3.connect(database) as conn:
        book_id = conn.execute(
            "INSERT INTO books(metadata_provider,provider_book_id,title) VALUES('test','manual','Manual')"
        ).lastrowid
    assert book_id is not None
    actor = {"value": V1Actor(int(admin["id"]), is_admin=True)}
    app = Flask(__name__)
    app.config["TESTING"] = True
    kobo_fulfilments: list[tuple[int, int, int]] = []
    register_v1_api(
        app,
        database_path=database,
        resolve_actor=lambda: actor["value"],
        library_root=library,
        kobo_fulfilment=lambda user_id, target_book_id, file_id: kobo_fulfilments.append(
            (user_id, target_book_id, file_id)
        ),
    )
    return (
        app.test_client(),
        database,
        library,
        actor,
        admin,
        reader,
        int(book_id),
        kobo_fulfilments,
    )


def test_admin_upload_imports_epub_and_completes_requests(tmp_path: Path) -> None:
    client, database, library, _actor, admin, reader, book_id, kobo_fulfilments = _setup(tmp_path)
    workflow = RequestWorkflowService(str(database))
    created = workflow.create_request(
        user_id=int(reader["id"]),
        book_id=book_id,
        profile={"formats": ["epub"]},
        add_to_kobo_when_available=True,
    )
    _approved, process, _new = workflow.approve_request(
        int(created["id"]), reviewer_user_id=int(admin["id"])
    )
    assert process is not None

    response = client.post(
        f"/api/v1/admin/catalog/books/{book_id}/files",
        data={"file": (io.BytesIO(_epub_bytes()), "manual.epub")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    assert response.json["file"]["file_format"] == "epub"
    assert "storage_path" not in response.json["file"]
    assert response.json["fulfilled_request_ids"] == [created["id"]]
    with sqlite3.connect(database) as conn:
        request_row = conn.execute(
            "SELECT status, fulfilled_file_id FROM requests WHERE id=?", (created["id"],)
        ).fetchone()
        process_row = conn.execute(
            "SELECT status, monitoring_enabled FROM request_processes WHERE id=?",
            (process["id"],),
        ).fetchone()
        entitlement = conn.execute(
            "SELECT COUNT(*) FROM user_file_entitlements WHERE user_id=?",
            (reader["id"],),
        ).fetchone()[0]
    assert request_row is not None and request_row[0] == "fulfilled" and request_row[1]
    assert process_row == ("completed", 0)
    assert entitlement == 1
    assert kobo_fulfilments == [(reader["id"], book_id, response.json["file"]["id"])]
    assert len(list(library.rglob("*.epub"))) == 1
    assert not list(library.glob(".manual-upload-*"))


def test_upload_requires_admin_and_valid_epub(tmp_path: Path) -> None:
    client, _database, library, actor, _admin, reader, book_id, _kobo = _setup(tmp_path)
    actor["value"] = V1Actor(int(reader["id"]), is_admin=False)
    forbidden = client.post(
        f"/api/v1/admin/catalog/books/{book_id}/files",
        data={"file": (io.BytesIO(_epub_bytes()), "manual.epub")},
        content_type="multipart/form-data",
    )
    assert forbidden.status_code == 403

    actor["value"] = V1Actor(1, is_admin=True)
    invalid = client.post(
        f"/api/v1/admin/catalog/books/{book_id}/files",
        data={"file": (io.BytesIO(b"not an epub"), "manual.epub")},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert invalid.json["error"]["code"] == "invalid_epub"
    assert not list(library.rglob("*.epub"))


def test_same_epub_cannot_be_attached_to_another_book(tmp_path: Path) -> None:
    client, database, _library, _actor, _admin, _reader, book_id, _kobo = _setup(tmp_path)
    with sqlite3.connect(database) as conn:
        other_book_id = conn.execute(
            "INSERT INTO books(metadata_provider,provider_book_id,title) VALUES('test','other','Other')"
        ).lastrowid
    assert other_book_id is not None
    payload = _epub_bytes()
    first = client.post(
        f"/api/v1/admin/catalog/books/{book_id}/files",
        data={"file": (io.BytesIO(payload), "manual.epub")},
        content_type="multipart/form-data",
    )
    second = client.post(
        f"/api/v1/admin/catalog/books/{other_book_id}/files",
        data={"file": (io.BytesIO(payload), "manual.epub")},
        content_type="multipart/form-data",
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json["error"]["code"] == "manual_import_failed"
