Type: task
Status: resolved
Blocked by: 06, 07, 08, 14

# Implement the validated book detail UI

## Question

Promote the validated contract from [Book detail page UI (with per-format downloads and Send-to-Kindle)](08-book-detail-page-ui.md) into production-quality code on a new feature branch. Do not merge or polish the prototype branch directly.

Use `library/08-book-detail-prototype-reconciled` at `dfc2b4e` as the visual and interaction reference, then reimplement it against a branch containing #14's multi-file release contract. Production work includes the nested `/library/:bookId` route and live handlers for per-format download, exact-file download, release-atomic unlink, Send-to-Kindle, settings, and Find Releases. Preserve #08's two-level information hierarchy:

- Available formats: newest completed File per format by `downloaded_at`, then `history_id`, with compact source/date provenance.
- Releases: collapsed advanced `task_id` groups, exact-file download, and a clearly release-wide unlink action.

The prototype's info-toast mutation stubs, artificial loading latency, and old tracker state must not be carried forward. The implementation must use the app's existing error/loading patterns and keep the activity sidebar accessible per #07.

Verification: `make checks` passes; seed or fixture data covers multi-file releases; `/library/1`, `/library/2`, and `/library/3` exercise the available-formats, empty, and in-flight paths; live mutations hit their #04/#06 endpoints.

## Answer

Implemented on `feature/library-book-detail` in commits `e7ba378` and `103189d`.

- Nested `/library/:bookId` now renders the production detail page with loading, retry, and shared 403/404 not-in-library states; the activity sidebar remains outside the route.
- Available formats select the newest File per format; the collapsed Releases view groups Files by `task_id`, serves exact files through a new `history_id` download selector, and exposes release-wide unlink only for the current user's linked releases.
- Find Releases opens the existing modal, auto-opening for file-less Books when `LIBRARY_AUTO_FIND_RELEASES` is true. Send-to-Kindle defaults to EPUB and permits only EPUB choices.
- Added route coverage for exact-file download and cross-book rejection. `npm run typecheck`, `npm run test:unit` (120), `uv run pytest tests/core/test_library_routes.py -q` (24), and `make python-checks` pass. `make checks` is blocked by five pre-existing frontend lint failures in `useUsersFetch.ts` and `SelfSettingsModal.tsx`.
