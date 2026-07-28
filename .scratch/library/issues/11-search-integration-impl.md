Type: task
Status: resolved
Assignee: OpenCode (claimed 2026-07-23; resolved 2026-07-23)
Blocked by: 06, 09

# Search/Release-list integration: dedup indicator + add-to-library button

## Question

Manual execution ticket: implement the UX from #09 against the existing search-results UI, plus the Add-to-Library button per #02's contract. The architectural survey surfaces:

- The release-list UI lives in `src/frontend/src/components/resultsViews/` and is rendered from `src/frontend/src/components/ResultsSection.tsx`. The "work detail" modal is `src/frontend/src/components/DetailsModal.tsx`, opened by `handleShowDetails` in `src/frontend/src/App.tsx:943`.
- The backend search results come back from `/api/search` (or similar — #09 must cite it; `main.py:1028` and the search/metadata routes are the area).

Implementation scope:

- **Backend** — extend the search-results payload to include `is_on_disk: bool` per release, by joining against `download_history` on `(source, task_id)` per the dedup contract (#09). If #09 decided no per-row shape change (separate check), implement that instead.
- **Frontend — Add-to-Library button** (per #02 contract):
  - The existing green `Get`/`+` affordance on search-result cards and in `DetailsModal` footer (Universal-mode metadata books only) is renamed to **Add to Library** (`Add +`).
  - Click → POST `/api/library/books` → loading state (metadata fetch may take time) → navigate to `/library/:bookId` based on the response's `book_id`. The response's `files_exist_globally` flag is used by the *destination page* (#08) to decide whether to auto-open the Find Releases modal, not by this navigation step.
  - Already-in-library state: button shows **"In Library"**, disabled-as-add; clicking the disabled button navigates to `/library/:bookId` (Sonarr/Radarr-style jump-to-existing). Whether this is a button-keep-its-shape-vs-turns-into-a-badge on the search-results card is #11's call; on `DetailsModal` footer it stays a button. Backend must expose the already-in-library flag per search result to drive the frontend state without a per-row fetch.
  - Idempotent backend: re-Add is a no-op that still routes per #02 based on `book_id`.
- **Frontend — release-list dedup** — per-release tick / "On disk" badge in the release-list view; per-release "Use existing" affordance per the contract (#09 owns the "Use Existing" decision; #11 just implements).
- **Loading state** for the Add click — the click may take time (metadata fetch). Don't leave the user guessing; show loading, then route.

Verification: `make checks` passes; clicking "Add to Library" on a search result navigates to `/library/:bookId`; clicking "In Library" (already-in-library state) on a search result or in `DetailsModal` navigates to `/library/:bookId` without re-adding.

## Outcome of this ticket

Code on the feature branch. Closes the spine of the experience — after this lands, the user can do the central flow: search → add → download/view-book-detail.

## Update from #04 (applied when #04 was resolved 2026-07-20)

#04 settled the Add-to-library backend contract that #11 implements. Confirmed shape:

- **Add endpoint**: `POST /api/library/books` with body `{metadata_provider, provider_book_id}`.
- **Add response (idempotent)**: `{book_id, files_exist_globally, in_flight_globally, in_my_library: true}` — same payload whether the `user_library` link was newly inserted or already existed. No 409 for "already in library".
- **Failure**: 503 with `{"error": "Metadata provider unavailable"}` on provider down/rate-limited; no `books` row inserted (per #04 sub-decision 13, strict failure — the snapshot must be self-sufficient).
- **Already-in-library button state** driven by a separate `GET /api/library/books/:book_id` lookup, NOT by the Add response — because the button renders *before* the user clicks Add. The added lookup checks whether the `user_library` row for this user + Book already exists. If yes → button says "In Library" and navigates to `/library/:bookId` on click; if no → button says "Add +" and POSTs on click.
- **Download finalize → `user_downloads` insert**: when a user grabs a release (Universal mode, after Add), the existing `download_history` insert (via `_record_download_queued` at `main.py:1321-1349`) is supplemented by a `POST /api/library/books/:book_id/downloads/:history_id` call — or an equivalent server-side insert at finalize time — that creates the `user_downloads(user_id, history_id)` link. The exact wiring (frontend-driven call vs backend hook into `record_download`) is #11's implementation choice; the contract is that every download from a Library user also writes the `user_downloads` link so the file surfaces on book-detail for that user.

## Answer

Implemented on `feature/library-search-integration` at `cc82700` and `0d02a1f`, after merging #14's multi-file release implementation (`c027f5a`). Metadata search now batch-resolves provider-natural-key Book membership for `Add +` / `In Library` controls; release search batch-resolves `is_on_disk`, `book_id`, and `in_my_library` by derived `task_id`; ReleaseModal shows informational On disk badges. Universal search cards and DetailsModal provide Add + (with loading/error recovery), In Library navigation, and a separate Find Downloads action. Library-originated release payloads pass `library_book_id` through queue-time history and multi-file finalize, preserving `download_history.book_id` and its finalize-time `user_downloads` links. Added service/history coverage; focused 48-test backend suite, TypeScript, Ruff, basedpyright, and hook formatting pass. `make checks` remains blocked only by five pre-existing Oxlint no-unnecessary-type-assertion errors in `useUsersFetch.ts` and `SelfSettingsModal.tsx`. Merged via [PR #3](https://github.com/muneebabbas/bookflow/pull/3) as `be40ae7`.
