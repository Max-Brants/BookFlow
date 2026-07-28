Type: prototype
Status: resolved
Blocked by:

# Design the persistent library app shell

## Question

Create a concrete, low-fidelity prototype for the authenticated library-first shell, taking Sonarr only as interaction inspiration rather than a visual template.

Settle the persistent desktop sidebar and collapsed narrow-screen behavior; Library, Activity, and Settings destinations with no nested hierarchy; `/library` as the default authenticated route; and Search as a modal entry point rather than a page. The shell must accommodate the existing activity surface without losing its state while the user navigates. Link the prototype from the resolution and record the responsive and route interaction contract it validates.

## Answer

The library-first shell uses the existing top bar and Activity surface rather than adding a parallel app frame. `/library` is the default authenticated route.

On desktop, a persistent left sidebar carries `Library`, `Add New`, and `Settings`, in that order from the top. `Add New` opens the book-add modal; it is not a route and deliberately avoids the technical term "Search." The existing Activity control and stateful right-side Activity sidebar remain unchanged: Activity is neither a sidebar destination nor a full page.

On narrow screens, the left navigation is hidden behind a standard top-left menu button which opens the same left drawer. It must not be replaced with bottom navigation, an icon rail, or a second header. Navigation must leave the Activity sidebar's state intact.

The standalone in-app prototype was discarded: because it mounted inside the present shell, it created a duplicate header and Activity control that made it misleading. For this map, later UI decisions should be worked through against the existing UI or by discussion, not by a parallel app-shell prototype.
