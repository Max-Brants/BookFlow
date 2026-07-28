# Library file visibility is a per-user-per-release link table

**Status:** accepted

Library membership (per #01 / ADR 0001) is Book-level — `user_library(user_id, book_id)` says "this user may read this available Book". It is only valid if the Book has an imported File. Files (`download_history` rows) are global per-instance — a downloaded file is shared, not copied per user. The question this ADR answers: how does the library decide which imported files a user sees, and which files they have unlinked?

We add a separate `user_downloads(user_id, history_id)` link table as the per-user-per-release link. A user's book-detail query JOINs `download_history` to `user_downloads` for that user; multiple users can link the same `download_history` row (a shared Request fulfilment links it to every requester, or any user explicitly grabs a competing release). Unlinking a release is `DELETE FROM user_downloads WHERE user_id=? AND history_id=?` — hard delete of the link; the file on disk and the `download_history` row are untouched. Files with zero `user_downloads` entries and not in-flight are Orphans (admin cleanup, deferred).

## Rejected alternatives

1. **Hidden-files mask table** (a `user_library_hidden_files` table that records "this user has hidden this release"). Tombstone-through-the-back-door — a parallel table whose only job is to subtract from another query. Doubles JOIN cost on every book-detail read, and re-introduces soft-delete through the back door after #01 explicitly said "no `removed_at`, no tombstone".

2. **Promote `user_library` to include `download_history_id`** (a link table per user per Book per file). Would break ADR 0001's Book-level membership invariant — `user_library` would no longer mean "this user may read this Book", it would mean "this user tracks this Book at this file". The entitlement table already provides file-level visibility without changing the membership meaning.

3. **Per-user file storage on disk** (each user has their own downloads; no shared pool). Multiplies disk usage N× for N users — and the qbittorrent/usenet dedup (`base_handler.py:758-828`, `find_existing`) doesn't save you, because `_handle_completed_file` still copies the file into each user's `DESTINATION`. Also breaks #02's in-flight race-prevention, conflicts with `CONTEXT.md`'s "Files are global per-instance" invariant, and would require a fresh settings/permissions/storage layer that doesn't exist today.

4. **Gate on `download_history.user_id`** (the existing "triggering user" column). Treats Files as per-user-property rather than per-instance-property. Doesn't allow admin downloads on behalf of users. Forces a fresh download per user even for books already on disk.

## Consequences

- `user_library` stays Book-level per ADR 0001. A fileless Book cannot be added to a Library; it is acquired through a Request. Adding an already available Book creates membership and entitlements atomically. Importing a File for an approved Request creates both for every approved requester.
- `download_history.user_id` becomes an audit field for "the auth identity who triggered the download"; the load-bearing column for library file visibility is `user_downloads.user_id`. The triggering user is not surfaced via the library API (no per-user attribution leak).
- File serving gates on **both Library membership and a `user_downloads` entitlement**, not on `download_history.user_id`. The bytes remain shared, while availability is explicitly granted per user. In-flight task bytes are never library-visible.
- Multiple users can link the same `download_history` row — the per-user-per-Book file lists diverge based on each user's `user_downloads` rows. A file another user has unlinked from their library is still visible to me if I have it linked.
- Re-add of an unlinked release is `INSERT OR IGNORE INTO user_downloads(user_id, history_id)` — instant when the file is still on disk and the `download_history` row is intact.
- Orphan files (zero `user_downloads` entries, not in-flight) are admin-cleanup candidates. Mechanism deferred — parked on the map's Not yet specified.
- The model preserves the Library-as-membership abstraction and the File-as-shared-resource abstraction exactly. The link table is the clean join between them.
