Type: task
Status: resolved
Blocked by: 06, 07, 10

# Implement the validated bookshelf UI

## Question

Promote the validated contract from [Bookshelf / library view UI](10-bookshelf-ui.md) into production-quality code on a new feature branch. Do not merge or polish the prototype branch directly.

Use `library/10-bookshelf-prototype` at `c0540e1` as the visual and interaction reference, then reimplement it against the live `GET /api/library/books` contract from #04/#06 and the nested `/library` route from #07.

Production work includes:

- A responsive cover-forward grid with provider cover art, title, primary author, and compact global-format badges.
- A neutral title-initial fallback for books without a cover.
- Client-side title/author search and `All / Has files / Needs files` filters over the unpaginated result set.
- Navigation from a book card to `/library/:bookId`.
- A `Find this book` affordance for file-less books that opens that book detail route with Find Releases open.
- Loading, empty, and request-error states using the application's existing patterns.

The activity sidebar must remain available on this route per #07. Do not add pagination, server-side structured filtering, or a new component dependency.

Verification: `make checks` passes; the page renders against seeded/live library data; title/author search and each file-state filter work; card navigation and `Find this book` route correctly.

## Answer

Implemented on `feature/library-bookshelf` in commits `1516c00` and `1e8f46e`. `LibraryPage` renders the live unpaginated `GET /api/library/books` response as the validated responsive cover shelf, with cover fallbacks, compact global-format badges, client-side title/author search, and All / Has files / Needs files filters. It includes loading, empty, filter-empty, and retryable error states; cards navigate to detail, while file-less books use `?find=true` to open Find Releases, including when an in-flight release exists. Added typed list API response support and the `/library` route. `npm run build`, typecheck, formatting, and 120 frontend unit tests pass. `make checks` remains blocked by five pre-existing Oxlint errors in `useUsersFetch.ts` and `SelfSettingsModal.tsx`.
