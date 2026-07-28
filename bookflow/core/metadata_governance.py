"""Field-level metadata corrections with append-only provenance."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from bookflow.core.web_push_events import enqueue_web_push

EDITABLE_BOOK_FIELDS = frozenset(
    {
        "title",
        "author",
        "subtitle",
        "publish_year",
        "isbn_13",
        "cover_url",
        "series_name",
        "series_position",
        "language",
        "description",
    }
)
_FIELD_UPDATE_SQL = {
    "title": "UPDATE books SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "author": "UPDATE books SET author = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "subtitle": "UPDATE books SET subtitle = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "publish_year": "UPDATE books SET publish_year = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "isbn_13": "UPDATE books SET isbn_13 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "cover_url": "UPDATE books SET cover_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "series_name": "UPDATE books SET series_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
    "series_position": (
        "UPDATE books SET series_position = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
    ),
    "language": "UPDATE books SET language = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
}


def _snapshot(row: sqlite3.Row) -> dict[str, Any]:
    values = {field: row[field] for field in EDITABLE_BOOK_FIELDS if field != "description"}
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    values["description"] = metadata.get("description")
    return values


def _metadata_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _candidate_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = {field: payload.get(field) for field in EDITABLE_BOOK_FIELDS}
    authors = payload.get("authors")
    if isinstance(authors, list):
        values["author"] = ", ".join(
            str(author).strip() for author in authors if str(author).strip()
        )
    return {field: value for field, value in values.items() if value is not None}


def record_provider_observation(
    conn: sqlite3.Connection,
    *,
    book_id: int,
    source: str,
    source_identifier: str | None,
    payload: dict[str, Any],
) -> None:
    """Append changed provider field observations without mutating the Book snapshot."""
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'book_metadata_field_events'"
    ).fetchone()
    if table is None:
        return
    normalized_source = str(source or "provider").strip()[:100] or "provider"
    normalized_identifier = (
        str(source_identifier).strip()[:500] if source_identifier is not None else None
    )
    for field, value in _candidate_values(payload).items():
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        latest = conn.execute(
            """
            SELECT value_json FROM book_metadata_field_events
            WHERE book_id = ? AND field_name = ? AND source = ?
              AND COALESCE(source_identifier, '') = COALESCE(?, '')
              AND event_type IN ('observed', 'snapshot')
            ORDER BY id DESC LIMIT 1
            """,
            (book_id, field, normalized_source, normalized_identifier),
        ).fetchone()
        if latest is not None and str(latest[0]) == encoded:
            continue
        conn.execute(
            """
            INSERT INTO book_metadata_field_events(
                book_id, field_name, value_json, source, source_identifier, event_type
            ) VALUES (?, ?, ?, ?, ?, 'observed')
            """,
            (book_id, field, encoded, normalized_source, normalized_identifier),
        )


def _provider_candidates(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    payload = _metadata_payload(row)
    candidates: list[dict[str, Any]] = []
    values = _candidate_values(payload)
    if values:
        candidates.append(
            {
                "source": str(payload.get("provider") or row["metadata_provider"]),
                "source_identifier": payload.get("provider_id") or row["provider_book_id"],
                "values": values,
            }
        )
    alternatives = payload.get("provider_values")
    if isinstance(alternatives, list):
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                continue
            alternative_values = alternative.get("values")
            if not isinstance(alternative_values, dict):
                alternative_values = alternative
            selected = {
                field: alternative_values[field]
                for field in EDITABLE_BOOK_FIELDS
                if field in alternative_values
            }
            if selected:
                candidates.append(
                    {
                        "source": str(alternative.get("source") or "provider"),
                        "source_identifier": alternative.get("source_identifier"),
                        "values": selected,
                    }
                )
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'book_metadata_field_events'"
    ).fetchone()
    if table is not None:
        rows = conn.execute(
            """
            SELECT source, source_identifier, field_name, value_json
            FROM book_metadata_field_events
            WHERE book_id = ? AND event_type IN ('observed', 'snapshot')
            ORDER BY id DESC
            """,
            (int(row["id"]),),
        ).fetchall()
        grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
        seen_fields: set[tuple[str, str | None, str]] = set()
        for event in rows:
            source = str(event["source"])
            identifier = (
                str(event["source_identifier"]) if event["source_identifier"] is not None else None
            )
            field = str(event["field_name"])
            field_key = (source, identifier, field)
            if field_key in seen_fields or field not in EDITABLE_BOOK_FIELDS:
                continue
            seen_fields.add(field_key)
            try:
                value = json.loads(str(event["value_json"]))
            except json.JSONDecodeError:
                continue
            grouped.setdefault((source, identifier), {})[field] = value
        for (source, identifier), values in grouped.items():
            candidates.append(
                {
                    "source": source,
                    "source_identifier": identifier,
                    "values": values,
                }
            )
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        fingerprint = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(candidate)
    return unique


class MetadataGovernanceService:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def report(
        self, *, user_id: int, book_id: int, fields: list[str], explanation: str
    ) -> dict[str, Any]:
        normalized = sorted(set(fields) & EDITABLE_BOOK_FIELDS)
        if not normalized or not explanation.strip():
            raise ValueError("Select at least one field and provide an explanation")
        with self._connect() as conn:
            book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if book is None:
                raise LookupError("Book not found")
            cursor = conn.execute(
                """
                INSERT INTO metadata_reports (book_id, user_id, fields_json, explanation)
                VALUES (?, ?, ?, ?)
                """,
                (book_id, user_id, json.dumps(normalized), explanation.strip()[:2000]),
            )
            for candidate in _provider_candidates(conn, book):
                for field, value in candidate["values"].items():
                    conn.execute(
                        """
                        INSERT INTO book_metadata_field_events(
                            book_id, field_name, value_json, source, source_identifier,
                            actor_user_id, event_type
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 'observed')
                        """,
                        (
                            book_id,
                            field,
                            json.dumps(value, ensure_ascii=False, sort_keys=True),
                            candidate["source"],
                            candidate["source_identifier"],
                            user_id,
                        ),
                    )
        if cursor.lastrowid is None:
            raise RuntimeError("Metadata report did not receive an id")
        report_id = cursor.lastrowid
        enqueue_web_push(
            self._db_path,
            user_id=user_id,
            event_type="metadata_report.status",
            payload={
                "report_id": report_id,
                "book_id": book_id,
                "status": "open",
                "url": f"/catalog/{book_id}",
            },
            event_key=f"metadata-report:{report_id}:open",
        )
        return {"id": report_id, "status": "open"}

    def reports(self, *, status: str = "open", user_id: int | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    """
                    SELECT metadata_reports.*, books.title
                    FROM metadata_reports JOIN books ON books.id = metadata_reports.book_id
                    WHERE metadata_reports.status = ? ORDER BY metadata_reports.created_at
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT metadata_reports.*, books.title
                    FROM metadata_reports JOIN books ON books.id = metadata_reports.book_id
                    WHERE metadata_reports.status = ? AND metadata_reports.user_id = ?
                    ORDER BY metadata_reports.created_at
                    """,
                    (status, user_id),
                ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["fields"] = json.loads(item.pop("fields_json"))
            item.update(self.review_context(book_id=int(row["book_id"])))
            items.append(item)
        return items

    def review_context(self, *, book_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if row is None:
                raise LookupError("Book not found")
            return {
                "current_values": _snapshot(row),
                "provider_values": _provider_candidates(conn, row),
            }

    def reject_report(self, *, actor_user_id: int, report_id: int, note: str) -> dict[str, Any]:
        if not note.strip():
            raise ValueError("A review note is required")
        with self._connect() as conn:
            report = conn.execute(
                "SELECT user_id, book_id FROM metadata_reports WHERE id = ? AND status = 'open'",
                (report_id,),
            ).fetchone()
            cursor = conn.execute(
                """
                UPDATE metadata_reports SET status = 'rejected', reviewed_by = ?,
                    review_note = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'open'
                """,
                (actor_user_id, note.strip()[:1000], report_id),
            )
        if cursor.rowcount != 1:
            raise LookupError("Report not found")
        if report is not None:
            enqueue_web_push(
                self._db_path,
                user_id=int(report["user_id"]),
                event_type="metadata_report.status",
                payload={
                    "report_id": report_id,
                    "book_id": int(report["book_id"]),
                    "status": "rejected",
                    "url": f"/catalog/{int(report['book_id'])}",
                },
                event_key=f"metadata-report:{report_id}:rejected",
            )
        return {"id": report_id, "status": "rejected"}

    def preview(self, *, book_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        selected = {key: value for key, value in changes.items() if key in EDITABLE_BOOK_FIELDS}
        if not selected:
            raise ValueError("No editable metadata fields supplied")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if row is None:
                raise LookupError("Book not found")
            current = _snapshot(row)
            return {
                "book_id": book_id,
                "current_values": current,
                "provider_values": _provider_candidates(conn, row),
                "changes": [
                    {"field": field, "before": current[field], "after": value}
                    for field, value in selected.items()
                    if current[field] != value
                ],
            }

    def apply(
        self,
        *,
        actor_user_id: int,
        book_id: int,
        changes: dict[str, Any],
        reason: str,
        source: str = "admin",
        report_id: int | None = None,
    ) -> dict[str, Any]:
        preview = self.preview(book_id=book_id, changes=changes)
        changed = {item["field"]: item["after"] for item in preview["changes"]}
        if not changed or not reason.strip():
            raise ValueError("A reason and at least one changed value are required")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            report_owner = None
            if report_id is not None:
                report_owner = conn.execute(
                    "SELECT user_id FROM metadata_reports WHERE id = ? AND book_id = ? AND status = 'open'",
                    (report_id, book_id),
                ).fetchone()
            before_row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if before_row is None:
                raise LookupError("Book not found")
            before = _snapshot(before_row)
            for field, value in changed.items():
                if field == "description":
                    try:
                        metadata = json.loads(str(before_row["metadata_json"] or "{}"))
                    except json.JSONDecodeError:
                        metadata = {}
                    metadata["description"] = value
                    conn.execute(
                        """
                        UPDATE books SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (json.dumps(metadata, sort_keys=True), book_id),
                    )
                else:
                    conn.execute(_FIELD_UPDATE_SQL[field], (value, book_id))
            after_row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            if after_row is None:
                raise LookupError("Book not found")
            after = _snapshot(after_row)
            cursor = conn.execute(
                """
                INSERT INTO book_metadata_revisions
                    (book_id, actor_user_id, reason, source, before_json, after_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    actor_user_id,
                    reason.strip()[:1000],
                    source[:100],
                    json.dumps(before, sort_keys=True),
                    json.dumps(after, sort_keys=True),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Metadata revision did not receive an id")
            revision_id = cursor.lastrowid
            for field in changed:
                conn.execute(
                    """
                    INSERT INTO book_metadata_provenance
                        (book_id, field_name, source, revision_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(book_id, field_name) DO UPDATE SET
                        source = excluded.source,
                        revision_id = excluded.revision_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (book_id, field, source[:100], revision_id),
                )
                conn.execute(
                    """
                    INSERT INTO book_metadata_field_events(
                        book_id, field_name, value_json, source, revision_id,
                        actor_user_id, event_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        field,
                        json.dumps(after[field], ensure_ascii=False, sort_keys=True),
                        source[:100],
                        revision_id,
                        actor_user_id,
                        "reverted" if source.startswith("revision:") else "applied",
                    ),
                )
            if report_id is not None:
                conn.execute(
                    """
                    UPDATE metadata_reports SET status = 'accepted', reviewed_by = ?,
                        review_note = ?, reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND book_id = ? AND status = 'open'
                    """,
                    (actor_user_id, reason.strip()[:1000], report_id, book_id),
                )
        if report_id is not None and report_owner is not None:
            enqueue_web_push(
                self._db_path,
                user_id=int(report_owner["user_id"]),
                event_type="metadata_report.status",
                payload={
                    "report_id": report_id,
                    "book_id": book_id,
                    "status": "accepted",
                    "url": f"/catalog/{book_id}",
                },
                event_key=f"metadata-report:{report_id}:accepted",
            )
        return {"revision_id": revision_id, **preview}

    def history(self, *, book_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM book_metadata_revisions
                WHERE book_id = ? ORDER BY id DESC
                """,
                (book_id,),
            ).fetchall()
            event_rows = conn.execute(
                """
                SELECT * FROM book_metadata_field_events
                WHERE book_id = ? ORDER BY id DESC
                """,
                (book_id,),
            ).fetchall()
        events_by_revision: dict[int, list[dict[str, Any]]] = {}
        for row in event_rows:
            event = dict(row)
            event["value"] = json.loads(event.pop("value_json"))
            revision_id = event.get("revision_id")
            if revision_id is not None:
                events_by_revision.setdefault(int(revision_id), []).append(event)
        history = []
        for row in rows:
            revision = dict(row)
            revision["field_events"] = events_by_revision.get(int(row["id"]), [])
            history.append(revision)
        return history

    def revert(
        self, *, actor_user_id: int, book_id: int, revision_id: int, reason: str
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT before_json FROM book_metadata_revisions WHERE id = ? AND book_id = ?",
                (revision_id, book_id),
            ).fetchone()
        if row is None:
            raise LookupError("Revision not found")
        return self.apply(
            actor_user_id=actor_user_id,
            book_id=book_id,
            changes=json.loads(str(row["before_json"])),
            reason=reason,
            source=f"revision:{revision_id}",
        )
