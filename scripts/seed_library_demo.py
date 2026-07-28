# ruff: noqa: E402, I001
"""Seed a local BookFlow library with three books for UI development.

Run with ``CONFIG_DIR=$PWD/.local/config uv run python scripts/seed_library_demo.py``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
os.environ.setdefault("LOG_ROOT", str(REPOSITORY_ROOT / ".local/log"))

from bookflow.core.user_db import UserDB


CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", ".local/config"))
DB_PATH = CONFIG_DIR / "users.db"
FILES_DIR = CONFIG_DIR.parent / "seed-files"
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo"

BOOKS = (
    ("openlibrary", "OL1W", "A Memory Called Empire", "Arkady Martine"),
    ("openlibrary", "OL2W", "The Left Hand of Darkness", "Ursula K. Le Guin"),
    ("openlibrary", "OL3W", "Piranesi", "Susanna Clarke"),
)


def main() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # A deterministic local fixture matters more than preserving disposable
    # development state: routes in the demo instructions address Books 1-3.
    DB_PATH.unlink(missing_ok=True)
    shutil.rmtree(FILES_DIR, ignore_errors=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    user_db = UserDB(str(DB_PATH))
    user_db.initialize()
    demo_user = user_db.create_user(
        username=DEMO_USERNAME,
        password_hash=generate_password_hash(DEMO_PASSWORD),
        role="admin",
    )
    demo_user_id = int(demo_user["id"])

    epub_path = FILES_DIR / "a-memory-called-empire.epub"
    mobi_path = FILES_DIR / "a-memory-called-empire.mobi"
    epub_path.write_text("Demo EPUB placeholder\n")
    mobi_path.write_text("Demo MOBI placeholder\n")

    conn = sqlite3.connect(DB_PATH)
    try:
        for provider, provider_book_id, title, author in BOOKS:
            conn.execute(
                """
                INSERT OR IGNORE INTO books (metadata_provider, provider_book_id, title, author)
                VALUES (?, ?, ?, ?)
                """,
                (provider, provider_book_id, title, author),
            )

        book_ids = {
            provider_book_id: row[0]
            for provider_book_id, row in (
                (
                    provider_book_id,
                    conn.execute(
                        "SELECT id FROM books WHERE metadata_provider = ? AND provider_book_id = ?",
                        (provider, provider_book_id),
                    ).fetchone(),
                )
                for provider, provider_book_id, _, _ in BOOKS
            )
        }
        for book_id in book_ids.values():
            conn.execute(
                "INSERT OR IGNORE INTO user_library (user_id, book_id) VALUES (?, ?)",
                (demo_user_id, book_id),
            )

        files = (
            ("demo-memory-epub", book_ids["OL1W"], "EPUB", epub_path, "complete"),
            ("demo-memory-mobi", book_ids["OL1W"], "MOBI", mobi_path, "complete"),
            ("demo-piranesi-active", book_ids["OL3W"], None, None, "active"),
        )
        for task_id, book_id, file_format, path, status in files:
            conn.execute("DELETE FROM download_history WHERE task_id = ?", (task_id,))
            cursor = conn.execute(
                """
                INSERT INTO download_history (
                    task_id, user_id, source, title, format, final_status, download_path, book_id
                ) VALUES (?, ?, 'demo', ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    demo_user_id,
                    next(
                        title
                        for _, provider_book_id, title, _ in BOOKS
                        if book_ids[provider_book_id] == book_id
                    ),
                    file_format,
                    status,
                    str(path) if path else None,
                    book_id,
                ),
            )
            if status == "complete":
                conn.execute(
                    "INSERT OR IGNORE INTO user_downloads (user_id, history_id) VALUES (?, ?)",
                    (demo_user_id, cursor.lastrowid),
                )
                file_bytes = path.read_bytes()
                file_cursor = conn.execute(
                    """
                    INSERT INTO book_files(
                        book_id, storage_path, file_format, size_bytes, sha256,
                        release_source, import_status
                    )
                    VALUES (?, ?, ?, ?, ?, 'demo', 'imported')
                    """,
                    (
                        book_id,
                        str(path),
                        str(file_format).casefold(),
                        len(file_bytes),
                        hashlib.sha256(file_bytes).hexdigest(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO user_file_entitlements(user_id, file_id, grant_source)
                    VALUES (?, ?, 'direct')
                    """,
                    (demo_user_id, int(file_cursor.lastrowid)),
                )
        conn.commit()
    finally:
        conn.close()

    print(f"Seeded Books 1-3 in {DB_PATH} for {DEMO_USERNAME}/{DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
