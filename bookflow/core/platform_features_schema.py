"""Additive schema for pairing, web push, metadata governance, and backups."""

from __future__ import annotations

PLATFORM_FEATURES_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS kobo_pairing_codes (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nonce_hash TEXT NOT NULL UNIQUE,
    origin TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    claimed_at TEXT,
    consumed_at TEXT,
    session_hash TEXT UNIQUE,
    session_expires_at TEXT,
    token_id INTEGER REFERENCES kobo_tokens(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kobo_pairing_expiry
    ON kobo_pairing_codes(expires_at, consumed_at);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint_hash TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth_secret TEXT NOT NULL,
    device_label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_success_at TEXT,
    revoked_at TEXT,
    UNIQUE(user_id, endpoint_hash)
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_active
    ON push_subscriptions(user_id, revoked_at);

CREATE TABLE IF NOT EXISTS notification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, event_type)
);

CREATE TABLE IF NOT EXISTS metadata_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fields_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open', 'accepted', 'rejected')),
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    review_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_metadata_reports_queue
    ON metadata_reports(status, created_at);

CREATE TABLE IF NOT EXISTS book_metadata_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    source TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_book_metadata_revisions_book
    ON book_metadata_revisions(book_id, id DESC);

CREATE TABLE IF NOT EXISTS book_metadata_provenance (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    source TEXT NOT NULL,
    source_identifier TEXT,
    revision_id INTEGER REFERENCES book_metadata_revisions(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(book_id, field_name)
);

CREATE TABLE IF NOT EXISTS backup_records (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0 CHECK(encrypted IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK(status IN ('available', 'staged', 'invalid', 'deleted')),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_at TEXT
);
"""
