# Books are denormalized snapshots, not lazy provider references

**Status:** accepted

When a user adds a book to their library, the provider's `get_book` result is copied into `books` columns at add-time. The book row is then self-sufficient — book detail, bookshelf, and author browse never call the metadata provider on the read path. Staleness is accepted; no refresh mechanism is in scope for this effort (manual or scheduled) — the snapshot at add-time is final. A future effort may introduce Sonarr/Radarr-style scheduled refresh.

We rejected the alternative — a thin `books` row that re-fetches from the provider on every read — because (a) `download_history` already establishes a snapshot precedent in this codebase (`user_db.py:70-91`), (b) provider APIs rate-limit and go down, and an offline provider would break the library UX under the lazy-fetch model, (c) the #12 author-browse MVP reads a Hardcover bibliography live and cross-references `user_library` locally, which is one JOIN under snapshot but two live calls under lazy-fetch, and (d) the raw provider payload is preserved in `books.metadata_json` so future column promotions are pure schema migrations with no re-fetch.

## Consequences

- Cover/title/year can go stale; no refresh mechanism exists for this effort. Accepted for the library's scale.
- A provider that sunsets (or user deletes their account) doesn't lose book detail.
- Bookshelf rendering is fast (no provider calls); library reads at scale are bounded only by SQLite.
- The `(metadata_provider, provider_book_id)` natural key is a pure cache key, not a cross-provider identity — same work in two providers lives as two book rows. Cross-provider merge was ruled out of scope for this effort.
