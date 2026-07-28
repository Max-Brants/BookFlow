Type: grilling
Status: resolved
Blocked by:

# Define request lifecycle and ownership

## Question

Specify the state machine and ownership rules for Book-identified Requests now that Library Capability is settled. Decide the allowed transitions for pending, fulfilled, rejected, cancellation, and failed Downloads; whether a requester can submit again after each terminal outcome; how an admin's shared fulfilment is represented and retried; and which Activity views expose each state to requesters and admins. Preserve the rule that a fulfilment matches only pending Requests for the same canonical Book and links finalized Files to every requester.

## Answer

Requests are an availability signal for request-only users, not an approval or download-progress state.

- A request-only user creates a Request only when their Book has no completed Files. Adding a Book with completed Files immediately shows every available release and creates no Request.
- The only Request states are `pending`, `fulfilled`, `rejected`, and `cancelled`. `fulfilled` means completed Files are available to the requester, never merely that an admin selected a release.
- A requester may cancel a pending Request, including while a shared download is in flight. Cancellation does not cancel or alter that download; only Requests still pending at finalization receive its File links.
- An admin may reject one selected requester only. Rejected and cancelled Requests remain historical terminal records, and the requester may create a fresh Request for the Book while it has no completed Files.
- Admin Activity groups pending Requests by canonical Book and shows its requesters. Choosing a release starts one shared download; the Requests remain pending while it runs. When Files finalize, every still-pending Request for that Book becomes fulfilled and receives every File in the completed release. A failed download leaves Requests pending for a later attempt.
- If any completed Files become available for a Book by any path, every pending Request for it is fulfilled and receives access to all Files already linked to the Book. This also covers a user requesting while a shared download is in flight.
- The administrator may approve availability from existing Files without searching or choosing a new release: all pending Requests for that Book are immediately fulfilled and receive all existing Files for the Book.
- A fulfilled Request cannot be repeated while any completed Files remain. If all completed Files for the Book are later removed, a library member may submit a new Request; the earlier fulfilled Request remains history.
- Requester Activity shows their pending and terminal Request history using request-oriented status wording, without release, indexer, or in-flight-download details. Admin Activity additionally shows grouped pending work and the in-flight download separately.
