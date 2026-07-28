Type: grilling
Status: resolved
Blocked by: 01

# Settle the "add to library" flow and the files-exist branch

## Question

The grilling session established that **add-to-library is the spine of the experience**: a user can only trigger downloads for books in their library. The exact click flow needs to be pinned down so downstream tickets (UI, API) can build against it.

Flow sketch from the session:

1. User searches (universal mode) → sees bookflow's current search-results UI.
2. User clicks **Add to library** on a single result (a metadata-provider book).
3. Two branches:
   - **No files on disk globally** → user is routed to the existing release-list page for that book (list of indexers/sources offering it). User picks a release to download as today.
   - **Files already on disk globally** → user is routed directly to the new **book detail page** (`/library/:bookId`). No re-search.

Open questions this ticket must resolve:

- **Where does the "Add to library" button live?** Settled in the grilling session as "in the work detail modal" (`DetailsModal`, `src/frontend/src/components/DetailsModal.tsx`, opened by `handleShowDetails` in `App.tsx:943`). Confirm the button is a new entry in that modal, not a new control on the search results list itself.
- **"No files on disk globally" check — what does "globally" mean, and how is it computed?** Likely: a row exists in `download_history` linked (by the model in #01) to a book row with the same `(provider, provider_book_id)` AND `final_status = 'complete'` AND the file path still exists. Decide the exact predicate.
- **Race condition:** user A clicks Add, no files on disk → routed to release-list → user A starts downloading. Meanwhile user B clicks Add for the same book. What does user B see — release-list (they might pick a competing release and round-trip a duplicate file) or book-detail (no files yet, just user A's in-flight download)? Decide the rule: do in-flight `download_history` rows count as "files on disk" for this branch?
- **If the book entity doesn't exist yet** (no one has ever added it) — does the Add click create the book row, the library link, then route? Or does it route first and only persist if the user actually downloads something? Affects UX of "added but then user closed the tab without downloading".
- **Routing mechanism.** Where does the user land when they click Add:
  - No-files branch: existing release-list view (the current bookflow search-results page filtered to one book?) or a new URL like `/library/:bookId/find`? Settling this matters because it shapes frontend routing (see #07).
  - Files-exist branch: new book detail page at `/library/:bookId`.

The output of this ticket is a written UX contract: every later UI ticket can code against it. No code changes here.

## Outcome of this ticket

A documented click-flow contract — entries, branches, predicates, route targets — that #04 (Add-to-library backend), #06 (bookshelf), #07 (frontend routing), #08 (book detail page), and #09 (release-list dedup indicator) all depend on.

## Answer

Resolved 2026-07-20 by grilling session. The contract substantially simplifies and re-shapes the original two-branch routing sketch: **Add always navigates to `/library/:bookId`**; there is no separate release-list route, and the book-detail page is the destination in both files-exist and no-files cases. Each sub-decision recorded with rationale.

### Sub-decisions

1. **Add button is a repurpose, not a new sibling.** The existing green `Get` / `+` affordance — on the search-results card and in `DetailsModal` footer (Universal-mode metadata books only) — is renamed to **Add to Library** (`Add +`). Direct-mode (`SEARCH_MODE=direct`) results are untouched and have no Add button. Grounded at `DetailsModal.tsx:404-422` (the footer action button) and `App.tsx:1512` (`handleGetReleases` is the existing Universal-mode "find downloads" path that Add now supersedes as the entry point).

2. **Already-in-library state.** When the user opens `DetailsModal` for a book already in their library, the button becomes **"In Library"**, disabled-as-add (re-adding is impossible — backend is idempotent). Clicking the disabled button navigates to `/library/:bookId` — Sonarr/Radarr-style "I forgot if I already grabbed this" jump-to-existing. Whether the search-results card itself surfaces the same in-library affordance as a button or just a badge is an implementation detail delegated to #11 (search integration), not decided here. On the card, the contract is "Add becomes navigate-to-book when already in library"; the exact control shape is #11's call.

3. **Add click flow — create-then-route (Option A).** Click → brief loading state → backend: metadata fetch (the existing `getMetadataBookInfo` shape hitting `/api/metadata/book/<provider>/<book_id>` at `services/api.ts:475-481`) → upsert `books` row → insert `user_library` link → compute `files_exist_globally` + `in_flight_globally` via the predicate in sub-decision 6 → return `{book_id, files_exist_globally, in_flight_globally}` → frontend navigates to `/library/:bookId`. The book row and the library link persist regardless of whether the user then closes the tab — **wishlist semantics**, per #01's invariant that "a Book can be in a user's library with zero files anywhere".

4. **Destination is always `/library/:bookId`.** No separate release-list route. **There is no `/library/:bookId/find` route** — this overrides #07's likely-route list. The book-detail page is the single destination in both files-exist and no-files cases. Direct-mode releases (no `books` row) cannot be Add-ed and keep their existing direct-download UX.

5. **Auto-open Find Releases modal on navigation — env-gated.** When the user lands on book detail after Add:
   - `files_exist_globally == false` → the existing `ReleaseModal` auto-opens (via the `setReleaseBook(book)` pattern at `App.tsx:1608-1631`), gated by env var **`LIBRARY_AUTO_FIND_RELEASES`** (default `true`). Admin/instance can disable.
   - `files_exist_globally == true` → the ReleaseModal **never** auto-opens. We do not re-route to search. The user sees book detail with their existing formats listed (per #08).
   The Find Releases action *on the book detail page* is a modal (re-uses `ReleaseModal`), not a routed view. Re-picking a release when files already exist: **behaviour is fog — explicitly not resolved here.** Resurfaces when #08 (book detail UI) is worked; parked on the map under "Removing files / re-fetching a release".

6. **"Files on disk globally" — precise SQL predicate.**

   ```sql
   SELECT 1
   FROM download_history dh
   WHERE dh.book_id = :book_id
     AND dh.final_status IN ('active', 'complete')
     AND (dh.final_status = 'active' OR dh.download_path IS NOT NULL)
   LIMIT 1
   ```

   - **In-flight counts as "files exist" (Q3.1 → A).** `final_status = 'active'` rows count. Prevents the duplicate-release race: when user A's download is mid-flight, user B's Add-to-book-detail does not auto-open the Find Releases modal — B sees the in-flight indicator (per #08) instead.
   - **Trust `download_path IS NOT NULL`, defer filesystem stat (Q3.2 → i).** The predicate does not verify `Path(download_path).exists()` on every check; filesystem verification is deferred to the download-serve path (existing `_resolve_existing_download_path` at `download_history_service.py:126-130` already stats when serving). Stale-path rows may produce a "files exist" flag without a servable file — user clicks download, gets 404, re-runs Find Releases. Edge case, acceptable. File-existence tracking and release/file removal is parked as fog ("Removing files / re-fetching a release").
   - **Backed by `idx_download_history_book_id`** on `(book_id, final_status)` from #01 — covers this predicate.
   - `error` / `cancelled` rows are excluded by the `final_status IN (...)` clause; they don't count as "files exist".

7. **Closing the auto-opened Find Releases modal without picking = stay on book detail (Q2.3 → A).** User lands on book-detail page with empty "no formats on disk yet" state. A persistent "Find Releases" button lives on the page (#08) — reusable to re-open the modal later. **Graduates** the "Library entry expiry / file-less wishlist cleanup" fog patch from the map: file-less library entries are first-class — bookshelf shows "Find this book" badge/button for them, book-detail empty-state shows the same.

8. **Race condition — moot under this contract.** Both users land on `/library/:bookId`. User B sees the in-flight indicator if user A's download is mid-flight; no special branching. The duplicate-release race is prevented structurally because in-flight counts as "files exist" (sub-decision 6), so user B's Find Releases modal does not auto-open.

### What this ticket does NOT decide (deferred to other tickets)

- Backend route shape, request/response, scoping → #04.
- Frontend routing infrastructure (react-router-dom, shared layout) → #07.
- Book-detail page UX (the "expanded ReleaseModal shell", buttons, empty states) → #08. #02's contract dictates what the page must host (Find Releases modal trigger, in-flight indicator, empty state with persistent Find button) but not the visual layout.
- "Use Existing" affordance on release-list rows → #09. #02 does not decide this.
- Whether the search-results card surfaces the same "In Library" affordance as `DetailsModal` (button vs badge) → #11.
- Behavior of "Find Releases" when files already exist (re-pick competing release, replace, etc.) → fog, resurfaces at #08.

### Knock-on effects on other tickets (to be applied when those tickets are worked)

- **#07 (Frontend routing)**: drop `/library/:bookId/find` from the likely-route list. Routing is `/library` + `/library/:bookId` only (+ `/authors/:authorId` from #12). Find Releases is a modal, not a route.
- **#08 (Book detail page UI)**: scope restated — book detail is an "expanded `ReleaseModal`-style shell" that hosts the Find Releases modal (auto-opened per #02 sub-decision 5). "Find another release" is a button that opens the existing `ReleaseModal`, not a route navigation. Page must host: cover/title/author, formats-on-disk rows (when files exist), in-flight indicator (when an active download exists), empty state when no files exist (with persistent Find Releases button), Send-to-Kindle (per #05).
- **#09 (Release-list dedup indicator)**: still owns the per-release "On disk" tick/badge. The "Use Existing" affordance decision is still #09's — #02's contract doesn't preclude it, just doesn't require it.
- **#10 (Bookshelf UI)**: file-less library entries get a "Find this book" affordance (graduated from fog).
- **#11 (Search integration)**: implements the Add button on the search-results card and `DetailsModal`. If the book is already in the user's library, the card's Add button becomes navigate-to-`/library/:bookId` (control shape — button vs badge — is #11's call).	Idempotent backend.

### Context assets

- `docs/adr/0001-books-as-denormalized-snapshot.md` — the snapshot invariant that makes create-then-route viable (book row is self-sufficient for reads; no provider re-fetch on the read path).
- `bookflow/core/download_history_service.py:23-24, 72-74, 126-130` — `final_status` value set + existing `_resolve_existing_download_path` filesystem stat precedent.
- `src/frontend/src/components/DetailsModal.tsx:404-422` — the footer action button that Add repurposes.
- `src/frontend/src/App.tsx:943` (`handleShowDetails`), `App.tsx:1512` (`handleGetReleases`), `App.tsx:1607-1615` (`getMetadataBookInfo` fetch + `setReleaseBook` modal-open pattern) — the existing code paths Add takes over.
- `src/frontend/src/services/api.ts:475-481` — existing `getMetadataBookInfo` helper hitting `/api/metadata/book/<provider>/<book_id>`; Add's backend (#04 / #06) invokes the server-side equivalent to cache the `books` row.

### Update from #04 (applied when #04 was resolved 2026-07-20)

- **Sub-decision 5 (auto-open Find Releases modal on navigation)** — unchanged. Still env-gated by `LIBRARY_AUTO_FIND_RELEASES` (default `true`); still only auto-opens when `files_exist_globally == false`. Files-exist branch never auto-opens.
- **Sub-decision 6 ("files on disk globally" predicate, in-flight counts)** — unchanged for auto-open purposes. The SQL predicate still returns a single boolean that drives Find Releases auto-open behavior.
- **Sub-decision 7 (closing the auto-opened modal without picking = stay on book detail)** — unchanged.
- **Sub-decision 8 (race condition moot)** — stays valid AND is now *deliberately* moot, not just guarded-against by the in-flight predicate. Any user can grab another release anytime; the manual Find Releases button on book-detail is ungated for all users (Q3 grab gate from #04's earlier grilling rounds is **repealed**).
- **Net effect**: the in-flight predicate gates *auto-open only*; the manual Find Releases button is always available to any user. Re-picking a release when files already exist is no longer fog — it is an allowed action that inserts a new `download_history` row (or `INSERT OR IGNORE` if the `task_id` already exists) plus a new `user_downloads(user_id, history_id)` link. Release-level metadata (indexer, protocol) is first-class on book-detail per #04 sub-decision 6.
- **Fog graduation**: the "Removing files / re-fetching a release" fog patch graduates partially — the "re-fetch another release" half is now resolved. The "admin-only file deletion on disk" half (Orphan cleanup) stays parked as a separate fog patch (admin cleanup mechanism deferred — see map's Not yet specified).
