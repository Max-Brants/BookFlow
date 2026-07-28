Type: grilling
Status: resolved
Blocked by:

# Reconcile request policy with library-first user capabilities

## Question

Define the canonical capability model for the MVP and reconcile it with BookFlow's existing per-user request-policy system.

A download-capable user may search releases and queue downloads. A request-only user may browse, add books, and submit only book-level requests; they never see indexer/release selection. Admins can download and fulfil requests. Decide the durable representation, migration from the current policy modes, permission boundaries for every relevant API/action, and how an admin's fulfilment links a selected release back to the request and requester.

The outcome must state whether the existing policy model is simplified, wrapped, or retained internally, and define the terms used by every later ticket.

## Answer

BookFlow starts greenfield with one required, admin-managed `library_capability` user field: `download-capable` or `request-only`. Admin status remains a separate privilege; admins may operate the request queue and queue Downloads regardless of their capability value.

The existing request-policy system is removed rather than retained, wrapped, or migrated. There are no source/content policy rules, request-policy settings, release-level Requests, or legacy compatibility paths.

A request-only user may add a Book to their Library, then explicitly create, read, or cancel their own book-level Request for that Book. Adding a Book does not create a Request. Every new Request stores the canonical `book_id`; matching is exact Book identity, never title/author inference. Request-only users cannot search or select releases.

A download-capable user may use Book-scoped release search and queue Downloads, but cannot create Requests. The environment-level direct-search override and its retirement boundary are decided separately.

Admins may search, queue Downloads, inspect all Requests, reject/reopen Requests, and fulfil pending Requests. Selecting one release for a Book fulfils every pending Request for that Book. The Download records those fulfilled Requests; when its Files finalize, they are linked to every requester so each requester sees the shared release in their Library. The detailed Request state machine is deferred to the lifecycle ticket.
