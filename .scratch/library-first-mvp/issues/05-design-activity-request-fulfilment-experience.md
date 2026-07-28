Type: prototype
Status: resolved
Blocked by: 01, 02

# Design Activity as the request fulfilment experience

## Question

Prototype how Activity works inside the new shell for both roles, with request fulfilment as the admin's operational workflow.

Request-only users need a clear view of their book-level request state without release/indexer information. Admins need pending requests prominent, enough requester/book context to start a search, and a clear handoff from selecting a release to fulfilling the request. Reuse the existing request queue and activity foundations where possible. Decide the information hierarchy and state presentation; notification delivery is out of scope.

## Answer

Activity remains the existing stateful right-side drawer: it is not a route or full page. The settled shell constraint rules out a duplicate standalone Activity prototype, so this decision was validated through the live product interaction discussion instead.

For a request-only user, Activity contains only a `Requests` view. It places their pending Request before terminal history and shows request-oriented status only: `Awaiting availability`, `Available`, `Not approved` (with an admin note when supplied), or `Cancelled`. A pending Request alone has a `Cancel request` action. Terminal Requests are durable history and have no clear or dismiss action. Activity never exposes a shared Download's progress, release, indexer, source, or other download-machine detail to this role.

For an admin, Activity opens on `Requests` whenever Book work is pending; otherwise it retains `All` as the initial view. The `Requests` tab groups pending work into one Book work card for each canonical Book. Each card supplies the Book identity, requester count, and an expandable requester list. Its primary action is `Find release`; its secondary actions are `Mark available` when Files already exist and `Reject` for one selected requester. Terminal Request history follows the pending work and is not dismissible. The current user filter may operate on the requester list, rather than returning to one card per Request.

`Find release` opens the existing Book-scoped release picker as a modal above the current screen and retains the Book plus pending-requester context. Activity stays open beneath it. Selecting a release closes the picker and creates one shared Download that appears independently in the admin's `Downloads` view; the pending Book work card leaves the queue. If the shared Download fails, its Book card returns to the pending queue with `Previous download failed`, and `Find release` is the retry path. The failed Download remains visible only to admins in `Downloads`.

If requesters cancel during a shared Download, the Book card's requester list and count update live. If no pending Requests remain, the Book card disappears, but the Download continues in the admin `Downloads` view. Its resulting Files remain globally available; no user receives request-derived File links from that run. Existing WebSocket-driven Activity refreshes are reused for these state changes.
