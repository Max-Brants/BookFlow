"""Safely promote verified legacy download history into canonical Book files."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bookflow.core.audiobook_retirement import AUDIO_FILE_EXTENSIONS


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("Inserted row did not receive an id")
    return cursor.lastrowid


def _normalized_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    normalized: list[Path] = []
    for root in roots:
        try:
            candidate = root.expanduser().resolve(strict=True)
        except OSError, RuntimeError:
            continue
        if candidate.is_dir() and candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def _normalized_formats(values: object) -> frozenset[str]:
    if isinstance(values, str):
        candidates: Iterable[object] = values.split(",")
    elif isinstance(values, Iterable):
        candidates = values
    else:
        candidates = ()
    return frozenset(
        normalized
        for value in candidates
        if (normalized := str(value).strip().casefold().lstrip("."))
    )


def _verified_file(
    raw_path: object,
    *,
    roots: tuple[Path, ...],
    allowed_formats: frozenset[str],
    history_format: object,
) -> tuple[Path | None, str | None, str | None]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, None, "missing_path"
    try:
        path = Path(raw_path.strip()).expanduser().resolve(strict=True)
    except OSError, RuntimeError, ValueError:
        return None, None, "missing_or_unresolvable"
    if not path.is_file() or not any(path.is_relative_to(root) and path != root for root in roots):
        return None, None, "outside_library_root"

    suffix_format = path.suffix.casefold().lstrip(".")
    declared_format = str(history_format or "").strip().casefold().lstrip(".")
    file_format = declared_format or suffix_format
    if (
        not file_format
        or f".{file_format}" in AUDIO_FILE_EXTENSIONS
        or f".{suffix_format}" in AUDIO_FILE_EXTENSIONS
    ):
        return None, None, "retired_or_unknown_format"
    if (
        allowed_formats
        and file_format not in allowed_formats
        and suffix_format not in allowed_formats
    ):
        return None, None, "unsupported_format"
    return path, file_format, None


def reconcile_legacy_download_files(
    *,
    database_path: Path,
    library_roots: Iterable[Path],
    supported_formats: object,
) -> dict[str, Any]:
    """Import only completed, present ebook files from the legacy review queue.

    Migration v3 intentionally quarantined existing legacy paths because
    database migration code did not yet know the configured library roots.
    Older download paths can also be written after that migration without a
    canonical file row. At runtime the roots are available, so this pass can
    validate path containment, existence, format, size and content hash before
    creating canonical rows.
    """
    roots = _normalized_roots(library_roots)
    formats = _normalized_formats(supported_formats)
    skipped: Counter[str] = Counter()
    imported = 0
    already_present = 0

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        rows = conn.execute(
            """
            SELECT review.id AS review_id, history.id AS history_id,
                   history.user_id, history.book_id, history.download_path,
                   history.format, history.source, history.final_status,
                   history.content_type
            FROM download_history history
            LEFT JOIN legacy_book_files_review review ON review.history_id = history.id
            WHERE history.book_id IS NOT NULL
              AND history.download_path IS NOT NULL
              AND (
                  review.id IS NOT NULL
                  OR NOT EXISTS (
                      SELECT 1 FROM book_files
                      WHERE storage_path = history.download_path
                  )
              )
            ORDER BY history.id
            """
        ).fetchall()
        for row in rows:
            if str(row["final_status"] or "").strip().casefold() != "complete":
                skipped["not_complete"] += 1
                continue
            if str(row["content_type"] or "ebook").strip().casefold() != "ebook":
                skipped["retired_content_type"] += 1
                continue
            if row["book_id"] is None:
                skipped["missing_book"] += 1
                continue

            path, file_format, reason = _verified_file(
                row["download_path"],
                roots=roots,
                allowed_formats=formats,
                history_format=row["format"],
            )
            if reason is not None or path is None or file_format is None:
                skipped[reason or "invalid_file"] += 1
                continue

            before = path.stat()
            with path.open("rb") as file_handle:
                digest = hashlib.file_digest(file_handle, "sha256").hexdigest()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                skipped["file_changed_during_hash"] += 1
                continue

            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    """
                    SELECT id, book_id FROM book_files
                    WHERE storage_path = ? OR sha256 = ?
                    ORDER BY storage_path = ? DESC
                    LIMIT 1
                    """,
                    (str(path), digest, str(path)),
                ).fetchone()
                book_id = int(row["book_id"])
                if existing is not None and int(existing["book_id"]) != book_id:
                    conn.rollback()
                    skipped["file_owned_by_other_book"] += 1
                    continue
                if existing is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO book_files (
                            book_id, storage_path, file_format, size_bytes, sha256,
                            mime_type, release_source, import_status, content_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'imported', 'ebook')
                        """,
                        (
                            book_id,
                            str(path),
                            file_format,
                            int(after.st_size),
                            digest,
                            "application/epub+zip" if file_format == "epub" else None,
                            str(row["source"] or "").strip() or None,
                        ),
                    )
                    file_id = _last_insert_id(cursor)
                    imported += 1
                else:
                    file_id = int(existing["id"])
                    already_present += 1

                conn.execute("UPDATE books SET catalog_visible = 1 WHERE id = ?", (book_id,))
                if row["user_id"] is not None:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO user_file_entitlements (
                            user_id, file_id, grant_source
                        )
                        SELECT ?, ?, 'migration'
                        WHERE EXISTS (SELECT 1 FROM users WHERE id = ?)
                        """,
                        (row["user_id"], file_id, row["user_id"]),
                    )
                if row["review_id"] is not None:
                    conn.execute(
                        "DELETE FROM legacy_book_files_review WHERE id = ?",
                        (row["review_id"],),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.close()

    return {
        "imported": imported,
        "already_present": already_present,
        "skipped": dict(sorted(skipped.items())),
        "configured_roots": len(roots),
    }
