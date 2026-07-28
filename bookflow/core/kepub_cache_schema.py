"""SQL reserved for the additive KEPUB conversion-cache migration.

The constant is deliberately kept outside ``user_db.py`` until the next
versioned schema migration is scheduled.  Its uniqueness matches the filesystem
cache key and protects concurrent workers that share one catalog database.
"""

from __future__ import annotations

KEPUB_CONVERSION_CACHE_MIGRATION_SQL = """
CREATE TABLE kepub_conversion_cache (
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    converter_version TEXT NOT NULL,
    options_hash TEXT NOT NULL CHECK (length(options_hash) = 64),
    source_file_id INTEGER NOT NULL REFERENCES book_files(id) ON DELETE CASCADE,
    output_file_id INTEGER NOT NULL REFERENCES book_files(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_sha256, converter_version, options_hash),
    UNIQUE (output_file_id)
);
CREATE INDEX idx_kepub_conversion_cache_source_file
    ON kepub_conversion_cache(source_file_id);
"""
