# File availability gates catalog and library membership

**Status:** accepted

A Book without an imported File is a request target, not a catalog or library item. It may only be represented by Requests. A Book becomes catalog-visible when at least one File is imported. A user may receive Library membership only for a catalog-visible Book and must receive an entitlement to at least one imported File at the same time.

## Decision

- A Request records a user's interest in a fileless Book and optional durable Kobo Sync intent. Admin requests are approved immediately; user requests wait for an administrator's book-wide approval.
- One approved Book has at most one active request process. The first approved request snapshots its selected named release Profile. Importing a File fulfils every approved request for that Book and atomically creates membership and file entitlements for every requester.
- Catalog queries require an imported File. Library queries and file serving require both membership and file entitlement.
- Existing fileless library rows are migrated to Requests instead of preserving wishlist membership.

## Consequences

- Request history is distinct from library state: active requests remain visible until a File is imported; fulfilled, rejected, and cancelled requests remain historical records.
- Release Profiles make automatic request processing deterministic. Automatic Search skips hard-filter failures, blocklisted candidates, negative scores, and candidates below the profile minimum. Interactive Search may force-select any candidate only with an audited administrator override.
- A direct add to **My Library** is available only after import; it grants entitlements for the Book's currently available Files and never starts a request process.
