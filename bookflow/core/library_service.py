"""Library service — SQL queries against books / user_library / user_downloads.

Implements the data layer for the library API (#04 contract). Mirrors the
layering of :class:`DownloadHistoryService`: db-path + lock + ``_connect`` +
row-to-dict helpers. Models books as denormalized snapshots per ADR 0001 and
file visibility per ADR 0002.

"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from bookflow.core.book_groups import canonical_book_id, equivalent_book_ids
from bookflow.core.catalog_relations import sync_book_catalog_relations
from bookflow.core.logger import setup_logger
from bookflow.core.metadata_governance import record_provider_observation
from bookflow.core.request_helpers import (
    normalize_optional_text,
    normalize_positive_int,
    now_utc_iso,
)

logger = setup_logger(__name__)


_ACTIVE_DOWNLOAD_STATUS = "active"
_COMPLETE_DOWNLOAD_STATUS = "complete"


def _now_utc_iso() -> str:
    return now_utc_iso()


def _parse_metadata_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _row_to_book(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = dict(row)
    payload["metadata_json"] = _parse_metadata_json(payload.get("metadata_json"))
    return payload


class LibraryService:
    """Service for library membership and book/file lookups."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _book_identity(book_id: Any) -> int:
        normalized = normalize_positive_int(book_id)
        if normalized is None:
            msg = "book_id must be a positive integer"
            raise ValueError(msg)
        return normalized

    @staticmethod
    def _history_identity(history_id: Any) -> int:
        normalized = normalize_positive_int(history_id)
        if normalized is None:
            msg = "history_id must be a positive integer"
            raise ValueError(msg)
        return normalized

    def upsert_book_from_metadata(
        self,
        *,
        metadata_provider: str,
        provider_book_id: str,
        title: str,
        author: str | None,
        subtitle: str | None,
        publish_year: int | None,
        isbn_13: str | None,
        cover_url: str | None,
        series_name: str | None,
        series_position: float | None,
        language: str | None,
        metadata_json: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert or return the existing book row for a provider natural key.

        Idempotent on ``UNIQUE(metadata_provider, provider_book_id)``. Per
        ADR 0001, the snapshot is written at Add time and never refreshed.
        """
        normalized_provider = normalize_optional_text(metadata_provider)
        if not normalized_provider:
            msg = "metadata_provider must be a non-empty string"
            raise ValueError(msg)
        normalized_provider_book_id = normalize_optional_text(provider_book_id)
        if not normalized_provider_book_id:
            msg = "provider_book_id must be a non-empty string"
            raise ValueError(msg)
        normalized_title = normalize_optional_text(title)
        if not normalized_title:
            msg = "title must be a non-empty string"
            raise ValueError(msg)
        serialized_metadata = json.dumps(metadata_json, ensure_ascii=False)

        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT * FROM books WHERE metadata_provider = ? AND provider_book_id = ?",
                    (normalized_provider, normalized_provider_book_id),
                ).fetchone()
                if existing is not None:
                    provider_snapshot = dict(metadata_json)
                    provider_snapshot.setdefault("provider", normalized_provider)
                    provider_snapshot.setdefault("provider_id", normalized_provider_book_id)
                    provider_snapshot.setdefault("title", normalized_title)
                    record_provider_observation(
                        conn,
                        book_id=int(existing["id"]),
                        source=normalized_provider,
                        source_identifier=normalized_provider_book_id,
                        payload=provider_snapshot,
                    )
                    conn.commit()
                    return _row_to_book(existing) or {}

                cursor = conn.execute(
                    """
                    INSERT INTO books (
                        metadata_provider, provider_book_id, title, author,
                        subtitle, publish_year, isbn_13, cover_url,
                        series_name, series_position, language, metadata_json,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_provider,
                        normalized_provider_book_id,
                        normalized_title,
                        normalize_optional_text(author),
                        normalize_optional_text(subtitle),
                        publish_year,
                        normalize_optional_text(isbn_13),
                        normalize_optional_text(cover_url),
                        normalize_optional_text(series_name),
                        series_position,
                        normalize_optional_text(language),
                        serialized_metadata,
                        _now_utc_iso(),
                        _now_utc_iso(),
                    ),
                )
                last_row_id = cursor.lastrowid
                if last_row_id is None:
                    msg = "Failed to insert book row"
                    raise RuntimeError(msg)
                book_id = int(last_row_id)
                raw_authors = metadata_json.get("authors")
                authors = (
                    raw_authors
                    if isinstance(raw_authors, list)
                    else [author]
                    if author is not None
                    else []
                )
                sync_book_catalog_relations(
                    conn,
                    book_id=book_id,
                    authors=authors,
                    series_name=series_name,
                    series_position=series_position,
                )
                provider_snapshot = dict(metadata_json)
                provider_snapshot.setdefault("provider", normalized_provider)
                provider_snapshot.setdefault("provider_id", normalized_provider_book_id)
                provider_snapshot.setdefault("title", normalized_title)
                provider_snapshot.setdefault("author", normalize_optional_text(author))
                provider_snapshot.setdefault("subtitle", normalize_optional_text(subtitle))
                provider_snapshot.setdefault("publish_year", publish_year)
                provider_snapshot.setdefault("isbn_13", normalize_optional_text(isbn_13))
                provider_snapshot.setdefault("cover_url", normalize_optional_text(cover_url))
                provider_snapshot.setdefault("series_name", normalize_optional_text(series_name))
                provider_snapshot.setdefault("series_position", series_position)
                provider_snapshot.setdefault("language", normalize_optional_text(language))
                record_provider_observation(
                    conn,
                    book_id=book_id,
                    source=normalized_provider,
                    source_identifier=normalized_provider_book_id,
                    payload=provider_snapshot,
                )
                conn.commit()
                row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
                return _row_to_book(row) or {}
            finally:
                conn.close()

    def add_to_library(self, *, user_id: int, book_id: int) -> bool:
        """Add an available book and entitle every imported file atomically.

        A fileless metadata row is a request target, never a library item.
        """
        normalized_user_id = normalize_positive_int(user_id)
        normalized_book_id = self._book_identity(book_id)
        if normalized_user_id is None:
            msg = "user_id must be a positive integer"
            raise ValueError(msg)
        with self._lock:
            conn = self._connect()
            try:
                book_ids = equivalent_book_ids(conn, normalized_book_id)
                if not book_ids:
                    raise ValueError("book_id does not reference an existing Book")
                normalized_book_id = canonical_book_id(conn, book_ids)
                file_rows = conn.execute(
                    """SELECT id FROM book_files WHERE book_id = ?
                       AND import_status = 'imported' AND content_type = 'ebook'""",
                    (normalized_book_id,),
                ).fetchall()
                if not file_rows:
                    raise ValueError("Book has no imported files; create a request instead")
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO user_library (user_id, book_id, added_at)
                    VALUES (?, ?, ?)
                    """,
                    (normalized_user_id, normalized_book_id, _now_utc_iso()),
                )
                for file_row in file_rows:
                    conn.execute(
                        """INSERT INTO user_file_entitlements(user_id,file_id,grant_source)
                           VALUES (?, ?, 'direct') ON CONFLICT(user_id,file_id) DO NOTHING""",
                        (normalized_user_id, file_row["id"]),
                    )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def add_many_to_library(
        self, *, user_id: int, book_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Add available Books in one transaction and report each outcome.

        Expected domain failures are isolated per Book. Unexpected database
        failures abort the transaction so callers never observe a half-written
        batch.
        """
        normalized_user_id = normalize_positive_int(user_id)
        if normalized_user_id is None:
            raise ValueError("user_id must be a positive integer")

        normalized_book_ids = [self._book_identity(book_id) for book_id in book_ids]
        with self._lock:
            conn = self._connect()
            try:
                results: list[dict[str, Any]] = []
                for requested_book_id in normalized_book_ids:
                    equivalent_ids = equivalent_book_ids(conn, requested_book_id)
                    if not equivalent_ids:
                        results.append(
                            {"book_id": requested_book_id, "status": "not_found"}
                        )
                        continue

                    representative_id = canonical_book_id(conn, equivalent_ids)
                    placeholders = ",".join("?" for _ in equivalent_ids)
                    file_rows = conn.execute(
                        f"""
                        SELECT id FROM book_files
                        WHERE book_id IN ({placeholders})
                          AND import_status = 'imported'
                          AND content_type = 'ebook'
                        ORDER BY id
                        """,  # noqa: S608 - only the placeholder count is generated.
                        equivalent_ids,
                    ).fetchall()
                    if not file_rows:
                        results.append(
                            {"book_id": requested_book_id, "status": "unavailable"}
                        )
                        continue

                    existing_membership = conn.execute(
                        f"""
                        SELECT 1 FROM user_library
                        WHERE user_id = ? AND book_id IN ({placeholders})
                        LIMIT 1
                        """,  # noqa: S608 - only the placeholder count is generated.
                        (normalized_user_id, *equivalent_ids),
                    ).fetchone()
                    if existing_membership is None:
                        conn.execute(
                            """
                            INSERT INTO user_library (user_id, book_id, added_at)
                            VALUES (?, ?, ?)
                            """,
                            (normalized_user_id, representative_id, _now_utc_iso()),
                        )
                    for file_row in file_rows:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO user_file_entitlements (
                                user_id, file_id, grant_source
                            ) VALUES (?, ?, 'direct')
                            """,
                            (normalized_user_id, int(file_row["id"])),
                        )
                    results.append(
                        {
                            "book_id": requested_book_id,
                            "canonical_book_id": representative_id,
                            "status": (
                                "added"
                                if existing_membership is None
                                else "already_in_library"
                            ),
                        }
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            else:
                return results
            finally:
                conn.close()

    def remove_from_library(self, *, user_id: int, book_id: int) -> bool:
        """Hard-delete the user's library row for a book. Returns True when deleted."""
        normalized_user_id = normalize_positive_int(user_id)
        normalized_book_id = self._book_identity(book_id)
        if normalized_user_id is None:
            msg = "user_id must be a positive integer"
            raise ValueError(msg)
        with self._lock:
            conn = self._connect()
            try:
                book_ids = equivalent_book_ids(conn, normalized_book_id)
                placeholders = ",".join("?" for _ in book_ids)
                cursor = conn.execute(
                    f"""
                    DELETE FROM user_library
                    WHERE user_id = ? AND book_id IN ({placeholders})
                    """,  # noqa: S608 - only the placeholder count is generated.
                    (normalized_user_id, *book_ids),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def is_in_library(self, *, user_id: int, book_id: int) -> bool:
        normalized_user_id = normalize_positive_int(user_id)
        normalized_book_id = self._book_identity(book_id)
        if normalized_user_id is None:
            return False
        conn = self._connect()
        try:
            book_ids = equivalent_book_ids(conn, normalized_book_id)
            placeholders = ",".join("?" for _ in book_ids)
            row = conn.execute(
                f"""
                SELECT 1 FROM user_library
                WHERE user_id = ? AND book_id IN ({placeholders}) LIMIT 1
                """,  # noqa: S608 - only the placeholder count is generated.
                (normalized_user_id, *book_ids),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        normalized_book_id = self._book_identity(book_id)
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (normalized_book_id,)).fetchone()
            return _row_to_book(row)
        finally:
            conn.close()

    def list_library_books(
        self,
        *,
        user_id: int | None,
        is_admin: bool,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return library books for a user, or all users when admin.

        Per #04 sub-decision 9: no pagination for MVP. Per sub-decision 10:
        ``?q=`` is a case-insensitive LIKE on title/author. Ordered by
        ``user_library.added_at DESC``.
        """
        params: list[Any] = []
        where_clauses: list[str] = []
        if not is_admin:
            normalized_user_id = normalize_positive_int(user_id)
            if normalized_user_id is None:
                return []
            where_clauses.append("ul.user_id = ?")
            params.append(normalized_user_id)
            where_clauses.append(
                "EXISTS (SELECT 1 FROM user_file_entitlements ufe JOIN book_files bf ON bf.id=ufe.file_id WHERE ufe.user_id=ul.user_id AND bf.book_id=b.id AND bf.import_status='imported')"
            )

        normalized_query = normalize_optional_text(query)
        if normalized_query:
            where_clauses.append("(b.title LIKE ? OR COALESCE(b.author, '') LIKE ?)")
            like_pattern = f"%{normalized_query}%"
            params.extend([like_pattern, like_pattern])

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)
        # Query is assembled from static fragments + parameterized clauses; the
        # LIKE patterns flow through bound parameters, so string interpolation
        # here only joins fixed SQL text.
        sql = (
            "SELECT b.*, ul.added_at AS library_added_at "
            "FROM books b "
            "INNER JOIN user_library ul ON ul.book_id = b.id"
            + where_sql
            + " ORDER BY ul.added_at DESC, b.id DESC"
        )
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            books = [_row_to_book(row) or {} for row in rows]
            seen: set[str] = set()
            deduplicated: list[dict[str, Any]] = []
            for book in books:
                raw_isbn = str(book.get("isbn_13") or "").replace("-", "").replace(" ", "")
                key = (
                    f"isbn:{raw_isbn}"
                    if len(raw_isbn) == 13 and raw_isbn.isdigit()
                    else f"id:{book.get('id')}"
                )
                if key in seen:
                    continue
                seen.add(key)
                deduplicated.append(book)
            return deduplicated
        finally:
            conn.close()

    def get_files_on_disk(self, book_id: int) -> list[dict[str, Any]]:
        """Return ``download_history`` rows for a book with on-disk artifacts.

        Per #04 sub-decision 6, files are surfaced per-row (release-level
        metadata: format, size, indexer_display_name, protocol, downloaded_at).
        Per sub-decision 3, the union spans all users — no per-user attribution.
        ``downloadable_by_me`` is computed by the caller (route) from the
        union against ``user_downloads`` since it depends on the actor.
        """
        normalized_book_id = self._book_identity(book_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, task_id, source, source_display_name, title, author,
                       format, size, content_type, download_path,
                       username, user_id AS triggering_user_id, queued_at,
                       terminal_at, final_status
                FROM download_history
                WHERE book_id = ?
                  AND final_status = ?
                  AND download_path IS NOT NULL
                ORDER BY terminal_at DESC, id DESC
                """,
                (normalized_book_id, _COMPLETE_DOWNLOAD_STATUS),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_in_flight_files(self, book_id: int) -> list[dict[str, Any]]:
        """Return in-flight ``download_history`` rows for a book (any user)."""
        normalized_book_id = self._book_identity(book_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, task_id, source, source_display_name, title, author,
                       format, size, content_type, username, queued_at,
                       final_status
                FROM download_history
                WHERE book_id = ? AND final_status = ?
                ORDER BY queued_at DESC, id DESC
                """,
                (normalized_book_id, _ACTIVE_DOWNLOAD_STATUS),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def files_exist_globally(self, book_id: int) -> bool:
        """Per #04 sub-decision 12: complete rows with a non-null ``download_path``."""
        normalized_book_id = self._book_identity(book_id)
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM download_history
                WHERE book_id = ? AND final_status = ? AND download_path IS NOT NULL
                LIMIT 1
                """,
                (normalized_book_id, _COMPLETE_DOWNLOAD_STATUS),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def in_flight_globally(self, book_id: int) -> bool:
        """Per #04 sub-decision 12: any active row for the book."""
        normalized_book_id = self._book_identity(book_id)
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM download_history
                WHERE book_id = ? AND final_status = ?
                LIMIT 1
                """,
                (normalized_book_id, _ACTIVE_DOWNLOAD_STATUS),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_release_library_states(
        self, *, task_ids: list[str], user_id: int | None
    ) -> dict[str, dict[str, Any]]:
        """Return on-disk and current-user library state for release task ids."""
        normalized_task_ids = sorted({task_id.strip() for task_id in task_ids if task_id.strip()})
        if not normalized_task_ids:
            return {}
        normalized_user_id = normalize_positive_int(user_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT task_id, MAX(book_id) AS book_id
                FROM download_history
                WHERE task_id IN (SELECT value FROM json_each(?))
                  AND final_status = ?
                  AND download_path IS NOT NULL
                GROUP BY task_id
                """,
                [json.dumps(normalized_task_ids), _COMPLETE_DOWNLOAD_STATUS],
            ).fetchall()
            states = {
                task_id: {"is_on_disk": False, "book_id": None, "in_my_library": False}
                for task_id in normalized_task_ids
            }
            for row in rows:
                task_id = str(row["task_id"])
                book_id = row["book_id"]
                states[task_id]["is_on_disk"] = True
                states[task_id]["book_id"] = int(book_id) if book_id is not None else None

            book_ids = [
                state["book_id"] for state in states.values() if state["book_id"] is not None
            ]
            if normalized_user_id is not None and book_ids:
                memberships = conn.execute(
                    """
                    SELECT book_id FROM user_library
                    WHERE user_id = ? AND book_id IN (SELECT value FROM json_each(?))
                    """,
                    [normalized_user_id, json.dumps(book_ids)],
                ).fetchall()
                member_book_ids = {int(row["book_id"]) for row in memberships}
                for state in states.values():
                    state["in_my_library"] = state["book_id"] in member_book_ids
            return states
        finally:
            conn.close()

    def get_metadata_library_states(
        self, *, book_keys: list[tuple[str, str]], user_id: int | None
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Return library membership for provider-backed metadata search results."""
        normalized_keys = sorted(
            {
                (provider.strip(), provider_book_id.strip())
                for provider, provider_book_id in book_keys
                if provider.strip() and provider_book_id.strip()
            }
        )
        if not normalized_keys:
            return {}
        normalized_user_id = normalize_positive_int(user_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT b.metadata_provider, b.provider_book_id, b.id AS book_id,
                       ul.book_id IS NOT NULL AS in_my_library
                FROM books b
                LEFT JOIN user_library ul ON ul.book_id = b.id AND ul.user_id = ?
                WHERE EXISTS (
                    SELECT 1 FROM json_each(?) AS requested
                    WHERE b.metadata_provider = json_extract(requested.value, '$.provider')
                      AND b.provider_book_id = json_extract(requested.value, '$.provider_book_id')
                )
                """,
                [
                    normalized_user_id,
                    json.dumps(
                        [
                            {"provider": provider, "provider_book_id": provider_book_id}
                            for provider, provider_book_id in normalized_keys
                        ]
                    ),
                ],
            ).fetchall()
            return {
                (str(row["metadata_provider"]), str(row["provider_book_id"])): {
                    "book_id": int(row["book_id"]),
                    "in_my_library": bool(row["in_my_library"]),
                }
                for row in rows
            }
        finally:
            conn.close()

    def get_download_history_row(self, history_id: int) -> dict[str, Any] | None:
        normalized_history_id = self._history_identity(history_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM download_history WHERE id = ?",
                (normalized_history_id,),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    def link_download_to_user(self, *, user_id: int, book_id: int, history_id: int) -> bool:
        """Idempotently link a ``download_history`` row to a user's library.

        Per #04 sub-decision 3: ``INSERT OR IGNORE`` into ``user_downloads``.
        The book_id argument is for ownership/membership validation by the
        caller; this insert only needs (user_id, history_id).
        """
        normalized_user_id = normalize_positive_int(user_id)
        normalized_history_id = self._history_identity(history_id)
        self._book_identity(book_id)
        if normalized_user_id is None:
            msg = "user_id must be a positive integer"
            raise ValueError(msg)
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO user_downloads (user_id, history_id, added_at)
                    VALUES (?, ?, ?)
                    """,
                    (normalized_user_id, normalized_history_id, _now_utc_iso()),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def unlink_download_from_user(self, *, user_id: int, book_id: int, history_id: int) -> bool:
        """Release-atomic unlink: delete the user's ``user_downloads`` links for
        **every file row in the release** identified by ``history_id``.

        Per #13 decision (4-a-strict): the ``:history_id`` identifies any file
        row of the release; the service fans out across sibling file rows
        sharing the same ``task_id`` and deletes ``user_downloads`` links for
        all of them for the requesting user. The underlying ``download_history``
        rows and the on-disk files are untouched. Per-file unlink within a
        release is out of scope (releases own atomically). Returns ``True`` if
        any link was removed.
        """
        normalized_user_id = normalize_positive_int(user_id)
        normalized_history_id = self._history_identity(history_id)
        self._book_identity(book_id)
        if normalized_user_id is None:
            msg = "user_id must be a positive integer"
            raise ValueError(msg)
        with self._lock:
            conn = self._connect()
            try:
                task_id = conn.execute(
                    "SELECT task_id FROM download_history WHERE id = ?",
                    (normalized_history_id,),
                ).fetchone()
                if task_id is None:
                    # No row to derive task_id from — nothing to unlink.
                    # Preserves the #08 #04 sub-decision 7 "file/history untouched"
                    # invariant and the mid-flight-404 UX (no link row yet).
                    return False
                normalized_task_id = (
                    str(task_id["task_id"]) if task_id["task_id"] is not None else None
                )
                if normalized_task_id is None:
                    # Fall back to per-row unlink when task_id is unavailable.
                    cursor = conn.execute(
                        "DELETE FROM user_downloads WHERE user_id = ? AND history_id = ?",
                        (normalized_user_id, normalized_history_id),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
                # Fan out across every sibling file row sharing the task_id.
                cursor = conn.execute(
                    """
                    DELETE FROM user_downloads
                    WHERE user_id = ? AND history_id IN (
                        SELECT id FROM download_history WHERE task_id = ?
                    )
                    """,
                    (normalized_user_id, normalized_task_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def download_linked_to_user(self, *, user_id: int, history_id: int) -> bool:
        """Whether a ``download_history`` row is linked to a user via ``user_downloads``."""
        normalized_user_id = normalize_positive_int(user_id)
        normalized_history_id = self._history_identity(history_id)
        if normalized_user_id is None:
            return False
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM user_downloads
                WHERE user_id = ? AND history_id = ?
                LIMIT 1
                """,
                (normalized_user_id, normalized_history_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def _iso_to_epoch(value: object) -> float | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
