Type: prototype
Status: resolved
Claimed by: wayfinder session 2026-07-23
Blocked by: 04, 05, 07

# Book detail page UI (with per-format downloads and Send-to-Kindle)

## Question

Build the new book detail page — the destination of Add-to-library per #02 (both files-exist and no-files branches land here). The central UI surface where downloads and Send-to-Kindle live.

This is a **prototype ticket** (per the wayfinder taxonomy): raise the fidelity of the discussion by making a concrete artifact to react to. The prototype can be:
- A. A static React stub that fetches mock data (or hits the live API from #06 if it's landed) and renders the layout. React-with-mock-data is fine.
- B. The full working component — only if #06 has shipped first.

Pick A if the API isn't ready, otherwise B.

**Scope per #02's resolution** — book detail is an "expanded `ReleaseModal`-style shell" that hosts the Find Releases modal. The page must host:

- **Cover image** — from metadata provider (`books.cover_url`). The grilling session settled on metadata-provider covers only — no file-extracted covers as fallback.
- **Title, author, subtitle, year, series** — denormalized from the `books` row.
- **Formats on disk section** — one row per available format (e.g. EPUB, MOBI, AZW3), shown when `files_exist_globally == true`. Each row shows the format name and a **Download** button for that format.
- **Empty state when `files_exist_globally == false`** — "no formats on disk yet" state with a persistent **Find Releases** button (graduated from #02 sub-decision 7). This is the state the user sees if they close the auto-opened Find Releases modal without picking.
- **Find Releases button** (always present) — opens the existing `ReleaseModal` (via the `setReleaseBook` pattern at `App.tsx:1608-1631`). When `files_exist_globally == false` and `LIBRARY_AUTO_FIND_RELEASES=true` (#02 sub-decision 5), the modal auto-opens on page load. Behavior of re-picking a release when files already exist is fog (parked on map); #08 does not need to resolve it.
- **In-flight downloads indicator** — if any downloads are currently active for this book across users (`final_status = 'active'` per #02's predicate), show an indicator (not the user — just "a download is in progress").
- **Send to Kindle** — one button, label shows the resolved format ("Send EPUB to Kindle"), with an adjacent override picker per #05. Greyed-out with tooltip when no Kindle-compatible format is on disk. Configured Kindle address is surfaced somewhere visible (settings link).

The architectural survey surfaces primitives worth reusing:
- Existing `DetailsModal` (`src/frontend/src/components/DetailsModal.tsx`) for the metadata-fetch shape. Decide whether to extend it into a routed page or build fresh.
- `Tailwind CSS 4` styling, **no component library** — match the hand-rolled primitives in `src/frontend/src/components/shared/`.

Foundational work this ticket drives: the actual `react-router-dom` route addition, the shared layout (header visible on library routes?), the activity-sidebar-stays-accessible rule from #07. The prototype IS where those decisions get tested.

Verification: `make frontend-typecheck` passes; the book-detail page renders against mock data without crashing; the activity sidebar still renders when navigated there.

## Outcome of this ticket

Prototype React code on the feature branch, plus a written note in the resolution about what worked and what didn't — particularly anything that challenges the assumptions in #02 or #07.

## Update from #04 (applied when #04 was resolved 2026-07-20)

#04 reshaped book-detail's scope. The page now hosts:

- **Cover/title/author/subtitle/year/series** — unchanged from above, denormalized from the `books` row.
- **Formats-on-disk as a UNION across all `download_history` rows for the Book** (high-level view): one row per unique format (epub, mobi, azw3, pdf, ...), deduped across releases. Each row has a Download button.
- **Per-file list (release-level detail)** — underneath the union view, the page shows one row per `download_history` row linked to the Book (and visible to this user via `user_downloads`), with: `{format, size, indexer_display_name, protocol, downloaded_at, downloadable_by_me}`. This is where release-level metadata surfaces.
- **Unlink affordance per file row** — `DELETE /api/library/books/:book_id/downloads/:history_id`; hard-deletes the `user_downloads` link; file/`download_history` row untouched. Available to the user on files they've linked via their own `user_downloads`.
- **Empty state when no files exist** — unchanged from above. Persistent Find Releases button.
- **Find Releases button** — always present, ungated for all users. (Q3 grab gate from earlier #04 grilling is **repealed** — users can grab another release anytime.) When `files_exist_globally == false` and `LIBRARY_AUTO_FIND_RELEASES=true`, still auto-opens on page load (#02 sub-decision 5).
- **In-flight indicator** — unchanged from above. Shows "a download is in progress" when `in_flight_globally == true` (no user attribution).
- **Send to Kindle** — one button, label "Send <FORMAT> to Kindle" (the format per #05's algorithm), with an adjacent inline override picker (per #05's narrowed scope — #05 decides priority; #08 implements the UI for the picker). Greyed-out with tooltip when no Kindle-compatible format is on disk (per #05 sub-decision 2).
- **No manual refresh button**, no refresh-metadata affordance. Out of scope for this effort per #04 sub-decision 18 — the `books` row at Add time is final for this MVP.

**Unlink mid-flight** (a user unlinks an active `final_status='active'` `download_history` row from their `user_downloads`) — UX decision: disallow with error, or allow with warning that "the file will still complete but you won't see it until you re-add." Parked as the one open UX sub-decision for #08 itself.

#08's open questions (still owned by #08, not #04):

- `bookId` shape for the URL (numeric DB id vs slug) — actually #07's call, but #08 consumes it.
- Whether to extend `DetailsModal` into a routed page or build fresh — prototype-time decision.
- Loading & error states — referenced from #07's contract.
- Activity sidebar accessibility on library routes — referenced from #07's contract.
- Unlink mid-flight UX (above).

## Answer

The revised prototype is on `library/08-book-detail-prototype-reconciled` at
`dfc2b4e` (including #14's multi-file release contract).

The page has two levels:

- **Available formats** is the default, common-case view. It displays one
  concrete File per format: the newest completed File by `downloaded_at`, with
  descending `history_id` as the deterministic tie-breaker. Each row shows
  compact provenance (`latest from <source> · <date>`) and downloads that
  selected File.
- **Releases** is a collapsed advanced section. It groups the flat API
  `files[]` payload by `task_id`, then shows source, completion date, and each
  exact File. A user can download a specific File here to retry an earlier EPUB
  or choose a particular release. Unlink appears once per group and explicitly
  removes the entire release, matching #13's release-atomic API behaviour.

Send-to-Kindle remains independent of which advanced File a user inspects: it
uses #05's EPUB-first priority (or the inline format override) and sends the
latest completed File for that chosen format. In-flight releases appear in the
advanced section without an unlink control because their file links do not yet
exist. The prior prototype's single-file-per-release rendering and obsolete
mid-flight-unlink assumption were removed.

`npm run typecheck` passes in the prototype worktree. This prototype is the
validated UI contract; production-quality integration remains implementation
work on a feature branch, not a change to `main` from this ticket.
