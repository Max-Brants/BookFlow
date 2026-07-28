Status: wontfix

> Closed for this planning-only map. Recreate or move this implementation work into the post-spec implementation effort.

# Implement the polished book-detail experience

## Scope

Implement the settled Book detail experience described by [Design the polished book-detail experience](04-design-polished-book-detail-experience.md).

Use the API-backed prototype on [`prototype/book-detail-experience`](https://github.com/muneebabbas/bookflow/tree/prototype/book-detail-experience) as a visual and interaction reference. The prototype is enabled locally at `/library/<bookId>?prototype=detail` and must not be promoted directly: remove the development gate and rewrite its throwaway code as production-quality components.

## Acceptance criteria

- Book identity, provider metadata, ratings, and description lead the page; the desktop layout is wide and remains responsive on narrow screens.
- Available files show the newest completed File per format with direct download actions.
- A collapsed advanced section shows all releases, including every File in multi-File releases, indexer/source, grab date, protocol, per-file downloads, and release unlinking.
- Send to Kindle is a distinct delivery control with an explicit selected format; EPUB remains the default.
- Find another release is an advanced action, while the existing one-shot first-add release-search navigation behavior remains unchanged.
- Request-only users receive the settled add/request/pending/cancelled/fulfilled presentation once the Book detail API supplies Library Capability and Request state. They must not see release, indexer, or download-machine controls.
- Add focused frontend and route/API tests for the production behavior.

## References

- [Book-detail design decision](04-design-polished-book-detail-experience.md)
- [Library-first MVP map](../map.md)
- [`prototype/book-detail-experience`](https://github.com/muneebabbas/bookflow/tree/prototype/book-detail-experience)
