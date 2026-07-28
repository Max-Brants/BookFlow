"""Canonical Book grouping helpers.

Legacy installations can contain more than one ``books`` row for the same
ISBN.  The physical rows remain intact so their requests, files and audit
history are never discarded, while catalog-facing reads treat them as one
logical Book.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bookflow.core.book_matcher import normalize_isbn

if TYPE_CHECKING:
    import sqlite3


def normalized_isbn13_sql(alias: str) -> str:
    """Return a fixed SQL expression for a normalized ISBN-13 column."""
    compact = f"REPLACE(REPLACE(TRIM(COALESCE({alias}.isbn_13, '')), '-', ''), ' ', '')"
    return (
        f"CASE WHEN LENGTH({compact}) = 13 "
        f"AND {compact} NOT GLOB '*[^0-9]*' THEN {compact} ELSE NULL END"
    )


def book_group_key_sql(alias: str) -> str:
    """Return a stable logical-book key for catalog SQL."""
    isbn = normalized_isbn13_sql(alias)
    return f"COALESCE('isbn:' || ({isbn}), 'book:' || {alias}.id)"


def equivalent_book_ids(conn: sqlite3.Connection, book_id: int) -> list[int]:
    """Return every Book row linked to the same valid ISBN as ``book_id``."""
    row = conn.execute("SELECT isbn_13 FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        return []
    normalized = normalize_isbn(str(row["isbn_13"] or ""))
    if normalized is None:
        return [book_id]
    identifiers = tuple(
        value for value in (normalized.isbn13, normalized.isbn10) if value is not None
    )
    placeholders = ",".join("?" for _ in identifiers)
    rows = conn.execute(
        f"""
        SELECT id FROM books
        WHERE id = ?
           OR id IN (
               SELECT book_id FROM book_identifiers
               WHERE identifier_type IN ('isbn10', 'isbn13')
                 AND identifier IN ({placeholders})
           )
           OR REPLACE(REPLACE(TRIM(COALESCE(isbn_13, '')), '-', ''), ' ', '') = ?
        ORDER BY id
        """,  # noqa: S608 - only the placeholder count is generated.
        (book_id, *identifiers, normalized.isbn13 or ""),
    ).fetchall()
    return sorted({int(candidate["id"]) for candidate in rows})


def canonical_book_id(conn: sqlite3.Connection, book_ids: list[int]) -> int:
    """Choose the best catalog representative without discarding any row."""
    if not book_ids:
        raise ValueError("book_ids must not be empty")
    placeholders = ",".join("?" for _ in book_ids)
    row = conn.execute(
        f"""
        SELECT b.id
        FROM books b
        WHERE b.id IN ({placeholders})
        ORDER BY
          EXISTS (
              SELECT 1 FROM book_files bf
              WHERE bf.book_id = b.id AND bf.import_status = 'imported'
          ) DESC,
          b.catalog_visible DESC,
          b.id ASC
        LIMIT 1
        """,  # noqa: S608 - only the placeholder count is generated.
        book_ids,
    ).fetchone()
    return int(row["id"]) if row is not None else min(book_ids)
