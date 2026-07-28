"""Executable restore rehearsal for the migration backup contract."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from bookflow.core.db_migrations import Migration, SQLiteMigrator


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_preflight_backup_can_restore_the_pre_upgrade_database(tmp_path: Path) -> None:
    """Restore the exact manifest artifact and verify data/schema integrity."""
    database_path = tmp_path / "users.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
    connection.executemany(
        "INSERT INTO books (id, title) VALUES (?, ?)",
        ((book_id, f"Book {book_id}") for book_id in range(1, 2_001)),
    )
    connection.commit()

    migration = Migration(
        version=1,
        name="add-book-language",
        checksum=_checksum("add-book-language-v1"),
        apply=lambda conn: conn.execute("ALTER TABLE books ADD COLUMN language TEXT"),
    )
    manifest_path = SQLiteMigrator(connection, str(database_path), (migration,)).migrate()
    assert manifest_path is not None
    connection.close()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_path = Path(manifest["backup_path"])
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == manifest["backup_sha256"]

    restored_path = tmp_path / "restored-users.db"
    shutil.copy2(backup_path, restored_path)
    restored = sqlite3.connect(restored_path)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
        assert restored.execute("SELECT COUNT(*) FROM books").fetchone() == (2_000,)
        assert restored.execute("SELECT title FROM books WHERE id = 2_000").fetchone() == (
            "Book 2000",
        )
        columns = {row[1] for row in restored.execute("PRAGMA table_info(books)")}
        assert "language" not in columns
        assert (
            restored.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            is None
        )
    finally:
        restored.close()
