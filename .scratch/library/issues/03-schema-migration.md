Type: task
Status: resolved
Blocked by: 01
Assignee: glm-5.2-fast (claimed 2026-07-20; resolved 2026-07-20)

# Implement the books / authors / user_library schema and migration

## Question

Manual execution ticket: write the schema and migration per the model in ticket #01, in the codebase's hand-rolled `ALTER TABLE` style (`bookflow/core/user_db.py:196-271`, `_migrate_*` helpers gated by `PRAGMA table_info(...)` checks). Register the migration in `UserDB.initialize()`.

Net-new tables (final list depends on #01 outcome — likely shape):

- `books` — `id`, `metadata_provider`, `provider_book_id` (unique pair), `title`, `author` (or normalized to `authors` if #01 decides so), `subtitle`, `year`, `series`, `series_position`, `cover_url`, `metadata_json` (raw payload from provider for fields not promoted to columns), `created_at`, `updated_at`.
- `user_library` — `user_id` (FK→users), `book_id` (FK→books), `added_at`, PK `(user_id, book_id)`. (No "removed_at" — removal deletes the row; files stay.)
- `user_downloads` — `user_id` (FK→users ON DELETE CASCADE), `history_id` (FK→download_history ON DELETE CASCADE), `added_at`, PK `(user_id, history_id)`. (Added by #04 — the per-user-per-release link between a user's library and a `download_history` row. #01 / ADR 0001 unchanged.) Plus `idx_user_downloads_history` on `(history_id)` to support the Orphan reverse query (`download_history` rows with zero `user_downloads` entries).

Link the existing `download_history` table to `books`: add nullable `book_id` FK. Backfill: best-effort match against `download_history` rows that carry `book_data` JSON in their `retry_payload` (`bookflow/core/user_db.py:70-91`). The backfill must be idempotent — running it twice should not duplicate book rows. Decide: backfill runs against all history at migration time, or the link is made lazily on next access. Pick one and document.

Constraints to honour:

- The migration runs against the live `users.db` of an existing BookFlow instance (your personal fork). Don't drop or rewrite `download_history`. New columns and tables only.
- SQLite has no real FK enforcement by default — add FK constraints declaratively for documentation but treat enforcement as application-layer.
- Existing per-source/per-content-type request policies (`bookflow/main.py:395-433`) must not be affected.

Verification on completion: `make python-checks` passes; running the container against an existing populated `users.db` upgrades cleanly without losing existing `download_history` rows; a freshly-initialized `users.db` from `UserDB.initialize()` produces all new tables.

## Outcome of this ticket

Code on a feature branch touching `bookflow/core/user_db.py` and possibly `bookflow/core/models.py`. No UI, no API endpoints — those live in #04. Document in the resolution: the migration approach, the backfill decision, and the file:line where the new CREATE TABLE statements live.

## Answer

Resolved 2026-07-20 by task execution on branch `feature/library-schema`. Schema lives in `bookflow/core/user_db.py`:

- **`books` table** — `_CREATE_TABLES_SQL` lines 122-139 (`bookflow/core/user_db.py:122`). Columns exactly per #01's sketch: `id`, `metadata_provider` NOT NULL, `provider_book_id` NOT NULL, `title` NOT NULL, `author`, `subtitle`, `publish_year`, `isbn_13`, `cover_url`, `series_name`, `series_position` (REAL), `language`, `metadata_json` NOT NULL DEFAULT `'{}'`, `created_at`, `updated_at`, `UNIQUE(metadata_provider, provider_book_id)`. Explicit `idx_books_provider` index at `:141` to mirror #01's hot-read expectation (the UNIQUE constraint also creates an autoindex — the explicit index exists so the read path has a named, queryable handle and stays stable if the UNIQUE is ever refactored).
- **`user_library` table** — `:144`, PK `(user_id, book_id)`, both `ON DELETE CASCADE`. `idx_user_library_book_id_added_at` at `:151` covers the inverse "which users have this book + most-recent-first" lookup that #04/#10 will hit.
- **`user_downloads` table** — `:154` per #04, PK `(user_id, history_id)`, both `ON DELETE CASCADE`. `idx_user_downloads_history` at `:161` supports the Orphan reverse query per CONTEXT.md.
- **`download_history.book_id`** — added by `_migrate_download_history_book_id(conn)` at `:288-303`. The migration is a conditional `PRAGMA table_info` guard pattern (matches `_migrate_download_history_queued_at` / `_migrate_download_history_retry_payload`); nullable, `REFERENCES books(id) ON DELETE SET NULL`. Followed by `CREATE INDEX IF NOT EXISTS idx_download_history_book_id ON download_history(book_id, final_status)` — placed inside the migration helper, not in `_CREATE_TABLES_SQL`, because `_CREATE_TABLES_SQL` runs first in `initialize()` and the index creation must post-date the column-add for the upgrade path. The legacy `download_history` CREATE TABLE block (no `book_id`) is preserved verbatim per the no-rewrite constraint.

### Migration approach

Conditional `ALTER TABLE` gated by `PRAGMA table_info` checks, registered as `self._migrate_download_history_book_id(conn)` inside `UserDB.initialize()` (`user_db.py:247`) alongside the existing `_migrate_*` helpers. New tables go through `_CREATE_TABLES_SQL` (all `CREATE TABLE IF NOT EXISTS`). Idempotent: re-running `initialize()` re-runs the migration helpers safely. WAL pragma fires after migrations, unchanged.

### Backfill decision

**No backfill; lazy-link is the model.** This ticket overrides the original question's two options ("backfill all history" vs "lazy-link on next access") — neither is exercised. The library starts from a **fresh database**: no legacy `download_history` rows need a `book_id` backfill. The `user_db.initialize()` upgrade path is preserved for pre-library `users.db` files, but it only *adds the nullable column and the index* — it never inserts `books` rows or sets `book_id`. Legacy rows (if any) keep `book_id IS NULL` and remain invisible to library queries, matching invariant #01 ("legacy / direct-mode / un-lined rows have `book_id IS NULL`"). Book rows are minted on Add-to-Library going forward.

This sidesteps the data-availability gap that drove the decision during execution: a backfill from `download_history.retry_payload` is **not possible** — `retry_payload` is the serialized `DownloadTask` (`orchestrator.py:445-499`), which carries `(task_id, source, title, author, ...)` and no `(metadata_provider, provider_book_id)` natural key. There's no source-of-truth for the books natural key in `download_history`. So even if backfill were wanted, the migration couldn't compute it from on-disk state alone.

### Verification

- `make python-checks` passes (ruff, ruff-format, basedpyright, basedpyright on tests, vulture).
- 12 new tests covering table creation, index creation, contract enforcement (UNIQUE pair rejects dups including cross-provider, NOT NULL pair rejects NULLs, composite PK enforcing), and the upgrade-path (`test_initialize_adds_book_id_and_library_tables_to_legacy_install`: pre-library DB gains the new schema and the legacy row survives `book_id IS NULL`, plus idempotency on re-run). All 69 tests in `tests/core/test_user_db.py` pass.
- `models.py` was not touched — the `books` shape is a schema decision owned by `user_db.py`'s `CREATE TABLE` statements, not a dataclass (matches existing precedent: `users`, `download_requests`, etc. live only as SQL).

### Downstream tickets now unblocked

- **#06** (Library API implementation) — its data-layer prerequisites are now in place.
- **#11** (Search integration impl), **#12** (Author browse MVP) blocked on #06.
- Existing FK conventions (`ON DELETE CASCADE` for `user_library` / `user_downloads`; `ON DELETE SET NULL` for `download_history.book_id`) are now load-bearing — #06's API implementation must respect them rather than inventing its own delete rules.
