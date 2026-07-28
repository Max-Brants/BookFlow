from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from bookflow.core.legacy_file_reconciliation import reconcile_legacy_download_files
from bookflow.core.user_db import UserDB


def _seed_review(
    database_path: Path,
    *,
    path: Path,
    file_format: str,
    final_status: str = "complete",
    create_review: bool = True,
) -> tuple[int, int]:
    user_db = UserDB(str(database_path))
    user_db.initialize()
    user = user_db.create_user(username="reader")
    with sqlite3.connect(database_path) as conn:
        book_id = int(
            conn.execute(
                """
                INSERT INTO books (
                    metadata_provider, provider_book_id, title, catalog_visible
                ) VALUES ('legacy', 'legacy-book', 'Legacy Book', 0)
                """
            ).lastrowid
        )
        history_id = int(
            conn.execute(
                """
                INSERT INTO download_history (
                    task_id, user_id, source, title, format, content_type,
                    final_status, download_path, book_id
                ) VALUES (
                    'legacy-task', ?, 'direct_download', 'Legacy Book', ?,
                    'ebook', ?, ?, ?
                )
                """,
                (user["id"], file_format, final_status, str(path), book_id),
            ).lastrowid
        )
        if create_review:
            conn.execute(
                """
                INSERT INTO legacy_book_files_review (
                    history_id, book_id, payload_json, reason
                ) VALUES (?, ?, '{}', 'legacy_path_requires_configured_root_review')
                """,
                (history_id, book_id),
            )
    return int(user["id"]), book_id


def test_reconciliation_imports_verified_legacy_file_and_grants_entitlement(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    epub = library / "Legacy Book.epub"
    epub.write_bytes(b"verified epub")
    database_path = tmp_path / "users.db"
    user_id, book_id = _seed_review(
        database_path,
        path=epub,
        file_format="epub",
        create_review=False,
    )

    result = reconcile_legacy_download_files(
        database_path=database_path,
        library_roots=[library],
        supported_formats=["epub", "pdf"],
    )

    assert result == {
        "imported": 1,
        "already_present": 0,
        "skipped": {},
        "configured_roots": 1,
    }
    with sqlite3.connect(database_path) as conn:
        file_row = conn.execute(
            """
            SELECT id, book_id, storage_path, file_format, size_bytes, sha256,
                   import_status, content_type
            FROM book_files
            """
        ).fetchone()
        assert file_row is not None
        assert file_row[1:] == (
            book_id,
            str(epub.resolve()),
            "epub",
            len(b"verified epub"),
            hashlib.sha256(b"verified epub").hexdigest(),
            "imported",
            "ebook",
        )
        assert conn.execute(
            "SELECT catalog_visible FROM books WHERE id = ?", (book_id,)
        ).fetchone() == (1,)
        assert conn.execute(
            """
            SELECT user_id, file_id, grant_source FROM user_file_entitlements
            """
        ).fetchone() == (user_id, file_row[0], "migration")
        assert conn.execute("SELECT COUNT(*) FROM legacy_book_files_review").fetchone() == (0,)

    repeated = reconcile_legacy_download_files(
        database_path=database_path,
        library_roots=[library],
        supported_formats=["epub"],
    )
    assert repeated["imported"] == 0


def test_reconciliation_preserves_unverified_or_retired_rows(tmp_path: Path) -> None:
    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    audio = library / "retired.mp3"
    audio.write_bytes(b"audio")
    outside_epub = outside / "outside.epub"
    outside_epub.write_bytes(b"outside")

    audio_db = tmp_path / "audio.db"
    _seed_review(audio_db, path=audio, file_format="mp3")
    outside_db = tmp_path / "outside.db"
    _seed_review(outside_db, path=outside_epub, file_format="epub")

    audio_result = reconcile_legacy_download_files(
        database_path=audio_db,
        library_roots=[library],
        supported_formats=["epub", "mp3"],
    )
    outside_result = reconcile_legacy_download_files(
        database_path=outside_db,
        library_roots=[library],
        supported_formats=["epub"],
    )

    assert audio_result["skipped"] == {"retired_or_unknown_format": 1}
    assert outside_result["skipped"] == {"outside_library_root": 1}
    for database_path in (audio_db, outside_db):
        with sqlite3.connect(database_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM book_files").fetchone() == (0,)
            assert conn.execute("SELECT COUNT(*) FROM legacy_book_files_review").fetchone() == (1,)
