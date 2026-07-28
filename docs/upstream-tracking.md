# Upstream Tracking

This fork is intentionally maintained independently of `calibrain/bookflow`.
Upstream changes are assessed and integrated deliberately; they are never
silently selected by a Docker image tag.

## Baseline snapshot

The current planning baseline (26 July 2026) is:

| Item | SHA / value |
| --- | --- |
| Fork HEAD | `7bfa970` |
| Upstream HEAD | `00f3fa5` |
| Merge base | `28969ac` |
| Divergence | 85 fork-only commits; 9 upstream-only commits |

## Priority review queue

| Upstream SHA | Classification | Disposition | Required evidence |
| --- | --- | --- | --- |
| `81a057c` | OIDC/JWKS hardening | Pending selective integration or equivalent fork implementation | Authentication and OIDC tests |
| `8eb9bd5` | Python image digest | Pending review against the fork's Docker build | Image build and deployment-pin verification |
| `91b1064` | Part-number fix | Pending selective integration | Affected parsing tests |

The remaining upstream-only commits must be classified individually before a
merge. Dependency updates and TypeScript 7 belong in a separate dependency PR
with the complete build, typecheck, and test matrix. The expected conflict
areas are `docs/environment-variables.md`, `SelfSettingsModal.tsx`, and
`useUsersFetch.ts`.

## Monthly procedure

1. Fetch upstream and record its HEAD, merge base, and ahead/behind counts.
2. Add every candidate SHA, classification, disposition, reason, and test
   evidence to this document or its linked PR.
3. Cherry-pick or manually reimplement only reviewed changes on an
   `upstream-sync/YYYY-MM` branch.
4. Run the relevant test matrix and publish a new fork image digest only after
   review.
5. Update deployment `.env` files to that digest as a separate, reversible
   operational change.
