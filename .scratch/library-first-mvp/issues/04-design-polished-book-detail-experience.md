Type: prototype
Status: resolved
Blocked by: 01, 02

# Design the polished book-detail experience

## Question

Create a concrete prototype for the book detail page's information hierarchy and actions in the library-first shell.

The page must surface the existing metadata-provider description and ratings, make library/file/request/download actions understandable for both capability types, and retain Send-to-Kindle and explicit file download where permitted. It must use the settled one-shot Find Releases navigation intent only after a successful first add with no global files; direct links, refreshes, and later visits never auto-open search. Decide the visual hierarchy, empty/requested/available states, and action wording without designing author browse or notification behavior.

## Answer

The Book detail page remains a traditional wide desktop flow: Book identity, metadata-provider ratings, and description lead; **Available files** follows below. The default file view shows the newest completed File for each format with direct download. A collapsed **Advanced: show all releases** section exposes every release, including every File in a multi-File release, indexer, grab date, protocol, file-level download, and release unlinking.

Send to Kindle is a separate labelled panel beside the default files on desktop, stacked on mobile. It exposes the selected format and defaults to EPUB. Find another release is an advanced action following the all-releases section. The first-add one-shot release-search intent remains unchanged.

The integrated, API-backed prototype is captured on [`prototype/book-detail-experience`](https://github.com/muneebabbas/bookflow/tree/prototype/book-detail-experience) in `src/frontend/src/library/BookDetailPrototype.tsx`, enabled locally at `/library/<bookId>?prototype=detail`. It uses the real library, metadata, download, Kindle, unlink, and release-search APIs. Request-only state presentation remains for implementation once Library Capability and Request state are exposed to the page.
