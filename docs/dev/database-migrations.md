# Database migrations

BookFlow upgrades `users.db` through the ordered migration catalog in
`bookflow/core/user_db.py`. Applied versions, immutable checksums, timestamps,
and the last attempt status are recorded in `schema_migrations`.

Before a pending migration changes the schema, startup runs SQLite's
`integrity_check`. It then creates a transactionally consistent backup with the
SQLite backup API and writes an adjacent JSON manifest:

```text
users.db.migration-backups/
  20260727T001122.123456Z.sqlite3
  20260727T001122.123456Z.manifest.json
```

A fresh, empty database receives a manifest with `backup_path: null`. Startup
does not make another backup when no migration is pending.

Migrations run under `BEGIN IMMEDIATE`. Schema changes and the completed journal
record commit together. A failed or interrupted migration can therefore be
retried; a failure is recorded without retaining partial schema changes.
Startup stops before schema changes if the database is corrupt, contains a newer
version, or has a checksum that differs from the application catalog.

## Legacy requests

Request rows from an incompatible pre-library schema cannot be mapped safely to
a canonical Book without guessing. The baseline migration stores every such row,
its original schema, and its payload in `legacy_download_requests_review`.
Payloads are not written to logs. The canonical `download_requests` table starts
empty, and its sequence is advanced past legacy audit references so new requests
cannot accidentally reuse an old identity.

## Recovery and rollback

Do not run older application code against an upgraded database.

1. Stop BookFlow and keep it stopped.
2. Open the latest manifest and locate its exact `backup_path`.
3. Preserve the failed/current `users.db` for diagnosis.
4. Restore the backup as `users.db`.
5. Start the previous immutable BookFlow image.

For a fresh-database manifest with `backup_path: null`, remove only the newly
created disposable database before starting the previous image. Never restore a
plain copy made while SQLite WAL writers were active.
