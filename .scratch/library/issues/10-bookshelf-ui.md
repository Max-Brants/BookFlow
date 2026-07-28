Type: prototype
Status: resolved
Blocked by: 04, 07

# Bookshelf / library view UI

## Question

Build the bookshelf grid at `/library` — the user-facing landing of the library feature. This is a **prototype ticket**: land a concrete artifact to react to, not a bullet list of opinions.

What the page must show (per grilling session):

- **Cover thumbnails** for each book in the user's library. Cover is from the metadata provider (`books.cover_url`) per the art decision.
- **Per-book affordance** — clicking a cover/row navigates to `/library/:bookId` (#07 routing).
- **Formats-on-disk indicator** — small badges or icons for which formats are available for that book globally (e.g. `EPUB MOBI AZW3`). Empty-set means the book is in the library but no files exist anywhere yet — a **"Find this book"** affordance lives here (graduated from #02's resolution of the file-less wishlist fog).
- **Filters** — by author (free-text? dropdown?), by `has_files` state (yes/no/any), text search across title/author. Settle which subset lands in the prototype.
- **Pagination or infinite scroll** — pick one; reflects the pagination decision from #04.

Architectural-survey constraints:

- Tailwind 4, no component library (`src/frontend/src/components/shared/` is the existing shared primitives).
- The activity sidebar stays visible on library routes per #07's contract — include `<Header>` (the existing component at `src/frontend/src/components/Header.tsx`) in the layout.
- Existing `App.tsx` is the single-page shell. This ticket adds the first real routes — the routing infrastructure itself lives here (or in #08, whichever lands first).

The prototype should fetch from `/api/library/books` (#04 / #06) when ready; otherwise mock data. Land as a real component under `src/frontend/src/pages/` — likely `LibraryPage.tsx` and `BookDetailPage.tsx` (the latter is #08).

Verification: `make frontend-typecheck` passes; the page renders against mock data without crashing; a click on a row navigates (URL changes) to the book detail page.

## Outcome of this ticket

Prototype React code on the feature branch plus a written note in the resolution on what worked and what didn't.

## Comments

- Prototype: `library/10-bookshelf-prototype` at `c0540e1` adds `/library/prototype?variant=A|B|C` with mock data and the real app shell. `npm run typecheck` passes. Awaiting a user-selected direction before resolution.

## Answer

Variant A, **Cover shelf**, is the validated direction. The production bookshelf is a responsive cover-forward grid: title, primary author, and compact format badges live below each cover; a neutral title-initial placeholder replaces missing covers. It provides client-side title/author search and an `All / Has files / Needs files` filter against the unpaginated result set. File-less Books show **Find this book**, which navigates to book detail and opens Find Releases. Variants B and C remain prototype-only reference material on `library/10-bookshelf-prototype` at `c0540e1`.
