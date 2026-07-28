"""Canonical ordered author and series relations for a Book snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _ordered_names(values: Iterable[object]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = _clean(value)
        if name is None:
            continue
        normalized = name.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        names.append(name)
    return names


def sync_book_catalog_relations(
    conn: sqlite3.Connection,
    *,
    book_id: int,
    authors: Iterable[object],
    series_name: object = None,
    series_position: float | None = None,
) -> None:
    """Replace derived relations while preserving provider author ordering."""
    conn.execute("DELETE FROM book_catalog_authors WHERE book_id = ?", (book_id,))
    for position, name in enumerate(_ordered_names(authors)):
        normalized = name.casefold()
        conn.execute(
            "INSERT OR IGNORE INTO catalog_authors(name, normalized_name) VALUES (?, ?)",
            (name, normalized),
        )
        author = conn.execute(
            "SELECT id FROM catalog_authors WHERE normalized_name = ?",
            (normalized,),
        ).fetchone()
        if author is not None:
            conn.execute(
                """
                INSERT INTO book_catalog_authors(book_id, author_id, position)
                VALUES (?, ?, ?)
                """,
                (book_id, int(author[0]), position),
            )

    conn.execute("DELETE FROM book_catalog_series WHERE book_id = ?", (book_id,))
    cleaned_series = _clean(series_name)
    if cleaned_series is None:
        return
    normalized_series = cleaned_series.casefold()
    conn.execute(
        "INSERT OR IGNORE INTO catalog_series(name, normalized_name) VALUES (?, ?)",
        (cleaned_series, normalized_series),
    )
    series = conn.execute(
        "SELECT id FROM catalog_series WHERE normalized_name = ?",
        (normalized_series,),
    ).fetchone()
    if series is not None:
        conn.execute(
            """
            INSERT INTO book_catalog_series(book_id, series_id, position)
            VALUES (?, ?, ?)
            """,
            (book_id, int(series[0]), series_position),
        )
