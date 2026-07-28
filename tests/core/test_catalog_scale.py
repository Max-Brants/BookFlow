"""Acceptance coverage for the 50,000-Book FTS catalog target."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bookflow.core.catalog_monitor_service import CatalogMonitorService
from bookflow.core.user_db import UserDB


def test_fts_and_pagination_with_fifty_thousand_books(tmp_path: Path) -> None:
    database_path = tmp_path / "users.db"
    users = UserDB(str(database_path))
    users.initialize()
    rows = [
        (
            f"scale-{index}",
            f"Scale Book {index:05d}",
            "Scale Author",
            '{"description":"unique scale anchor"}' if index == 42420 else "{}",
        )
        for index in range(50_000)
    ]
    with sqlite3.connect(database_path) as conn:
        conn.executemany(
            """
            INSERT INTO books(
                metadata_provider, provider_book_id, title, author, metadata_json
            )
            VALUES ('scale', ?, ?, ?, ?)
            """,
            rows,
        )
        # Browse only exposes imported books; populate an imported file for
        # each synthetic title so this remains a catalog-scale test rather
        # than exercising hidden request metadata.
        conn.execute(
            """
            INSERT INTO book_files(book_id, storage_path, file_format, size_bytes, sha256, import_status)
            SELECT id, 'scale/' || id || '.epub', 'epub', 1, printf('%064x', id), 'imported'
            FROM books
            """
        )

    service = CatalogMonitorService(str(database_path))
    page = service.catalog_books(
        query=None,
        author_id=None,
        series_id=None,
        offset=49_990,
        limit=10,
        sort="title",
    )
    match = service.catalog_books(
        query="unique scale anchor",
        author_id=None,
        series_id=None,
        offset=0,
        limit=10,
    )

    assert page["total"] == 50_000
    assert len(page["items"]) == 10
    assert match["total"] == 1
    assert match["items"][0]["provider_book_id"] == "scale-42420"
