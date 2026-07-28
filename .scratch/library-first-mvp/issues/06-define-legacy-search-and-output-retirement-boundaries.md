Type: grilling
Status: resolved
Blocked by: 01, 03

# Define legacy search and output retirement boundaries

## Question

Specify the MVP boundary for legacy download-machine controls so the later implementation can remove the right UI and code safely.

Direct search is unavailable in the UI for every user, while an environment-level operator override remains dormant for future work. Normal users do not configure delivery preferences, output modes, per-user destinations, or metadata providers; browser auto-download is not part of the library model. Determine the exact routes, controls, APIs, and settings keys affected by these rules, including what remains admin-only versus what is deleted. BookFlow is greenfield: no compatibility or data migration path is required.

## Answer

Direct search is removed entirely. There is no standalone search route or API, environment/operator override, `SEARCH_MODE` choice, direct-mode filter/query builder, or direct-search onboarding/configuration path. The legacy direct-search UI and its tests are deleted rather than hidden. `Add New` retains its metadata-provider-backed Book lookup because it adds a canonical Book to a Library; it is not direct release search.

Release discovery remains strictly Book-scoped. A download-capable user may open `Find release` for a Book and queue a selected release using the Book-derived query. An administrator has the same workflow plus an editable custom-query override inside that Book's release modal only. There is no global release-search entry point, and a download-capable user cannot edit the query or use an override.

Remove the per-user search-preference model: its search-preferences API and user override keys (`SEARCH_MODE`, default release sources, combined-search flags, and metadata-provider selections), together with the corresponding self-settings and administrator user-editing controls. Metadata-provider credentials, enabled providers, release-source configuration, and instance default behavior remain administrator-only operational configuration.

Remove generic output-mode behavior, browser auto-download, and all per-user delivery/output destinations and overrides. In particular, `BOOKS_OUTPUT_MODE` and its email, Booklore, browser-download, and per-user destination branches are not retained as alternatives. Administrators retain only the instance-level storage/destination configuration required to run shared Downloads. Users access completed Files through explicit library downloads or the separate Send to Kindle action; Kindle delivery is never a generic Download output mode.
