"""Schema owned by the Dutch Bestseller 60 suggestion feature.

The migration is deliberately kept outside :mod:`user_db` so the feature's
storage contract remains independently reviewable.  ``UserDB`` owns adding it
as the next immutable migration version.
"""

BESTSELLER60_MIGRATION_SQL = """
-- Existing Books are normal catalog records.  Only rows created exclusively
-- from a weekly suggestion start hidden until somebody asks for the book.
ALTER TABLE books ADD COLUMN catalog_visible INTEGER NOT NULL DEFAULT 1
    CHECK (catalog_visible IN (0, 1));

CREATE INDEX idx_books_catalog_visible ON books (catalog_visible, id);

CREATE TABLE bestseller_sync_state (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    last_checked_at       TEXT,
    next_check_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_year        INTEGER,
    last_seen_week        INTEGER,
    last_success_snapshot_id INTEGER REFERENCES bestseller_snapshots(id)
        DEFERRABLE INITIALLY DEFERRED,
    last_error            TEXT,
    lease_owner           TEXT,
    lease_expires_at      TEXT,
    updated_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bestseller_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_year     INTEGER NOT NULL CHECK (source_year BETWEEN 2000 AND 2999),
    source_week     INTEGER NOT NULL CHECK (source_week BETWEEN 1 AND 53),
    status          TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    is_active       INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    fetched_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT,
    UNIQUE (source_year, source_week)
);

CREATE UNIQUE INDEX idx_bestseller_snapshots_one_active
ON bestseller_snapshots (is_active) WHERE is_active = 1;

CREATE INDEX idx_bestseller_snapshots_completed
ON bestseller_snapshots (status, source_year DESC, source_week DESC);

CREATE TABLE bestseller_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL REFERENCES bestseller_snapshots(id) ON DELETE CASCADE,
    list_key        TEXT NOT NULL CHECK (list_key IN (
        'overall', 'fiction', 'non_fiction', 'thriller', 'youth', 'cooking'
    )),
    list_rank       INTEGER NOT NULL CHECK (list_rank > 0),
    isbn_13         TEXT NOT NULL CHECK (length(isbn_13) = 13 AND isbn_13 NOT GLOB '*[^0-9]*'),
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE RESTRICT,
    source_title    TEXT NOT NULL,
    source_author   TEXT,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_id, list_key, isbn_13)
);

CREATE INDEX idx_bestseller_entries_snapshot_list_rank
ON bestseller_entries (snapshot_id, list_key, list_rank, id);

CREATE INDEX idx_bestseller_entries_book ON bestseller_entries (book_id);

CREATE TABLE bestseller_metadata_enrichment (
    isbn_13             TEXT PRIMARY KEY CHECK (
        length(isbn_13) = 13 AND isbn_13 NOT GLOB '*[^0-9]*'
    ),
    book_id             INTEGER REFERENCES books(id) ON DELETE SET NULL,
    metadata_state      TEXT NOT NULL CHECK (metadata_state IN (
        'complete', 'partial', 'missing', 'transient_error', 'invalid'
    )),
    metadata_provider   TEXT,
    cover_state         TEXT NOT NULL DEFAULT 'unknown' CHECK (cover_state IN (
        'unknown', 'complete', 'missing', 'transient_error'
    )),
    last_attempt_at     TEXT,
    next_retry_at       TEXT,
    last_error          TEXT,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_bestseller_enrichment_retry
ON bestseller_metadata_enrichment (next_retry_at)
WHERE next_retry_at IS NOT NULL;

INSERT OR IGNORE INTO bestseller_sync_state (id, next_check_at)
VALUES (1, CURRENT_TIMESTAMP);
"""
