# Security threat model

This review covers BookFlow's authenticated API, release discovery, download
pipeline, central file store, archive handling, Kobo synchronization and
operator workflows. Re-run it when an authentication mode, remote source,
download client, file-serving route or trust boundary changes.

## Assets and trust boundaries

- Session cookies, Kobo bearer tokens, OIDC and provider credentials are
  secrets. They must never enter structured logs, candidate JSON, metrics,
  browser storage or user-visible error details.
- `/config` contains the SQLite database and credentials; `/books` contains
  trusted imported output. Search providers, download clients, archives and
  paths returned by remote clients are untrusted input.
- Admin authority, user identity, file entitlements and per-user Kobo shelf
  state are resolved server-side. Client-supplied user IDs never grant access.

## Required controls and review evidence

| Threat | Required control | Regression coverage |
| --- | --- | --- |
| IDOR across libraries, requests, files or Kobo shelves | Resolve the actor from the authenticated session/token; scope every read and mutation by `user_id` or explicit entitlement; require admin on operational endpoints | v1 API, library, request and Kobo service/route tests |
| SSRF through covers, metadata or release URLs | Allow only supported HTTP(S) targets, reject private/reserved destinations after DNS resolution, bound redirects/body/timeouts, and keep provider credentials out of persisted candidate data | image-cache, proxy and release-source security tests |
| Archive bombs, traversal and executable payloads | Bound member count and expanded bytes, reject absolute/parent/reparse paths and suspicious executables, extract into a private staging root, validate before publication | archive, scan, path-security and KEPUB validator tests |
| Path escape or remote-client cleanup abuse | Resolve real paths beneath configured roots; normalize Windows/POSIX remote paths independently of host OS; never recursively delete an unresolved path | path-security and external-client adapter tests |
| Token theft, guessing or replay | Store only a slow hash and short display prefix, show plaintext once, rotate/revoke atomically, rate-limit valid and invalid token identities by source IP, use constant-time comparisons, sign cursors | Kobo token, cursor and rate-limit tests |
| Pairing-code replay or endpoint substitution | Sign a ten-minute self-describing code, store only the nonce hash, consume once, rate-limit code/IP attempts, require public HTTPS, bind completion and the returned Kobo endpoint to the confirmed origin, and revoke on patch failure | pairing service, route and patcher-origin tests |
| Push subscription disclosure or abuse | Accept HTTPS/loopback endpoints only, never return auth key material, apply per-user event filters server-side, retire 404/410 subscriptions and keep payloads free of secrets | web-push service, route and durable-event tests |
| Corrupt or malicious restore archive | Verify the checksum manifest, encryption authentication, archive paths, SQLite integrity and supported schema in staging; replace only before DB initialization and first make a safety backup | backup service and startup-restore tests |
| CSRF or cross-origin mutation | Same-origin validation plus `X-BookFlow-CSRF` on cookie-authenticated mutations; POST/PATCH/PUT/DELETE only; restricted Socket.IO origins and authorized rooms | HTTP security, v1 API and WebSocket tests |
| Authentication downgrade | A configured but unavailable provider is `unavailable` and returns 503; it never falls back to `none` | auth-mode and readiness tests |
| Secret disclosure in telemetry | Structured logger redacts credential-shaped keys and bearer/query secrets; metrics contain bounded route classes and aggregate counters only | logger-redaction and metrics tests |
| Duplicate or replayed external side effects | Durable idempotency keys, lease-backed jobs and one active attempt per request process; reconcile expired leases before claiming | durable-job, scheduler and request-process integration tests |

## Operational assumptions

- Deploy one SQLite writer for a `/config` volume and use an immutable image
  digest. Do not expose SQLite over a shared network filesystem.
- Terminate TLS at a trusted reverse proxy and configure only its CIDRs/hop
  count. Secure cookies are mandatory on HTTPS deployments.
- Keep release providers and download clients on networks with the minimum
  required egress. Their responses remain untrusted even when authenticated.
- Back up before migration, verify the manifest checksum, rehearse restore on a
  separate path and retain the prior image digest.

## Release gate

Before release, CI must pass unit/database/integration tests, frontend checks,
dependency audit, immutable container builds for both architectures, SBOM and
provenance generation. An operator must additionally validate login, library
scoping, one request-to-import flow, Kobo token rotation/sync, readiness,
maintenance status and restore rehearsal on the candidate image.
