"""Durable author/series monitoring against explicitly capable providers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from bookflow.core.book_matcher import BookMatchInput
from bookflow.core.catalog_relations import sync_book_catalog_relations
from bookflow.core.catalog_service import CatalogService
from bookflow.core.durable_jobs import DurableJobService
from bookflow.core.metadata_governance import record_provider_observation
from bookflow.core.request_workflow_service import RequestWorkflowService
from bookflow.metadata_providers import (
    MetadataSearchOptions,
    SearchType,
    get_provider,
    get_provider_kwargs,
    get_provider_monitoring_capabilities,
)

MONITOR_SCAN_JOB = "scan_monitor"


class MonitorRuntime:
    def __init__(
        self,
        db_path: str,
        *,
        notify: Callable[[int, dict[str, Any]], None] | None = None,
    ) -> None:
        self._db_path = db_path
        self._jobs = DurableJobService(db_path)
        self._catalog = CatalogService(db_path)
        self._requests = RequestWorkflowService(db_path)
        self._notify = notify

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def schedule_due(self, now: datetime) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, next_scan_at FROM monitors
                WHERE status = 'active' AND next_scan_at IS NOT NULL
                  AND next_scan_at <= ?
                ORDER BY next_scan_at, id
                """,
                (now.isoformat(timespec="seconds"),),
            ).fetchall()
        for row in rows:
            due = str(row["next_scan_at"]).replace(" ", "T")
            self._jobs.enqueue(
                job_key=f"scan-monitor:{int(row['id'])}:{due}",
                job_type=MONITOR_SCAN_JOB,
                payload={"monitor_id": int(row["id"])},
                run_at=now,
                max_attempts=3,
            )
        return len(rows)

    def process(self, payload: dict[str, Any]) -> None:
        monitor_id = payload.get("monitor_id")
        if not isinstance(monitor_id, int) or monitor_id < 1:
            raise ValueError("monitor_id is required")
        with self._connect() as conn:
            monitor = conn.execute(
                "SELECT * FROM monitors WHERE id = ? AND status = 'active'",
                (monitor_id,),
            ).fetchone()
        if monitor is None:
            return
        provider_name = str(monitor["provider"])
        monitor_type = str(monitor["monitor_type"])
        if monitor_type not in get_provider_monitoring_capabilities(provider_name):
            raise ValueError(f"{provider_name} does not support {monitor_type} monitoring")
        provider = get_provider(provider_name, **get_provider_kwargs(provider_name))
        if not provider.is_available():
            raise RuntimeError(f"{provider_name} is not configured")
        query = str(monitor["query"])
        try:
            search_profile = json.loads(str(monitor["search_profile_json"] or "{}"))
        except KeyError, json.JSONDecodeError:
            search_profile = {}
        if not isinstance(search_profile, dict):
            search_profile = {}
        configured_fields = search_profile.get("fields", {})
        fields = (
            {
                str(key): str(value)
                for key, value in configured_fields.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            if isinstance(configured_fields, dict)
            else {}
        )
        fields.setdefault(monitor_type, query)
        provider_id = str(monitor["provider_id"] or "").strip()
        if provider_id:
            if provider_name == "hardcover":
                fields[monitor_type] = (
                    provider_id if provider_id.startswith("id:") else f"id:{provider_id}"
                )
            elif provider_name == "openlibrary" and monitor_type == "author":
                fields["author_key"] = provider_id.removeprefix("/authors/")
        search_type = SearchType.AUTHOR if monitor_type == "author" else SearchType.GENERAL
        requested_limit = search_profile.get("limit", 100)
        limit = requested_limit if isinstance(requested_limit, int) else 100
        language = search_profile.get("language")
        books = provider.search(
            MetadataSearchOptions(
                query=query,
                search_type=search_type,
                fields=fields,
                language=language if isinstance(language, str) else None,
                limit=min(100, max(1, limit)),
            )
        )
        for book in books:
            self._record(monitor, book)
        self._finish_scan(monitor)

    def _record(self, monitor: sqlite3.Row, book: Any) -> None:
        provider = str(book.provider)
        provider_book_id = str(book.provider_id)
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT book_id FROM book_provider_identifiers
                WHERE provider = ? AND provider_book_id = ?
                """,
                (provider, provider_book_id),
            ).fetchone()
        canonical = self._catalog.get_or_create_book(
            BookMatchInput(
                title=str(book.title),
                author=str(book.authors[0]) if book.authors else None,
                language=book.language,
                publish_year=book.publish_year,
                provider=provider,
                provider_book_id=provider_book_id,
                isbn=book.isbn_13 or book.isbn_10,
            )
        )
        now_year = datetime.now(UTC).year
        state = (
            "present"
            if existing is not None
            else "future"
            if book.publish_year is not None and book.publish_year > now_year
            else "discovered"
        )
        metadata = asdict(book)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE books SET subtitle = COALESCE(?, subtitle),
                    cover_url = COALESCE(?, cover_url),
                    series_name = COALESCE(?, series_name),
                    series_position = COALESCE(?, series_position),
                    metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    book.subtitle,
                    book.cover_url,
                    book.series_name,
                    book.series_position,
                    json.dumps(metadata, sort_keys=True, default=str),
                    canonical.book_id,
                ),
            )
            sync_book_catalog_relations(
                conn,
                book_id=canonical.book_id,
                authors=book.authors,
                series_name=book.series_name,
                series_position=book.series_position,
            )
            record_provider_observation(
                conn,
                book_id=canonical.book_id,
                source=provider,
                source_identifier=provider_book_id,
                payload=metadata,
            )
            cursor = conn.execute(
                """
                INSERT INTO monitor_discoveries
                    (monitor_id, provider, provider_book_id, book_id, state, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id, provider, provider_book_id) DO UPDATE SET
                    book_id = excluded.book_id,
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(monitor["id"]),
                    provider,
                    provider_book_id,
                    canonical.book_id,
                    state,
                    json.dumps(metadata, sort_keys=True, default=str),
                ),
            )
            is_new = cursor.rowcount == 1 and existing is None
        if not is_new or state == "future":
            return
        action = str(monitor["action"])
        if action in {"request", "auto_acquire"}:
            try:
                search_profile = json.loads(str(monitor["search_profile_json"] or "{}"))
            except KeyError, json.JSONDecodeError:
                search_profile = {}
            request_process_profile = (
                search_profile.get("request_process_profile", {})
                if isinstance(search_profile, dict)
                else {}
            )
            if not isinstance(request_process_profile, dict):
                request_process_profile = {}
            request_row = self._requests.create_request(
                user_id=int(monitor["user_id"]),
                book_id=canonical.book_id,
                profile=request_process_profile,
                note=f"Discovered by {monitor['monitor_type']} monitor",
                add_to_kobo_when_available=bool(monitor["add_to_kobo"]),
            )
            if action == "auto_acquire" and str(request_row["status"]) == "pending_approval":
                reviewer_id = self._admin_reviewer(int(monitor["user_id"]))
                if reviewer_id is None:
                    raise RuntimeError(
                        "No active administrator can approve automatic request_process"
                    )
                self._requests.approve_request(int(request_row["id"]), reviewer_user_id=reviewer_id)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE monitor_discoveries SET state = 'requested', updated_at = CURRENT_TIMESTAMP
                    WHERE monitor_id = ? AND provider = ? AND provider_book_id = ?
                    """,
                    (int(monitor["id"]), provider, provider_book_id),
                )
        if self._notify is not None:
            self._notify(
                int(monitor["user_id"]),
                {
                    "title": "Nieuwe titel ontdekt",
                    "body": str(book.title),
                    "url": f"/catalog/{canonical.book_id}",
                    "monitor_id": int(monitor["id"]),
                    "book_id": canonical.book_id,
                },
            )

    def _admin_reviewer(self, preferred_user_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM users WHERE role = 'admin' AND is_active = 1
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, id LIMIT 1
                """,
                (preferred_user_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def _finish_scan(self, monitor: sqlite3.Row) -> None:
        interval = int(monitor["scan_interval_seconds"])
        seed = f"{monitor['id']}:{datetime.now(UTC):%Y-%m-%d}".encode()
        jitter = int(hashlib.sha256(seed).hexdigest()[:8], 16) % 901
        next_scan = datetime.now(UTC) + timedelta(seconds=interval + jitter)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE monitors SET last_scanned_at = CURRENT_TIMESTAMP,
                    next_scan_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_scan.isoformat(timespec="seconds"), int(monitor["id"])),
            )
