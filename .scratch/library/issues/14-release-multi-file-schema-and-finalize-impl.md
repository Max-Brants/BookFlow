Type: task
Status: resolved
Blocked by: 13
Assignee: glm-5.2-fast (claimed 2026-07-23; resolved 2026-07-23)

# Implement #13's multi-file release schema + finalize write path

## Question

Implement the contract #13 resolved: `download_history` as one-row-per-file (one `task_id` shared across files of the same release), multi-file finalize, flat `files[]` + `task_id` API, release-atomic unlink, finalize-time `user_downloads` linking. #13 is the contract decision; #14 is the implementation. #13's Answer is the authoritative spec — read it in full before starting.

## Scope (per #13's "Implementation owner nomination")

1. **Schema migration** (`user_db.py`, #03's conditional `PRAGMA table_info`/`index_info` idiom): drop `UNIQUE` on `download_history.task_id` (sqlite table rebuild — copy rows to temp, drop+recreate without UNIQUE, copy back). Add a non-unique index on `task_id` (`idx_download_history_task_id`). Legacy rows keep their existing values; no backfill.
2. **Transfer return types** (`bookflow/download/postprocess/transfer.py`):
   - `transfer_file_to_library` (`:371`): return `list[Path]` instead of `str(final_path)`.
   - `transfer_directory_to_library` (`:478`): return `list[Path]` instead of `str(transferred_paths[0])`.
   - `transfer_book_files` (`:161-270`) already returns `list[Path]` — unchanged.
   - Audit and update every caller of the two changed functions.
3. **Task carrier**: add `task.library_paths: list[str]` to `DownloadTask`. Set it from the transfer return list (stringified). Keep `task.download_path = str(library_paths[0])` for any legacy single-path reader.
4. **`download_history_service.finalize_download_files(task_id, file_rows)`** — new method:
   - Delete the `'active'` sentinel row for `task_id`.
   - Insert N file rows (one per `(path, format, size)` in `file_rows`) with `final_status` + `terminal_at` set, sharing the same `task_id`.
   - Insert N `user_downloads(user_id, history_id)` rows for the triggering user (`download_history.user_id` of the sentinel) — one per inserted file row.
   - Atomic (single `with self._lock` + `conn.commit()`).
   - `finalize_download` (existing) becomes a thin delegate that calls `finalize_download_files` with a one-element list — preserves call signature for non-library callers.
5. **`record_download` retry path** (`download_history_service.py:313-318`): replace `ON CONFLICT(task_id) DO UPDATE SET final_status='active'...` with explicit `DELETE FROM download_history WHERE task_id=?` + sentinel `INSERT` (per-file cols NULL) inside the existing `with self._lock` transaction. Atomic.
6. **`_record_download_terminal_snapshot`** (`main.py:1435`): read `task.library_paths` (the list) instead of `task.download_path`; build `file_rows` from it (derive `format`/`size` per file at the path — plumbing, see existing `transfer_book_files` for how per-file `format` is derived from the source extension). Call `finalize_download_files`.
7. **`_serialize_book_detail`** (`library_routes.py:170-212`): add `task_id` to each entry in `files[]` and `in_flight[]`. No shape change beyond the added field.
8. **Unlink service** (`library_service.py`): the `DELETE /api/library/books/:book_id/downloads/:history_id` handler looks up the row's `task_id`, finds all sibling file rows sharing it, and deletes `user_downloads` links for all of them for the requesting user (release-atomic). Per-file unlink stays impossible.
9. **`CONTEXT.md`**: File section is already updated (per #13's resolution). Verify no drift.
10. **Tests**: cover multi-file finalize (N=3 file rows + N `user_downloads` links inserted), retry-while-partial (multi-file rows from crashed attempt deleted before sentinel insert), per-file `task_id` present in `files[]` API payload (multiple entries share `task_id`), release-atomic unlink fan-out (one `:history_id` deletes N links), mid-flight unlink returns 404 (no link row yet), sentinel shape at queue time (per-file cols NULL), legacy single-file rows still work (one-member release group).
11. **#08 revision (post-implementation)**: update `library/08-book-detail-prototype` against the new flat `files[] + task_id` shape. The frontend groups by `task_id` for display. Out of #14's scope unless #08 is still claimed by the same dev — hand off to #08 otherwise.

## Out of scope (per #13)

- Per-file unlink within a release (releases unlinked atomically).
- Destination-dir scanning to backfill missing files of legacy grabs.
- Migration of legacy rows beyond dropping UNIQUE — legacy rows keep their existing single-file shape trivially.
- A "Grab" vocabulary term (#13 chose "release" everywhere).
- `grabs[]` server-side API grouping (#13 chose flat `files[]` + `task_id`).

## Definition of done

- `make python-checks` green; new tests pass; existing library API tests still pass (the `files[]` shape gains a field, doesn't lose any).
- `_serialize_book_detail` payload includes `task_id` per entry; a multi-file grab produces N entries sharing the same `task_id`.
- Unlinking a release with N files deletes all N `user_downloads` links for the user.
- Mid-flight unlink returns 404.
- Map's Decisions-so-far gets a #14 context pointer on close; unblocks #08 (blocked by 13), #11 (blocked by 13).

## Resolution

Implemented #13's contract in full on branch `feature/library-multi-file-release` (commit `5fcd684`). `make python-checks` green (ruff lint + format, basedpyright 0 errors, vulture); 1952 unit tests pass (16 new). Tracker state (#13 resolution, #14 opening, CONTEXT.md File section, git-tracking standing preference) landed on `main` directly per the new tracking strategy before the code commit.

### What landed

- **Schema (1):** `_CREATE_TABLES_SQL` drops `UNIQUE` on `download_history.task_id`; new `idx_download_history_task_id` (non-unique) for fresh DBs. `_migrate_download_history_task_id_nonunique` rebuilds the table (copy-to-temp / drop / recreate-without-UNIQUE / copy-back) for legacy installs, preserving rows + `book_id` and recreating all four indexes. Idempotent on re-init.
- **Transfer return types (2):** `transfer_file_to_library` returns `list[Path] | None` (one entry); `transfer_directory_to_library` returns the full `transferred_paths` list. `transfer_book_files` unchanged (already `list[Path]`). All 10 test-only callers in `test_hardlink.py` updated.
- **Task carrier (3):** `DownloadTask.library_paths: list[str]` added; `download_path` stays equal to `library_paths[0]` for legacy readers.
- **Multi-file finalize (4):** `finalize_download_files(task_id, file_rows)` — captures the queue-time sentinel's immutable columns, deletes it (and any crashed-attempt partial rows), inserts N terminal file rows sharing `task_id` (each with `format`/`size`/`download_path`), and inserts N `user_downloads` links for the triggering user (`INSERT OR IGNORE`). `finalize_download` (legacy single-path) delegates with a one-element list. **No-file-row finalizes** (error/cancelled with no transferred path) UPDATE the sentinel in place rather than deleting it — preserves the activity/retry-by-`task_id` lookup contract that a naive delete would have broken (caught by `test_activity_routes_api` + `test_download_api_guardrails`).
- **Retry path (5):** `record_download` sentinel INSERT writes per-file cols NULL; retry is explicit `DELETE WHERE task_id=?` + sentinel `INSERT`, atomic under the existing `self._lock` + `commit()`. The legacy `ON CONFLICT(task_id) DO UPDATE` is gone (INVALID under non-unique `task_id`).
- **Terminal hook (6):** `_build_download_file_rows` in `main.py` reads `task.library_paths`, derives `format` (from extension) + `size` (`Path.stat().st_size`) per file. `_record_download_terminal_snapshot` calls `finalize_download_files` with the list. `folder.process_folder_output` sets `task.library_paths` from `transfer_book_files`' `final_paths`; `orchestrator._download_task` defaults it to `[result]` for single-path output handlers (email/booklore).
- **API (7):** `_serialize_book_detail` adds `task_id` to every `files[]` and `in_flight[]` entry. `get_files_on_disk` / `get_in_flight_files` already `SELECT task_id` — no query change.
- **Unlink (8):** `unlink_download_from_user` fans out across sibling file rows sharing the row's `task_id`, deleting `user_downloads` links for all of them for the requesting user (release-atomic per (4-a-strict)). Mid-flight unlink (no link yet) returns `False` → route surfaces `200 'unlinked'` idempotently, matching (4-mid-1-ii). Per-file unlink within a release stays impossible.
- **CONTEXT.md (9):** File / Download section already updated on `main` per #13's resolution; verified no drift.

### Tests (10)

16 new cases: sentinel-per-file-cols-NULL, multi-file finalize (N=3 + N links), retry-while-partial (stray rows cleared before sentinel insert), legacy single-path delegate, no-file-row error finalize (sentinel preserved in place), legacy single-file well-formed group, `task_id` per entry in `files[]` payload, release-atomic unlink fan-out from any file's `history_id`, mid-flight unlink no-op, unknown `history_id` no-op, plus the `test_hardlink.py` return-type updates.

### Notes / follow-ups

- **`download_history.book_id` is never populated by production code today** — neither `record_download` nor `finalize_download_files` sets it. `library_service.get_files_on_disk` filters `WHERE book_id = ?` and currently finds nothing because `book_id` is always NULL. This is **not #14's contract** (it's part of #11's search-integration / the #02 add-to-library flow wiring the request's book to the download). Flagged on the map for the ticket that owns it; not a regression introduced here — the column was already unused before #14.
- **#08 revision (step 11)**: `library/08-book-detail-prototype` needs updating against the new flat `files[] + task_id` shape (frontend groups by `task_id` for display). Out of #14's scope — handed off to #08 (still claimed on its branch).
- **Git tracking strategy**: recorded on the map's Notes — `.scratch/library/` lands on `main` directly, always, separate from code branches. Applied here: tracker edits committed to `main` first, then code on `feature/library-multi-file-release`.

Unblocks #08 (blocked-by 13 → resolved) and #11 (blocked-by 13 → resolved).
