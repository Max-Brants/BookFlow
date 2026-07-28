# Context

A glossary of the canonical terms in the BookFlow fork's library effort. Devoid of implementation detail — for schema, see the tickets under `.scratch/library/`; for decisions, see `docs/adr/`.

## Book

A **Book** is a metadata-provider-backed work — an instance of "this work exists in provider X with provider id Y". A Book is **not** a release and **not** a file on disk; it is the catalog identity. The `(metadata_provider, provider_book_id)` pair is the natural key (both NOT NULL); the same work added via two providers lives as two Book rows (cross-provider merge is out of scope for the library effort).

A Book row is a **denormalized snapshot** of the provider's `BookMetadata` at add-time: title, author (primary), subtitle, publish_year, isbn_13, cover_url, series_name, series_position, language are copied into columns. The row is self-sufficient — reading book detail or the bookshelf never calls the provider. The complete raw provider payload is preserved in `metadata_json` for fields not promoted to columns (including the full ordered `authors` list). Staleness is accepted; refresh is a deferred explicit action, not a read-time behaviour. `books.updated_at` bumps on metadata refresh only — cover re-fetches (if they ever exist) don't touch it.

## Library

A user's **Library** is the set of available Book rows that user may read — a per-user link onto Books (`user_library`, PK `(user_id, book_id)`, both FKs `ON DELETE CASCADE`). A library entry is valid only when the Book has at least one imported File and the user has an entitlement to at least one such File. A fileless Book is never a library item or wishlist: it may only be requested. Removing a Book from a Library is a hard `DELETE` of the link row — no `removed_at`, no tombstone.

## Library Capability

A user's **Library Capability** is the administrator-assigned access level for the library workflow. A **download-capable user** may search releases and queue Downloads. A **request-only user** may add Books to their Library and submit book-level Requests, but cannot search or select releases. Admin status is a separate privilege that permits administrative operations and does not form a third Library Capability.

## Request

A **Request** is an authenticated user's explicit request for a fileless canonical Book. It belongs to the requester and Book and records the named release Profile selected by the requester. Admin requests are immediately approved; user requests require an admin's book-wide approval. Approval creates or joins one shared **request process** for the Book; its first approved request snapshots the active Profile. A Request remains active (`pending_approval` or `approved`) until at least one File is imported, then becomes `fulfilled`; rejected and cancelled requests are terminal history. Importing a File fulfils all approved requests for that Book and adds the Book, File entitlements, and durable Kobo-sync intent for every requester. A pending request may be cancelled without affecting the shared request process.

## Request Process and Release Profile

A **Request Process** is the single active, Book-scoped attempt to obtain a File for approved Requests. It uses an immutable snapshot of the first approved Request's named **Release Profile**, including hard filters and scoring settings. Automatic Search queries the allowed sources and selects only eligible candidates at or above the profile's minimum automatic score; negative scores are never eligible automatically. A failed release-specific attempt is blocklisted and the next eligible candidate is attempted. Interactive Search lets an admin run a fresh search and inspect every candidate, including rejected candidates and score reasons. An admin may force-select any result only through a confirmed, audited override; downstream file validation still applies.

## Notification

A **Notification** communicates a library event. Personal Notifications are sent to a User through one selected email or Apprise transport. Administrator Notifications are instance-level operational alerts sent through administrator-configured email or Apprise transports; they are separate from personal Notifications.

## File / Download

A **File** is a concrete imported downloaded artifact — one `download_history` row with its own `download_path`, `format`, and `size`. Files are global (per-instance, not per-user). A Book becomes visible in the Catalog only once it has at least one imported File. Adding an available Book to a Library creates membership and File entitlements atomically; importing a File for a requested Book does so for all approved requesters.

A single download activity (one qbittorrent/usenet job) may produce **multiple Files**. Files belonging to the same download activity **share a `task_id`** — together they form one **release** (the post-download artefact; distinct from a "release" in the search-results sense, which is a row the user picked from). `download_history.task_id` is therefore non-UNIQUE; the release is the derived `GROUP BY task_id` across file rows. At queue time, one `'active'` sentinel row per `task_id` (per-file columns NULL) stands in for the in-flight release; at finalize, the sentinel is deleted and replaced by N concrete file rows.

`download_history.book_id` (nullable, `ON DELETE SET NULL`) links a File to a Book. Legacy / direct-mode / un-lined rows have `book_id IS NULL` and are invisible to library queries. Backfill strategy for existing rows is deferred to the implementation ticket.

A user's library surfaces a File via the **`user_downloads(user_id, history_id)` entitlement link table**. Multiple users can be entitled to the same global File. Library reads require both `user_library` membership and an entitlement; file serving follows the same rule. Unlinking a release from a user's library hard-deletes the `user_downloads` links for every file row in that release (looked up by `task_id`); the File and `download_history` row are untouched. The `download_history.user_id` column remains an audit field for the identity that triggered the download, not a visibility grant.

`user_downloads` links are created at **import/finalize time** (when N file rows are concrete), not at queue time: one row per File for each requester in the shared request process or user who adds an already-available Book. An in-flight release has no entitlements yet; it cannot appear in a user's Library.

## Orphan

An **Orphan** is a `download_history` row (a File) with zero `user_downloads` entries across all users AND not currently in-flight (`final_status != 'active'`). Orphans are admin-cleanup candidates; the cleanup mechanism (schedule, retention window, what deletes — file only vs file + row) is deferred and parked on the map's Not yet specified.

## Author

The **primary author** is a denormalized `books.author TEXT` column (one string). The full ordered author list lives in `metadata_json.authors`. There is **no `authors` table** — author identity is provider-specific (Hardcover numeric ids, Open Library `/authors/OL*` keys, Google Books none), so an instance-local author table would buy a join without buying cross-provider identity. A future authors table is parked in fog for the author-browse ticket to revisit if it demands an instance-local author route.
