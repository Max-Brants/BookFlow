Type: prototype
Status: resolved
Blocked by: 04, 06, 07

# Author browse MVP (Hardcover author endpoint, suggestions only)

## Question

This is the **last ticket** in the map, per the grilling session: a basic MVP for author-browse showing a small list of books by an author, with "books you haven't added" highlighted. Built last; refined later (out of scope for this effort).

Per the grilling session:

- Uses **Hardcover's author endpoint** to fetch an author's bibliography. The architectural survey surfaces that Hardcover is one of the pluggable metadata providers (`bookflow/metadata_providers/`, registered with `@register_provider`). Decide which endpoint to call and what the response shape is.
- Lives at a route (per #07: probably `/authors/:authorId` or a subview of `/library`). Pick one.
- Shows: author name + small list of their works. Each row shows: title, year, "In my library" badge if applicable, "Add to library" button if not.
- The grilling session said "we would use hardcover's author endpoint and show a small list" — scope is intentionally minimal. No pagination, no search within the list, no other-provider support. Just Hardcover. Refinements later.

Open questions this ticket must resolve:

- **Hardcover-specific:**
  - What's the right endpoint to call? (`/authors/{id}/works` or similar). Read the existing Hardcover provider in `bookflow/metadata_providers/` for the auth and base-URL setup.
  - Author ID source: where does the user click "browse this author" from? Likely from a book detail page's author field. Confirm path.
- **Limit and sort:** how many works to show? Default 10 most recent by year desc? Top N by some popularity metric?
- **Books-I-own rendering** — the existing `/api/library/books?author=...` (from #04) returns a user's library filtered by author. Cross-reference the Hardcover-bibliography response with the user's library to render "In my library" badges. Confirm this is the right way (vs. a separate endpoint that returns "Hardcover bibliography plus per-row `in_my_library` flag").

Architectural-survey constraints:

- Mock data acceptable for prototype, real API hit if it's straightforward — pick what lands fastest.
- Route is implemented at the same place #07/#08/#10 set up their routes.

Verification: `make frontend-typecheck` passes; the page renders against mock data without crashing; clicking "Add to library" on a not-in-library work launches the same flow as the search-results Add button.

## Outcome of this ticket

Prototype React code on the feature branch. After this ticket, the map is done — the way to the destination is clear.

## Comments

- Parked for now at the user's request. This is deferred rather than ruled out of scope.

## Answer

Author browse is deferred completely and is outside this Library map's MVP destination. It is not a prerequisite for the library, book-detail, or search-to-library workflow. A future effort may chart it from scratch if it becomes a priority.
