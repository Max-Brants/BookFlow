# Users & Requests

Configure instance settings in **Admin Settings**. User preferences are available through **My Account**.

## Authentication methods

BookFlow supports local accounts, proxy authentication, OIDC (OpenID Connect), and Calibre-Web database synchronization. Local accounts are created in BookFlow. Proxy and OIDC identities are created on first sign-in or linked to matching existing identities. Calibre-Web synchronization reads the mounted `app.db` at `/auth/app.db` and keeps its roles synchronized.

At least one local admin remains the fallback for authentication methods that need one. See [OIDC](oidc.md) for provider setup.

## Per-user settings

Admins can manage users and their settings. Non-admin users can edit their own exposed settings through **My Account**. Personal notification routes are separate from instance-level operational notifications.

## Requests

Books without an imported file can only be requested; they cannot be placed directly in **My Library**. Both users and admins can submit a book request and choose an active named release profile. A request can also record the user's request to add the book to Kobo Sync when it becomes available.

### Approval and availability

- An admin's request is approved immediately. A user's request starts as **pending approval** until an admin approves the Book.
- Approval is Book-wide: it approves all pending requests for the same Book and starts, or joins, one shared request process. The first approved request supplies the process's immutable profile snapshot.
- Active requests stay on **Requests** until at least one file has been imported. Then all approved requesters receive the Book in **My Library**, their imported-file entitlements, and their saved Kobo Sync intent.
- Administrators can upload a manually obtained EPUB from an active request or the Book detail page. A valid upload is added to the shared catalog and fulfils every active request for that Book.
- Rejected, cancelled, and fulfilled requests remain in the history tab. A user can cancel their own pending request.
- A Book with one or more imported files appears in **Catalog**. Users add it directly to **My Library**; this grants access to all currently imported files and does not create a request.

### Release profiles and searching

Admins manage named release profiles in **Admin Settings -> Profiles**. A profile defines allowed formats, languages, protocols and indexers plus size, seeder, bundle/archive, score and term rules. One profile is the default for new requests.

After approval, **Automatic Search** searches all allowed sources and chooses the best eligible release. Candidates that fail a hard filter, are blocklisted, have a negative score, or do not meet the profile's minimum automatic score are always skipped. If an attempted release fails for a release-specific reason, it is blocklisted and the next eligible result is tried.

Admins can use **Interactive Search** from a request to perform a fresh search. It shows every candidate with its score and rejection reasons. An admin can force-select any candidate, including a filtered, negative-score, safety-rejected, or blocklisted one, after confirmation. Every such override is recorded with the admin, time and reason; normal downstream file validation still applies.

### Pages and access

**Requests** is a standalone page. Users see their own active requests and history. Admins see Book-grouped requests, requesters, profile snapshot, request-process status, candidates and attempts. **Downloads** is a separate admin-only page for the live queue and download history; it is no longer a sidebar.
