Type: grilling
Status: resolved
Blocked by: 01, 02, 04
Claimed by: wayfinder session 2026-07-23

# Release-list "files already on disk" indicator + add-to-library button on work detail

## Question

This ticket owns **the integration point between search and the library**: the existing release-list UI gets a *dedup indicator* (a tick / "On disk" badge) per release, plus a "Use existing" affordance; and the work-detail modal gets an **Add to library** button.

The grilling session gave the rough shape:

- For releases that already have files on disk globally — show a tick / "On disk" badge. Don't auto-redirect, don't block re-download. The user can still pick another release.
- Books already in the user's library — when the user clicks "Add to library" on a search result, the routing branches per #02.

Open questions this ticket must resolve:

- **What does "this release is on disk" check against?** The grilling session's dedup resolution was "(source, task_id) pair" — a `download_history` row exists with `final_status = 'complete'` for `(source, task_id)` matching the displayed release. The architectural survey confirms `download_history` keys on `task_id` (the source's release ID, e.g. AA MD5) per `bookflow/core/user_db.py:70-91`. Wire this check precisely.
- **Search endpoint extension.** The existing search-results endpoint returns releases. Does this ticket add an "already-on-disk" flag to each release's payload (join against `download_history` per release row), or does the frontend call a separate "is-on-disk" check per release (probably too chatty)? The former is the right answer via JOIN; decide where the JOIN lives (the search service vs the post-process layer).
- **Add-to-library button shape on the work detail modal** — placement, label, post-click behavior. Sits on the existing `DetailsModal`. Click triggers `POST /api/library/books` (#04); the response's `files_exist_globally` flag drives the route branch (#02). Settle the loading state UX (the click might trigger a metadata fetch).
- **"Use existing" affordance on the release row** — should it be there at all? The grilling session said tick+badge, no behaviour change; user can still pick another release. Does "Use existing" jump them to book detail (requires a book row to exist, which it might not — files-on-disk doesn't imply a `books` row). This is the crux of the question: a release being on disk doesn't mean a book entity has been created. Resolve the relationship; you can land at either "no Use Existing button — tick only" (simpler) or "Use Existing links to book detail when a books row exists for that release, otherwise disabled". Pick one and defend.

Output: written contract for the search results / release list / work-detail modal changes. Implementation lives in #12 (search integration).

## Outcome of this ticket

UX contract document. #12 implements against it.

## Grounded context (wayfinder session 2026-07-23)

Research on `main` @ `23bd49c`. #14's multi-file code lives on `feature/library-multi-file-release` (`5fcd684`), **unmerged to main** — flagged inline where it bites.

### The search pipeline (for Q1 + Q2)

- **Search route**: `GET /api/releases` at `bookflow/main.py:2849-3106` (handler `api_releases`). Envelope at `main.py:3078-3084`: `{releases, book, sources_searched, column_config, search_info}`. There is no separate search *service* module — the search runs inline in the route via `_search_source_releases` (`main.py:2884-2934`), which calls each plugin's `source.search(search_book, plan, ...)` (`release_sources/__init__.py:326-334`).
- **Per-release serializer**: `_serialize_release` at `main.py:1065-1080` — a thin `asdict(release)` over the `Release` dataclass (`release_sources/__init__.py:59-77`). The fields a release row carries today: `source`, `source_id`, `title`, `format`, `language`, `size`, `size_bytes`, `download_url`, `info_url`, `protocol`, `indexer`, `seeders`, `peers`, `content_type`, `extra`. **There is no `task_id` on a search result** — `task_id` is minted at *queue* time (`DownloadTask.task_id` at `models.py:91`, "e.g. AA MD5 hash, Prowlarr GUID"), typically derived from `source_id`/`download_url`.
- **No dedup against `download_history` exists today** anywhere in the search or queue path. `_search_source_releases` does none; `api_download_release` (`main.py:1083-1150`) queues blindly; `record_download`'s `ON CONFLICT(task_id)` (`download_history_service.py:313`) is retry re-arming, not skip-because-on-disk.
- **The qbittorrent/usenet `find_existing` dedup** (`download/clients/__init__.py:340-357`; call site `base_handler.py:761`) is **client-side**, keyed on `Release.download_url` (resolved to info_hash for torrents). It checks the external download client, not `download_history` or disk. Not reusable for #09's "is_on_disk".

### The dedup key (for Q1) — the #14 sequencing snag

- **On `main`**: `download_history.task_id TEXT UNIQUE NOT NULL` (`user_db.py:76`). `task_id` alone is the de-facto dedup key. `record_download` upserts `ON CONFLICT(task_id)`; `get_by_task_id` (`download_history_service.py:393`) keys on it. `(source, task_id)` is **not** a constraint anywhere on main.
- **On `feature/library-multi-file-release` (#14, unmerged)**: `task_id` UNIQUE is dropped (`task_id TEXT NOT NULL`), non-unique `idx_download_history_task_id` added, "release" = derived `GROUP BY task_id` group of file rows (per #13 decision + `CONTEXT.md` File section). A given release now has 1..N `download_history` rows sharing `task_id`.
- **Implication**: the dedup predicate for "this search release is on disk" must check for ≥1 `download_history` row with `final_status='complete'` AND `download_path IS NOT NULL` where `task_id` matches the release. On main, that's `∃ row WHERE task_id = ?`; on #14, it's `∃ row IN (rows WHERE task_id = ?)` — same predicate shape, but #11's implementation must group. The predicate itself (question 1) is stable across both; the *quantity* of joined rows differs and the frontend groups in #08. #09 owns the predicate; the sequencing (merge #14 first, or land #09/#11 against main then rebase) is a #11 impl concern surfaced here.

### The `book_id` gap (forces Q4's answer)

- `download_history.book_id` (added by #03's migration, `user_db.py:321-340`) is **never populated by production code** on main — neither `record_download` nor `finalize_download_files` sets it (flagged on map at `map.md:50`). `library_service.files_exist_globally(book_id)` (`library_service.py:335-350`) filters `WHERE book_id = ?` and today finds nothing.
- **This is load-bearing for Q4.** "Use existing → jump to book detail" requires a `books.id` to navigate to. A release on disk (a `download_history` row with `complete` + `download_path`) does **not** imply a `books` row exists — the `book_id` column is NULL. The only code that creates a `books` row is the Add-to-library flow (`POST /api/library/books`, #04/#06). So a release can be on disk *without* a book entity, and the "Use existing" affordance cannot link to `/library/:bookId` when no `books.id` exists for that release.
- Wiring `book_id` into `record_download`/`finalize_download_files` is owned by #11 (per `map.md:50`). #09 sets the contract that #11 implements — so a clean answer is: **"Use existing" is tick-only (no link action) for the MVP**; the link-to-book-detail behaviour is gated on whether a `books` row exists for that `task_id`, which #11 can surface as a per-release `book_id: number | null` field. Q4 decides which.

### Release-list frontend (for Q3 + Q4)

- **`ResultsSection.tsx:40-303`** orchestrates three views (`resultsViews/ListView.tsx`, `CompactView.tsx`, `CardView.tsx`). Each row gets a `Book` + a `ButtonStateInfo` (`types/index.ts:83-87`: `{text, state: ButtonState, progress?}`). `ButtonState` union (`index.ts:73-81`): `'download' | 'queued' | 'resolving' | 'locating' | 'downloading' | 'complete' | 'error' | 'blocked'`.
- **The Get/+ button dispatcher**: `BookActionButton.tsx:24-66` — branches on `searchMode === 'universal'` (from `useSearchMode()` / `SearchModeContext.tsx`), routing to `BookGetButton` (green `bg-emerald-600`, `BookGetButton.tsx:93-94`) in Universal mode or `BookDownloadButton` in direct mode. Click → `onGetReleases(book)` → opens ReleaseModal. **This is the existing seam** the Add-repurposes-Get decision (#02) plugs into.
- **Plausible insertion points for an "On disk" badge**: card footer at `CardView.tsx:246-260` / mobile row `CardView.tsx:232-243`; list action cell `ListView.tsx:290-339` (before the Details button at `:301`).
- **Plausible seam for "In Library" state** (per #02's Sonarr/Radarr-style disabled-button-navigates-to-`:bookId`): a new `ButtonState` value, or pre-check inside `getUniversalActionButtonState` (`App.tsx:1893-1919`) which already post-processes universal-mode button state for dismissed-task re-arming.

### DetailsModal (for Q3)

- `src/frontend/src/components/DetailsModal.tsx`, opened via `handleShowDetails` at `App.tsx:943-978` (fetches metadata for `isMetadataBook(book)` rows, else source record, then `setSelectedBook`).
- Footer at `DetailsModal.tsx:374-425`: source link (left), optional `BookTargetDropdown` (`:396-403`), and the action button (`:405-422`) which **already branches** on `isMetadata` — Universal mode calls `onFindDownloads?.(book)` (opens ReleaseModal); direct mode calls `handleDownload()` (queues). The button label in Universal mode is `'Find Downloads'` when state is `download`+text `'Get'`, else `buttonState.text` (`DetailsModal.tsx:88-91`).
- **Add-to-Library button insertion point**: the right-side flex container at `DetailsModal.tsx:395` — alongside the existing action button. Per #02, Add *repurposes* the existing green Get/+ button (Universal mode only) — so the modal footer's `isMetadata` branch (`:408-413`) is the existing seam. The question is whether Add-in-library state ("In Library", navigates to `/library/:bookId`) is a new `ButtonState` driving the same button, or a separate sibling button. Q3 decides.
- **Loading state**: the Add click triggers `POST /api/library/books` (#04), which does a synchronous metadata fetch (`_resolve_metadata_book_for_library`, #06) — can take noticeable time. The footer's button already has `disabled`+label-swapping infrastructure; the prototype's "loading" state (`BookDetailPage` first-pass) reused this pattern. Q3 settles the exact UX (spinner vs label-swap vs both).

## Resolution (wayfinder session 2026-07-23)

Grilling settled the contract one question at a time; each sub-decision below was picked deliberately from the options in the grounded-context section. Implementation lives in #11 (the ticket previously said #12 — corrected: #11 is the search-integration impl owner, #12 is author browse).

### Q1 — the "is this release on disk" predicate

A release shown in the search/release-list results is "on disk" iff ∃ ≥1 `download_history` row with `task_id` matching the release's would-be `task_id` (derived from `source_id`/`download_url` per the queue path's derivation), `final_status = 'complete'`, AND `download_path IS NOT NULL`.

- **No fs stat at search time** — defer to serve-time, consistent with #02's deferred-stat decision and #04's "trusts `download_path IS NOT NULL`" sub-decision for `files_exist_globally`. A stale row yields a 404 at serve-time; search stays fast.
- **Match key is `task_id` alone** — `(source, task_id)` is not a constraint anywhere on `main` and adds nothing; `task_id` is the canonical identifier `download_history` already keys on. The predicate shape is stable across #14's unmerged non-unique-`task_id` change (a release becomes a `GROUP BY task_id` group of file rows — the "∃ ≥1 row" predicate still holds; #11's impl groups if #14 has landed by then).
- **#11 owns extracting the `task_id` derivation into a shared pure function** both the queue path and the search dedup call pre-queue. The derivation is currently inline per-source (qBittorrent → info_hash from URL; AA → MD5; Prowlarr → GUID; per `DownloadTask.task_id` at `models.py:91`). The search result has no `task_id` until queue time, so #11 must surface the derivation for the search path to call.

### Q2 — per-release flag delivery (backend JOIN)

`api_releases` (`main.py:3053`, after `_serialize_release`) extends each serialized release row with:

- `is_on_disk: bool` — the Q1 predicate result for this release.
- `book_id: number | null` — the `books.id` for the release if one exists (the Q4 hook + the Q3b in-library source). Null when the release is on disk but no `books` row exists (the `book_id`-never-set gap — see #11 dependency below).
- `in_my_library: bool` — true iff a `user_library(user_id, book_id)` row exists for the current user + the `book_id` above (non-null `book_id` is a precondition; `in_my_library` is false when `book_id` is null).

Populated by a **single batched lookup** after serialization: one query `WHERE task_id IN (...)` against `download_history` (complete + path-not-null), then a follow-up for the `book_id`/`in_my_library` resolution if any rows matched. No N+1, no per-row fetch. The frontend gets everything it needs to render the tick (Q4) and the Add/In-Library button state (Q3) in one payload.

### Q3 — Add-to-Library button on `DetailsModal`

**Q3a — button shape (repurpose existing Universal-mode button):**

The existing footer action button (`DetailsModal.tsx:405-422`) is repurposed in Universal mode (`isMetadata` branch). Three states:

1. **`Add +`** — release not in library (`in_my_library` false / `book_id` null). Click → POST `/api/library/books` (#04) → on success navigate `/library/:bookId` (per #02). Post-click behavior per Q3c.
2. **`In Library`** — release already in library (`in_my_library` true). Disabled-as-add (greyed), but clickable → navigate `/library/:bookId` (Sonarr/Radarr-style jump-to-existing, per #02).
3. **`Find Downloads`** — the existing universal-mode "open ReleaseModal" affordance. Present in both the `Add +` and `In Library` states (the user can always find releases; grab gate was repealed by #04). Preserves the existing `onFindDownloads?.(book)` → `setReleaseBook` path at `App.tsx:1608-1631`.

Direct-mode rows (`!isMetadata`) keep the existing Download button unchanged — they have no metadata-provider book to Add from (#01's `UNIQUE(metadata_provider, provider_book_id)` NOT NULL contract would be violated by a synthesized row).

**Q3b — in-library state data flow (reuse search-result `in_my_library`):**

`handleShowDetails` (`App.tsx:943-978`) reads `in_my_library` + `book_id` from the already-fetched search-result row when opening DetailsModal for `isMetadataBook(book)`. Zero extra round-trips; the In-Library state renders instantly.

**This supersedes #04 sub-decision 19** ("separate `GET /api/library/books/:book_id` lookup for the already-in-library button state") for the search→DetailsModal path: Q2's batched JOIN makes a separate lookup redundant when a search response is in hand. #04's `GET /api/library/books/:book_id` endpoint survives for direct `/library/:bookId` navigations where no search response is available (e.g. deep links, browser back) — it's not deprecated, just not the source of truth for the modal-render path. *(Map amendment recorded against #04.)*

**Q3c — Add-click loading UX (label-swap + spinner + disable):**

On click: button label swaps to `Adding…` with a spinner icon, button disabled (prevents double-submit). On success (response carries `book_id`): navigate `/library/:bookId`. On 503 (provider down — #04 sub-decision 13: no `books` row inserted on failure): button reverts to `Add +`, inline error toast `Metadata provider unavailable — try again`; user stays on DetailsModal with a recoverable error (does not navigate to a dead `:bookId`). Matches the existing `BookActionButton` state-swap idiom and the #08 first-pass prototype's loading pattern.

### Q4 — "Use existing" affordance on release rows (tick only)

Tick / "On disk" badge on every release row where `is_on_disk` is true. **No navigation action in the badge** — the badge is informational, not an affordance. Re-grab stays via the existing `Get` button (grab gate repealed by #04). Library-jump-to-`:bookId` is owned by Q3a's Add-to-Library button on `DetailsModal`, not the release row.

Defended against the "conditional 'Use existing' when `book_id` exists" option: a release being on disk doesn't mean a `books` row exists (the `book_id`-never-set gap), so a "Use existing" link would dead-end for any release whose `book_id` is null. The Q3a modal-button path owns the `:bookId` navigation where a metadata-provider book exists to Add from — that's the right surface for it.

### Contract dependencies surfaced

1. **#04 amendment (sub-decision 19 superseded for the search→DetailsModal path)** — Q3b makes the batched JOIN in `/api/releases` the source of truth for the already-in-library button state on DetailsModal; #04's separate `GET /api/library/books/:book_id` lookup survives only for direct navigations. Recorded on map.
2. **#11 owns the contract implementation** with four pieces: (a) the `task_id` derivation extraction into a shared pure function the search path calls pre-queue (Q1); (b) the `/api/releases` batched JOIN adding `is_on_disk` + `book_id` + `in_my_library` (Q2 + Q3b); (c) the `DetailsModal` footer button's three-state shape + the Add-click loading UX (Q3a + Q3c); (d) the release-row "On disk" tick/badge rendering (Q4).
3. **#11 also owns wiring `book_id` into `record_download`/`finalize_download_files`** (the `map.md:50` fog item). **Hard dependency**: without this, the Q2 batched JOIN finds rows but `book_id` is always null, so `in_my_library` can never be true via the search path — the `In Library` button state on the modal (Q3a state 2) would never render. This was previously an "and/or #11/#02" fog item; #09 sharpens it to a hard #11 contract obligation.

### Ticket-number correction

The ticket's "Output" line said "Implementation lives in #12 (search integration)" — that's wrong. **#11 is the search-integration impl ticket** (its title: "Search/Release-list integration: dedup indicator + add-to-library button"); #12 is author browse MVP. Corrected here; not a decision, just a typo surfaced in the grilling.
