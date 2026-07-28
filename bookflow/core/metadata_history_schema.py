"""Append-only field provenance history for governed Book metadata."""

from __future__ import annotations

METADATA_FIELD_HISTORY_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS book_metadata_field_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    source_identifier TEXT,
    revision_id INTEGER REFERENCES book_metadata_revisions(id) ON DELETE SET NULL,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL
        CHECK(event_type IN ('observed', 'applied', 'reverted', 'snapshot')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_book_metadata_field_events_book
    ON book_metadata_field_events(book_id, field_name, id DESC);
"""
