Type: grilling
Status: resolved
Blocked by: 02
Assignee: glm-5.2-fast (claimed 2026-07-20; resolved 2026-07-20)

# Frontend routing philosophy

## Question

The architectural survey confirms the React app today has **only one route** — the login gate (`src/frontend/src/main.tsx:17`). Everything else is modal/sidebar state inside `App.tsx`. Your request demands persistent URLs for book detail (URL shareable like Grimmory). The grilling session settled "new top-level routes".

This ticket decides the routing shape — the contract that #08 (book detail UI) and #10 (bookshelf UI) build against.

Open questions this ticket must resolve:

- **What are the new routes?** Likely candidates:
  - `/library` — the bookshelf grid.
  - `/library/:bookId` — book detail page. What's the `bookId` shape — numeric DB id (e.g. `/library/42`), or slug (`/library/hardcover/12345-the-silmarillion`)? Numeric is simpler to mint; slug is shareable. Pick one.
  - `/authors/:authorId` — author browse (#11) — possibly punted until #11.
  - ~~`/library/:bookId/find` — the "no files on disk" branch from #02~~ — **dropped per #02's resolution.** Find Releases is a modal on book detail (re-uses existing `ReleaseModal`), not a routed view. #02 sub-decision 4 settles this; #07 just reflects it.
- **Route guards:** existing `login_required` runs server-side; the frontend just gates on session presence. Library routes should redirect to `/login` (via the existing `LoginPage` rendering) when unauthenticated. Match that pattern.
- **What happens to the existing single-page layout?** Today the search/results/activity are all in `App.tsx`. Adding routes means either:
  - A. Each route is a separate top-level view and `<Header>` is shared. Home page (`/`) becomes the existing search UI; `/library` and `/library/:bookId` are siblings.
  - B. Library stays embedded (modal/sidebar) and only book detail gets a real URL. (Contradicts "new top-level routes" from the grilling session — caller rejected this.) Take plan A.
- **Persistent state on book detail**: the activity sidebar must remain accessible from book detail. Decide — is it global (sticky across all library routes) or only on search? Likely global; decide and document.
- **404 behaviour** at `/library/:bookId` for a book not in the requester's library vs not in any library. Different messages.
- **Loading & error states** for fetch-by-bookId. Decide the skeleton/error UI philosophy.

Output: a routing contract (route table, what each route renders, what shared layout wraps, how the activity sidebar stays accessible on library routes). #08 and #10 code against it.

## Outcome of this ticket

Routing contract document. Implementation is part of #08 (which sets up the routing infrastructure as it lands the first library route).

## Update from #04 (applied when #04 was resolved 2026-07-20)

#04 confirmed the contract for routes landing in `bookflow/core/library_routes.py`. Two routes confirmed per #02 + #04:

- `/library` — the bookshelf grid.
- `/library/:bookId` — book detail page.

No `/library/:bookId/find` route (already settled by #02 sub-decision 4 — Find Releases is a modal, not a route). No `/library/:bookId/downloads/:historyId` route — `POST` and `DELETE` actions on `downloads/:history_id` are API-only routes, not user-facing URLs. Author browse `/authors/:authorId` is owned by #12 (punted until then, per the route-list candidates above).

#07 just needs to decide: `bookId` shape (numeric DB id `/library/42` vs provider-prefixed slug `/library/hardcover/12345-the-silmarillion`), shared layout wrapping, route guards, 404 behavior, loading/error states. The route list itself is closed.

## Answer

Resolved 2026-07-20 by grilling session. The contract is shaped against the **actual** frontend state, which differs materially from the ticket's framing: `react-router-dom` v7 is already installed (`src/frontend/package.json`), `BrowserRouter` already wraps `<App>` (`src/frontend/src/main.tsx:17`), and `<App>` already renders `<Routes>` with two entries — `/login` and `/*` (`App.tsx:2853-2875`) — where `/*` renders `mainAppContent` (the search UI + modals) when authed, else `<Navigate to=/login?return_to=...>`. So the decision is **how to introduce nested routing inside the authenticated app shell**, not whether to adopt a router. Each sub-decision recorded with rationale.

### Sub-decisions

1. **Shared layout shape — nested `<Routes>` inside `mainAppContent` (Option A).** `mainAppContent` (the `/*` route's element, `App.tsx:2375`) renders `<Header>` + `<DownloadsSidebar>` (hoisted, see sub-decision 6) + a nested `<Routes>` where `/` is the existing search UI extracted into a `<HomePage>` component, and `/library`, `/library/:bookId` are siblings. Header never remounts on nav between search and library; activity sidebar state preserved naturally. Smallest diff to existing structure; matches the map's "shared `<Header>`" framing. Rejected: B (top-level routes per feature, each its own Header instance) regresses on the ticket's own persistence requirement by remounting Header on every search↔library nav. Rejected: C (layout route + `<Outlet>`) is a larger refactor of code with no outlet today, with no payoff for two extra routes.

2. **`bookId` shape — numeric DB id, `/library/:bookId` where `:bookId` is the integer `books.id` PK (Option A).** `/library/42`. Frontend already holds `book_id` from #04's Add response (`{book_id, files_exist_globally, in_flight_globally, in_my_library}`); matches #04's API path `/api/library/books/:book_id` uniformly across providers (Hardcover numeric ids, Open Library `OL*W` keys, Google Books opaque ids — uniform under the surrogate id); no drift or normalization logic. Rejected: B (provider-prefixed natural key) introduces a second addressing scheme vs the API and forces a lookup/reshape. Rejected: C (numeric id + title slug) — slug is cosmetic (lookup by `:bookId`), drifts if titles ever change, adds redirect/normalization. Readability of the URL is not load-bearing: the book-detail page renders the title prominently; the URL doesn't need to.

3. **Route guards — reuse the outer gate only, no per-route guard inside `mainAppContent` (Option A).** The existing `authRequired && !isAuthenticated ? <Navigate to={loginRedirectPath}> : mainAppContent` gate at `App.tsx:2845` already ensures `mainAppContent` doesn't render when unauthed. `buildLoginRedirectPath` (`utils/authRedirect.ts:67-75`) preserves the full current path + query + hash into `return_to`, sanitized to reject non-relative, `/login*`, `/api*` paths — so a deep-link to `/library/42?tab=formats` while logged out redirects to `/login?return_to=/library/42%3Ftab%3Dformats`, and post-login `getReturnToFromSearch` sends the user back to exactly that URL. `/library` and `/library/:bookId` pass the sanitizer (start with `/`, not `/login`, not `/api`) with zero new code. Nested routes render unconditionally inside `mainAppContent`; no `<RequireAuth>` wrapper. The HTTP layer's existing `login_required` on `/api/library/*` is the server-side backstop independent of any frontend guard. Rejected: B (per-route `<RequireAuth>`) is redundant — `mainAppContent` doesn't render at all when unauthed. Rejected: C (move auth into nested routes, drop outer catch-all gate) is a larger refactor affecting the existing search UI too — out of scope.

4. **404 behavior — single generic `LibraryNotFound` page for both API 403 (not in requester's library) and API 404 (book id doesn't exist) (Option A).** When `GET /api/library/books/:book_id` returns 403 (non-admin lacks `user_library` membership) or 404 (no `books` row for that integer PK), the `/library/:bookId` route renders the same `LibraryNotFound` component: a "Book not found" page with a link back to `/library`. No Add-to-Library CTA on this error state. Rejected: B (distinct 404 vs "not in your library" pages with an Add-to-Library CTA on the latter) — the CTA isn't useful enough to justify the second route element and the (minor) book-existence information leak; users who land on a deep link for a book they don't have can search and add from search-results per #02's `DetailsModal` flow, which is the canonical Add entrypoint anyway. Admin viewing another user's book returns 200 (admin reads any per #04 sub-decision 2) and renders detail normally — not a 404.

5. **Loading + error + cache philosophy — skeleton + inline error card with retry + no cache (A1 + B1 + C1).**
   - **Loading (A1)**: structural skeleton matching the book-detail layout (cover silhouette, title bar, format-row placeholders) on mount, between route mount and fetch resolve. Communicates "this is where the content lands"; a centered spinner on a content-heavy page reads as broken.
   - **Error (B1)**: inline error card on the page with a retry button. URL stays valid (shareable, back button works naturally); retry re-issues `GET /api/library/books/:book_id`. Covers transient 5xx and network errors. The 403/404 cases route to `LibraryNotFound` per sub-decision 4, not to this error card.
   - **Cache (C1)**: no stale-while-revalidate; always fetch on mount. Simplest coherent set — every fetch is one `GET`, fast enough for MVP. A SWR/React Query cache layer is a graduation candidate if back-navigation feels slow, parked on the map.

6. **Activity sidebar — global sticky, accessible on all three routes (A1 + B1).** The downloads sidebar is hoisted to `mainAppContent` level, **outside** the nested `<Routes>`, so a single mounted instance persists across `/`, `/library`, `/library/:bookId`. The sidebar's open/closed state and its socket subscription survive route transitions. `<Header>`'s downloads-button toggle (`onDownloadsClick={toggleDownloadsSidebar}` at `App.tsx:2387`) works everywhere. Auto-open-on-download-start behavior is the socket subscription's concern, not a routing decision — it stays as-is and fires on whatever route the user is on when the event arrives. Rejected: A2 (per-route sidebar instances) regresses on persistence — state resets on nav, losing in-flight download visibility. Rejected: B3 (skip bookshelf from the toggle) is arbitrary asymmetry with no justification.

7. **Filesystem layout — new `src/frontend/src/library/` directory (Option A1).** `LibraryPage.tsx`, `BookDetailPage.tsx`, `LibraryNotFound.tsx`, and any library-specific hooks/components live as a co-located sub-tree under `src/frontend/src/library/`. Keeps the library feature discoverable and bounded; mirrors how future features might grow. Rejected: A2 (flat in `src/frontend/src/components/` next to `DetailsModal.tsx`, `Header.tsx`) pollutes the flat dir with three+ new files for one feature.

### Route-table contract (the output of this ticket)

What #08 and #10 code against (given Q1–Q6 above):

```tsx
// Inside mainAppContent (which is the element of the /* route at App.tsx:2375):
<Header ... />
<DownloadsSidebar ... />  {/* hoisted, outside nested Routes — sub-decision 6 */}
<Routes>
  <Route path="/" element={<HomePage />} />                              {/* extracted search UI — #08's mechanical concern */}
  <Route path="/library" element={<LibraryPage />} />                    {/* #10 builds this */}
  <Route path="/library/:bookId" element={<BookDetailPage />} />         {/* #08 builds this; :bookId is integer books.id — sub-decision 2 */}
  <Route path="*" element={<Navigate to="/" replace />} />               {/* unknown sub-path under /* — bounce to home */}
</Routes>
```

- **Auth**: outer `mainAppContent`-only gate (sub-decision 3); deep-link to `/library/42` while logged out redirects to `/login?return_to=/library/42` via the existing `buildLoginRedirectPath`. No per-route guard.
- **`:bookId`**: integer `books.id` PK, e.g. `/library/42` (sub-decision 2).
- **404 at `/library/:bookId`**: single generic `LibraryNotFound` page for API 403 and 404 (sub-decision 4). No Add-to-Library CTA on the error state.
- **Loading**: skeleton matching book-detail layout (sub-decision 5, A1).
- **Error**: inline error card with retry, URL preserved (sub-decision 5, B1).
- **Cache**: none — fetch on every mount (sub-decision 5, C1).
- **Sidebar**: hoisted outside the nested `<Routes>`, accessible on all three routes (sub-decision 6).
- **Author route `/authors/:authorId`**: owned by #12; the contract reserves the namespace but does not create the route here.
- **`HomePage` extraction**: today's search UI is inline in `mainAppContent`. To make the nested `<Routes>` work, the search UI tree becomes a `<HomePage />` component rendered at `/`. This is a mechanical extraction that #08 does as it lands the first new route — the ticket's Outcome section already says "Implementation is part of #08 (which sets up the routing infrastructure as it lands the first library route)."

### Map framing correction — `react-router-dom` is already installed and in use

The map's `## Notes` "Standing preferences" section says: *"The frontend has no router beyond the login gate today (`src/frontend/src/main.tsx:17`) — library routes are the first real routes."* This is **factually stale** and should be amended when the map is updated next:

- `react-router-dom ^7.18.1` is in `src/frontend/package.json`.
- `BrowserRouter` wraps `<App>` at `src/frontend/src/main.tsx:17`.
- `<App>` renders `<Routes>` with two entries at `App.tsx:2853-2875`: `/login` and `/*`.
- `useNavigate`, `useLocation`, `<Navigate>`, `<Route>` are all imported and used across `App.tsx`, `hooks/useAuth.ts`, `hooks/useSearch.ts`.

The accurate framing: the router is installed and the login gate is already a real route; the `/*` catch-all renders `mainAppContent` (a single monolithic tree containing `<Header>` + search UI + modals + sidebar) when authed. The decision #07 settles is how to introduce **nested routing inside the authenticated app shell**, not whether to adopt a router at all. This correction belongs in the map's Notes (replacing the stale line) when #07's resolution is appended; left here in the answer so the map's gist below carries an accurate one-liner.

### What this ticket does NOT decide (deferred to other tickets)

- Book-detail page UX (the expanded `ReleaseModal`-style shell, format rows, in-flight indicator, empty state with persistent Find Releases button, Send-to-Kindle button) → #08. #07's contract dictates the route, the `:bookId` shape, the 404/loading/error behavior, and the global sidebar; #08 owns everything inside the `<BookDetailPage />` element.
- Bookshelf page UX (grid, file-less entry "Find this book" affordance, search-within-library) → #10.
- `HomePage` extraction details — pulling the existing search UI out of `mainAppContent` into a `<HomePage />` component at `/` → #08's mechanical concern per the Outcome section; #07 just requires it as a precondition for the nested `<Routes>` to compile.
- Search-results card + `DetailsModal` Add/In-Library button wiring → #11.
- Author browse route `/authors/:authorId` → #12.
- Pagination of `GET /api/library/books` (already deferred per #04 sub-decision 9) — surfaces when a user feels the absence.

### Knock-on effects on other tickets (to be applied when those tickets are worked)

- **#08 (Book detail page UI)**: scope restated per #02's Outcome + #04's knock-on-effects + #07's contract. #08 builds `<BookDetailPage />` at `/library/:bookId`, `<HomePage />` (the mechanical search-UI extraction), `<LibraryNotFound />`, and the nested `<Routes>` infrastructure inside `mainAppContent`. It also does the `HomePage` extraction as it lands the first new route. `:bookId` is integer; skeleton loading; inline error+retry; single generic 404 page for 403 and 404; sidebar is hoisted outside its route. The Find Releases modal auto-open behavior from #02 sub-decision 5 still applies on navigation, gated by `LIBRARY_AUTO_FIND_RELEASES`.
- **#10 (Bookshelf UI)**: builds `<LibraryPage />` at `/library`; the sidebar is already mounted globally by #08's infrastructure, so #10 doesn't touch it.
- **#11 (Search integration)**: implements the Add button on the search-results card and `DetailsModal`; on Add success, navigates to `/library/:bookId` (integer id from the Add response). If the book is already in the user's library, the card's Add button becomes navigate-to-`/library/:bookId`.
- **#12 (Author browse MVP)**: introduces `/authors/:authorId` as a new sibling route inside the nested `<Routes>`; #07's contract reserves the namespace. #12 decides `authorId` shape (instance-local numeric PK if it introduces an authors table, or provider-scoped slug) — the analogous decision to #07's Q2, scoped to authors.

### Context assets

- `src/frontend/package.json` — `react-router-dom ^7.18.1` already a dependency (corrects the map's stale "no router beyond the login gate" framing).
- `src/frontend/src/main.tsx:17` — `BrowserRouter` wraps `<App>`.
- `src/frontend/src/App.tsx:2375` — `mainAppContent` (the `/*` route's element) — where the nested `<Routes>` is introduced per sub-decision 1.
- `src/frontend/src/App.tsx:2845-2875` — the outer auth gate (`<Navigate to={loginRedirectPath}>`) and the existing `<Routes>` with `/login` + `/*` routes.
- `src/frontend/src/App.tsx:2387` — `onDownloadsClick={toggleDownloadsSidebar}` on `<Header>`; the sidebar toggle plumbed through the header (now global per sub-decision 6).
- `src/frontend/src/hooks/useAuth.ts:36-37` — `useLocation` + `useNavigate` usage precedent; the auth hook already integrates with the router.
- `src/frontend/src/utils/authRedirect.ts:67-75` — `buildLoginRedirectPath` preserves the deep-link target into `return_to`; already handles `/library*` paths with zero new code.
- `.scratch/library/issues/02-add-to-library-flow-contract.md` sub-decision 4 — Add always navigates to `/library/:bookId`; no `/library/:bookId/find` route.
- `.scratch/library/issues/04-library-api-contract.md` route table — `GET /api/library/books/:book_id` returns 403 on non-admin non-membership, 404 on no books row — the API contract #07's 404 decision keys off.
- `.scratch/library/issues/01-book-library-data-model.md` — `books.id` is the integer PK; `(metadata_provider, provider_book_id)` is the natural key (both NOT NULL). Justifies #07's integer `:bookId` choice.
