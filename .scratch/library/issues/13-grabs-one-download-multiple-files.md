Type: grilling
Status: resolved
Blocked by: 04

# Grabs: one download, multiple files

## Question

Resolve the schema + API contract + canonical vocabulary for a **grab** — a single download activity that produces multiple files on disk — and a forward path to model it correctly across `download_history`, `download_history_service`, the #04 library API, the #06 routes, the seed/test fixture, and the `transfer_book_files` caller that today silently discards every file but the first.

## Origin (fact-finding from reviewer feedback on #08)

**Reviewer intuition was correct.** A single torrent download produces multiple matched book files (often EPUB + MOBI + PDF from one grab). Reviewer observed: "I have confirmed a single download imported three files and the torrent also contained those three files." The current #04/#06 contract and #01's `CONTEXT.md` schema both model `download_history` as **one row = one file = one format** — factually too narrow.

### What the code actually does

- `bookflow/download/postprocess/transfer.py:161 transfer_book_files(book_files: list[Path], ...)` transfers **all** matched book files into the destination dir. The list `final_paths[]` it builds contains every transferred file (`transfer.py:179-267`).
- The caller of `transfer_book_files` (in the same module's `process_*_files` flow, `transfer.py:416-451`) iterates `len(source_files) > 1`, hardlinking/copying/moving each one to its final destination, building `transferred_paths: list[Path]`.
- `bookflow/download/postprocess/transfer.py:478`: returns `str(transferred_paths[0])` — **discards every file but the first.** `transfer.py:371` does the same for the simpler case.
- `bookflow/main.py:1435-1454 _record_download_terminal_snapshot` calls `download_history_service.finalize_download(task_id, final_status, status_message, download_path=task.download_path, retry_payload=...)` — that one path is persisted to `download_history.download_path`. `download_history.format` was set at queue time from `task.format` (singular) — also collapses to one format for a multi-format grab.

### What the schema today stores

`download_history` (`bookflow/core/user_db.py:70-91`):

- `task_id TEXT UNIQUE NOT NULL` — the grab's identity (one per download activity).
- `format TEXT` — singular format; intended by #01 to be the file's format.
- `size TEXT` — singular size.
- `download_path TEXT` — singular path.
- `book_id INTEGER` (added by #03's migration) — FK to `books.id`.
- `final_status TEXT NOT NULL` — `'active'` for in-flight, `'complete'` for terminal.

There's **no concept of multiple files per grab** anywhere in the schema. `library_service.get_files_on_disk` (`library_service.py:285`) `SELECT`s one row → one `<file>` entry in `_serialize_book_detail`'s `files[]` array (`library_routes.py:192-203`). The #04 contract that the #08 prototype modelled correctly against is **factually lossy versus reality**.

## Open questions this ticket must resolve

Open under five headings — schema, finalize-time persistence, API contract, unlink semantics, vocabulary. The grilling session works each in dependency order (schema is upstream of everything).

1. **Schema shape — child table or repurpose `task_id`?**
   - **(a) New `download_history_files` child table** keyed by `download_history.id` (FK `ON DELETE CASCADE`): columns `id, history_id, format, size, path, transferred_op, indexed_at`. One row per file. `download_history.format`/`size`/`download_path` become **summary** columns (first file's format; aggregate size; first file's path — preserves the current API surface for any consumer reading the flat row directly). Bonus: `format` becomes "primary format" rather than singular, and the formats-union across a book's `download_history` rows stays derivable from the child table.
   - **(b) Re-purpose `download_history` to one-row-per-file** with a new `grab_id` grouping column (the old `task_id` becomes `grab_id`; one grab spans multiple rows sharing the same `grab_id`). Touches every caller of `download_history` (activity sidebar, history views, retry-backfill, etc. — far heavier than (a)).
   - **(c) Keep schema flat, accept the loss** — officially cap the system at one file per grab. Means the pipeline silently drops N-1 files from `download_history`, and Find Downloads dedup by `(source, task_id)` is the only surviving concept. Reviewer explicitly disagreed with this option when raising the feedback.

2. **Finalize-time write path — where the child rows get persisted.**
   The natural seam: `transfer_book_files` returns `final_paths[]` (already does — `transfer.py:171,237,270,302`). The bug is the caller at `transfer.py:478` returning `transferred_paths[0]`. The pipeline needs to surface *all* `transferred_paths` up to whoever calls `finalize_download` so a new `record_download_files(history_id, paths[])` call can insert the child rows. Is the seam at `transfer.py:478` (let `process_*_files` return `list[Path]` instead of `str`), or at `_record_download_terminal_snapshot` (extend the snapshot to carry a list)? #13 decides the shape.

3. **API contract — `_serialize_book_detail` shape.**
   Today (#04): `files[]` is one entry per `download_history` row, with `{history_id, format, size, indexer_display_name, protocol, downloaded_at, downloadable_by_me}`. Resolution (a) above reshapes to: `files[]` becomes `grabs[]` (reviewer's preferred term), one entry per `download_history` row with the summary fields plus a nested `files: [{format, size, path, downloaded_at, downloadable_by_me}]` array per row. `downloadable_by_me` per-file (because `user_downloads` owns grabs, not individual files — sub-decision linked below). `in_flight[]` follows the same re-shape.

4. **Unlink semantics — at the grab level.**
   - Reviewer's stated intention: "unlink an entire release (= grab)." Unlink at the grab level means `DELETE /api/library/books/:book_id/downloads/:history_id` (existing #04 route, unchanged endpoint shape) deletes the `user_downloads` link row — same as today — but now the *visual* meaning is "remove the whole grab from my library." The underlying `download_history` row + its `download_history_files` children stay untouched (per #04 sub-decision 7: "file/`download_history` row untouched"). The files stay on disk globally; other users still see the grab if they've linked it.
   - **Per-file unlink mid-flight:** the #08-decided-rule was "disallow with error when `final_status='active'`." Under the new grab-shape, what if the grab is multi-file and one file in it is mid-transfer? Today the whole `download_history` row's `final_status` flips to `'complete'` only after the pipeline finishes transferring all files; mid-flight means the row's `final_status='active'`. So "unlink mid-flight" = the whole grab is mid-flight = the row-level rule still holds. **#13 reaffirms the rule applies at the row level** (it always did, but explicitly noting it for the new grab shape).
   - **No per-file unlink:** the contract does **not** expose unlink of individual files within a grab — `user_downloads` owns grabs, not files. If a user wants to keep one file of a grab and not another, that's out of scope for this effort (would require a separate per-file link table).

5. **Canonical vocabulary — "grab" vs "release."**
   Reviewer proposed "grab" because "release" overlaps with the upstream indexer's vocabulary (`release` is one row in the search results; one search result can map to one grab). The map body and CONTEXT.md say "release" throughout (#02 "Find Releases," #04 sub-decision 1 "release-level metadata," #09 "release-list dedup," #11 "release-list integration"). Decide:
   - **(a)** Adopt `grab` as canonical for the *post-download artefact* (one `download_history` row + its child files). Keep `release` for the *upstream search/indexer row* (the search-result rows the user picks from). Two distinct terms, precise.
   - **(b)** Keep `release` everywhere (overloaded term).
   - **(c)** Adopt `grab` everywhere; rename `Find Releases` to `Find Grabs` on the search side (touches more surface).

## Out of scope (must rule out)

- **Per-file unlink within a grab.** Grabs are unlinked atomically. Out of scope for this effort; surfaces only if a reviewer explicitly asks for per-file ownership.
- **Migration of legacy download_history rows.** Existing rows that pre-date #13 carry only the primary file's path + format. The migration adds the `download_history_files` child row from the existing `download_path` + `format` — that's the floor; the other N-1 files of legacy grabs are *truly lost* (the destination dir may or may not still hold them; scanning is out of scope).
- **Retroactive scanning of destination dirs to backfill missing child files.** Out of scope — lands as a fresh effort if a reviewer asks for it later. The map updates its Out-of-scope section to record this ruling once #13 resolves.

## What #13 produces

A **contract decision** (this is a grilling ticket, not an implementation ticket) that resolves all five headings above, plus a context pointer back to the map. It does *not* write the migration or the implementation — those land as the *outcome* of #13's decision, owned either by #03-extend (a fresh implementation ticket) or by the existing #11 (which already touches download-finalize → user_downloads wiring). #13's resolution explicitly nominates which ticket picks up the implementation.

## Linked artifacts

- `bookflow/download/postprocess/transfer.py:161,302,478` — the source of truth for "one grab, multiple files"
- `bookflow/main.py:1376,1435` — the queue-time + terminal-time history writers
- `bookflow/core/download_history_service.py:344` — `finalize_download` writes one path
- `bookflow/core/library_service.py:285` — `get_files_on_disk` reads from one history row
- `bookflow/core/library_routes.py:170` — `_serialize_book_detail` shape (the contract #13 reshapes)
- `bookflow/core/user_db.py:70-91` — the `download_history` schema (one row = one file today)
- `.scratch/library/issues/08-book-detail-page-ui.md` (reopened) — the prototype that surfaced this gap; #13 unblocks #08's revision
- `CONTEXT.md` (File / Download section — updated to reflect schema (b): one row = one file, files sharing a `task_id` belong to the same release)

## Answer

Resolved via a `/grilling` + `/domain-modeling` session working the five headings in dependency order. Each heading's decision is recorded with its rationale; the implementation lands in a fresh ticket **#14** (nominated below), not #11.

### Terminology note (Heading 5 override)

The ticket body uses "grab" throughout. The grilling session's Heading 5 resolution overrode that: **"release" stays the canonical term for both the upstream search-result row and the post-download artefact** (option 5-b). No "grab" term is introduced into `CONTEXT.md`, the API, or the UI. The implementation should use "release" in code, comments, and copy. Where the Answer below says "release (the post-download artefact)," it means the set of `download_history` file rows sharing a `task_id`. The term is overloaded against the search-result sense of "release"; sentences must disambiguate by context.

### 1. Schema shape — (b) one row = one file, no child table

`download_history` is repurposed to **one row = one file**. Files belonging to the same download activity (one qbittorrent/usenet job) share the same `task_id`. No `download_history_files` child table; no new columns. `format`, `size`, `download_path` stay on the row and are now correctly per-file.

- **1b. Group key — (b-i).** The existing `task_id` value doubles as the release group key (the queue already produces one `task_id` per download activity by construction). Drop the `UNIQUE` constraint on `download_history.task_id`. sqlite cannot drop a UNIQUE constraint in place; the migration rebuilds the table via #03's conditional `PRAGMA table_info` / `PRAGMA index_info` migration idiom (copy rows to a temp table, drop+recreate without UNIQUE, copy back). Legacy single-file grabs trivially form well-formed one-member groups — no backfill work.
- **1c. Column name.** Keep the column name `task_id` (do not rename to `grab_id`). `task_id` already means "the queue's per-download task handle" = the release group key. Renaming would touch `DownloadTask.task_id`, the queue terminal-hook contract, and `record_download`/`get_by_task_id` for no behavioural change.
- Rejected (a) child table: redundant under (b) since the file row is the stored entity. Rejected (c) cap-at-one-file by reviewer feedback. Rejected (d) flat-with-summary-only: dishonest (knows of N-1 files but refuses to model them).

### 2. Finalize-time write path — (2-a) sentinel + multi-row finalize

- **Queue time:** `record_download` (`download_history_service.py:260`) keeps inserting one `'active'` row per `task_id`, but writes the per-file columns (`format`, `size`, `download_path`) as `NULL` — a release-in-flight sentinel.
- **Transfer seam:** `transfer_file_to_library` (`transfer.py:371`) and `transfer_directory_to_library` (`transfer.py:478`) currently return `str(final_path)` / `str(transferred_paths[0])`, discarding every file but the first. Both are changed to return `list[Path]` (the full `final_paths` / `transferred_paths` list — already built at `transfer.py:179,237,270,412`). `transfer_book_files` (`transfer.py:161-270`) already returns `list[Path]` and is unchanged.
- **Carrier:** new `task.library_paths: list[str]` on the task object carries the final paths up to the terminal hook. `task.download_path` stays as `str(library_paths[0])` for any legacy consumer reading the single-path field.
- **Finalize:** `_record_download_terminal_snapshot` (`main.py:1435`) reads `task.library_paths` (a list) instead of `task.download_path` (a single string) and calls a new `download_history_service.finalize_download_files(task_id, file_rows)` that **deletes the sentinel row + inserts N file rows** (one per path), each with its own `format`/`size`/`download_path`/`final_status`/`terminal_at`. The existing single-path `finalize_download` is kept as a thin delegate that calls `finalize_download_files` with a one-element list — preserves the call signature for any non-library caller (direct-mode downloads still finalize through it).
- **2b. Retry path — (2-retry-i).** `record_download`'s `ON CONFLICT(task_id) DO UPDATE SET final_status='active'` (`download_history_service.py:313-318`) relied on `task_id` UNIQUE, which no longer holds post-(b). Retry now: inside `record_download`'s existing `with self._lock` transaction, **`DELETE FROM download_history WHERE task_id=?`** (clears any partial multi-file rows from a crashed previous attempt) **+ `INSERT` the sentinel** (per-file cols NULL). Atomic (same lock + `conn.commit()`). Observable behaviour identical to today's `ON CONFLICT` on a clean retry; safe under non-unique `task_id`.

### 3. API contract — (3-a) flat `files[]` + `task_id` per entry

`_serialize_book_detail` (`library_routes.py:170-212`): `files[]` stays **flat, one entry per `download_history` row** (= one entry per file under (b)). Add a `task_id` field to each entry — frontend (#08) groups by `task_id` for display. `in_flight[]` mirrors: flat, one entry per active row, with `task_id` added.

- No `grabs[]` server-side grouping (option 3-b rejected): the release is a derived `GROUP BY task_id`, not a stored entity; a server-derived `grabs[]` shape would imply release-level metadata that doesn't exist as a row.
- The API field name is `task_id` (column-faithful per 1c). The vocabulary term "release" is prose/UI; the column and API field are both `task_id`.
- `downloadable_by_me` stays per-file (it's `user_downloads`-derived, and `user_downloads` links at the `history_id` = file-row level under (b)).
- `get_files_on_disk` (`library_service.py:285`) and `get_in_flight_files` (`library_service.py:315`) unchanged in shape — they already return one row per `download_history` row, which under (b) is naturally one row per file. Index any new `WHERE task_id = ?` queries on `task_id` (a non-unique index, since UNIQUE is dropped).

### 4. Unlink semantics — (4-a-strict) per-file URL, release-atomic effect

`DELETE /api/library/books/:book_id/downloads/:history_id` (existing #04 route, unchanged URL): the `:history_id` identifies **any** file row of the release. The service looks up that row's `task_id`, finds all sibling file rows sharing it, and **deletes `user_downloads` links for all of them** for the requesting user. Per-file URL (backward-compat with #04's endpoint table); release-atomic ownership at the data level.

- Matches #02's "unlink the whole release" intent under (b)'s per-file storage.
- **Per-file unlink within a release** is ruled out of scope for this effort (`user_downloads` owns releases atomically). This closes the "Per-file unlink within a grab" fog patch.
- **4b. Link timing — (4-mid-1-ii).** `user_downloads` link rows are inserted **at finalize, not at queue time**. When `finalize_download_files` inserts N file rows, it also inserts N `user_downloads(user_id, history_id)` rows for the triggering user (`download_history.user_id`). The queue-time sentinel has **no** `user_downloads` link — the triggering user's ownership of an in-flight release is captured by `download_history.user_id` (audit) + `request_id` (library request), not by a link row.
- **Mid-flight unlink returns 404** (no link row exists to delete), preserving #08's "Unlink disabled while in-flight" UX via a different mechanism (no `user_downloads` row to delete, so the endpoint finds nothing). The #08-decided "409 Conflict" rule is superseded by "404 Not Found" under (b) — same UX outcome, different status code.
  - Rationale: linking the sentinel would force a link-migration at finalize (delete sentinel link + insert N file-row links) that adds failure surface (a crash between delete and insert loses ownership) for no gain. Deferred linking keeps the sentinel a pure transient placeholder.
- #04's "in-flight counts as files-exist" predicate for #02's Find Releases auto-open is a **display** predicate over `download_history.final_status`, not over `user_downloads` — unaffected by deferred linking. An in-flight release is visible in `in_flight[]` (per #04/#06) but not in `files[]` until finalize, which is already the case today.

### Migration note for legacy rows

Legacy `download_history` rows (one path + one format each) trivially become well-formed one-file releases under (b). The schema migration drops `task_id` UNIQUE; legacy rows keep their existing `task_id`/`format`/`size`/`download_path` unchanged. The "other N-1 files of legacy grabs are truly lost" caveat from the ticket's Out-of-scope section still applies — no destination-dir scanning.

### Implementation owner nomination

#13 is a contract decision only — **no migration or implementation code is written here.** The implementation lands in a fresh ticket **#14** (`release-multi-file-schema-and-finalize-impl`), NOT #11. Rationale: #11 is "search-integration-impl" (search-results → library dedup); it touches the search layer, not the download-finalize pipeline. The #13 implementation work is squarely in `user_db` (schema migration), `download/postprocess/transfer.py` (return-type changes), `download_history_service` (sentinel/finalize/retry), `main.py` (terminal hook), `library_routes` (`_serialize_book_detail` `task_id`), `library_service` (unlink fan-out), and `CONTEXT.md` — none of which is search. Folding into #11 would bloat a search ticket with finalize-pipeline surgery it shouldn't own.

**#14's scope, per this contract:**
1. Schema migration dropping `task_id` UNIQUE (#03's idiom) + add a non-unique index on `task_id`.
2. `transfer_file_to_library` / `transfer_directory_to_library` return `list[Path]`.
3. `task.library_paths: list[str]` on `DownloadTask` (+ keep `task.download_path` as `library_paths[0]` for legacy readers).
4. `download_history_service.finalize_download_files(task_id, file_rows)` — deletes sentinel, inserts N file rows + N `user_downloads` links for the triggering user; `finalize_download` delegates with a one-element list.
5. `record_download` retry path: `DELETE WHERE task_id=?` + sentinel `INSERT`.
6. `_serialize_book_detail`: add `task_id` to `files[]` and `in_flight[]` entries.
7. Unlink service: fan-out across sibling file rows sharing `task_id` for the requesting user.
8. Update `CONTEXT.md` File section: "A File is one `download_history` row; files sharing a `task_id` belong to the same release (one download activity may produce multiple files)."
9. New tests covering: multi-file finalize, retry-while-partial-multi-file, per-file `task_id` in API payload, release-atomic unlink fan-out, mid-flight-404 unlink, sentinel shape.
10. Post-resolution: remove `library/08-book-detail-prototype`'s assumption of one-file-per-release (revise the prototype against the new flat `files[] + task_id` shape — #08's revision).

### Fog patches cleared by this resolution

- **"One grab → multiple files"** (map Not-yet-specified) — graduated; resolved here as schema (b) + write path (2-a). Cleared from the map.
- **"Unlink mid-flight — held pending #13"** (map Not-yet-specified) — graduated; resolved here as (4-mid-1-ii): mid-flight unlink returns 404 (no `user_downloads` link exists). Cleared from the map.
- **"Per-file unlink within a grab"** (map Not-yet-specified) — graduated to Out-of-scope; ruled out via (4-a-strict) (releases unlinked atomically). Cleared from the map.

### Updates captured elsewhere

- `CONTEXT.md` File / Download section pending #14's implementation: the current text ("A File is a `(source, task_id)` pair with a `download_path` and a `format`") is updated now (see #14 step 8) to "A File is one `download_history` row; files sharing a `task_id` belong to the same release."
- `docs/adr/` — no new ADR. Schema (b) is not hard-to-reverse (a child table could be added later if per-file ownership is ever demanded), not surprising (the file row storing one file is the obvious shape), and the trade-off is small (drop UNIQUE). Skips the ADR bar.
