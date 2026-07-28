"""Upgrade coverage for the additive canonical catalog/file migration."""

import sqlite3
from pathlib import Path

import pytest

from bookflow.core.db_migrations import Migration, SQLiteMigrator
from bookflow.core.user_db import (
    _MIGRATION_001_CHECKSUM,
    _MIGRATION_002_CHECKSUM,
    UserDB,
)


def test_v3_backfills_certain_identifiers_and_quarantines_legacy_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "users.db"
    user_db = UserDB(str(db_path))
    conn = user_db._connect()
    try:
        SQLiteMigrator(
            conn,
            str(db_path),
            (
                Migration(
                    version=1,
                    name="canonical-library-baseline",
                    checksum=_MIGRATION_001_CHECKSUM,
                    apply=user_db._apply_migration_001,
                ),
                Migration(
                    version=2,
                    name="persistent-auth-login-rate-limits",
                    checksum=_MIGRATION_002_CHECKSUM,
                    apply=user_db._apply_migration_002,
                ),
            ),
        ).migrate()
        first = conn.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, isbn_13)
            VALUES ('hardcover', 'one', 'First Edition', '9780306406157')
            """
        ).lastrowid
        second = conn.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, isbn_13)
            VALUES ('openlibrary', 'two', 'Second Edition', '9780306406157')
            """
        ).lastrowid
        assert first is not None
        assert second is not None
        conn.execute(
            """
            INSERT INTO download_history (
                task_id, source, title, final_status, download_path, book_id
            ) VALUES ('legacy-task', 'test', 'First Edition', 'complete', '/legacy/book.epub', ?)
            """,
            (first,),
        )
        conn.commit()
    finally:
        conn.close()

    user_db.initialize()

    conn = user_db._connect()
    try:
        migration = conn.execute(
            "SELECT name, status FROM schema_migrations WHERE version = 3"
        ).fetchone()
        providers = conn.execute(
            "SELECT book_id, provider, provider_book_id FROM book_provider_identifiers ORDER BY book_id"
        ).fetchall()
        isbn_rows = conn.execute(
            "SELECT book_id, identifier FROM book_identifiers WHERE identifier_type = 'isbn13' ORDER BY book_id"
        ).fetchall()
        conflict = conn.execute(
            """
            SELECT identifier, existing_book_id, proposed_book_id
            FROM book_identifier_conflicts
            """
        ).fetchone()
        review = conn.execute("SELECT history_id, reason FROM legacy_book_files_review").fetchone()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(book_files)").fetchall()}
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO book_files (
                    book_id, storage_path, file_format, size_bytes, sha256, import_status
                ) VALUES (?, '/library/invalid.epub', 'epub', 1, 'not-a-hash', 'imported')
                """,
                (first,),
            )
    finally:
        conn.close()

    assert tuple(migration) == ("canonical-book-files-and-entitlements", "completed")
    assert [tuple(row) for row in providers] == [
        (first, "hardcover", "one"),
        (second, "openlibrary", "two"),
    ]
    assert [tuple(row) for row in isbn_rows] == [
        (first, "9780306406157"),
        (second, "9780306406157"),
    ]
    assert tuple(conflict) == ("9780306406157", first, second)
    assert review[1] == "legacy_path_requires_configured_root_review"
    assert columns >= {
        "storage_path",
        "file_format",
        "size_bytes",
        "sha256",
        "mime_type",
        "import_status",
        "derived_from_file_id",
    }
