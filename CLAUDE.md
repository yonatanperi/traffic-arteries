# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

צירי תנועה (Traffic Arteries): given a set of authored routes (each a list of
place names, walked as bidirectional chains), find the top-3 best routes
between two places. Full-stack Django REST Framework + React, with a
filesystem JSON store (no SQL). The UI is Hebrew/RTL.

**The routing objective is concentration, not shortest-path**, gated by a hard
priority tier. Priority is stated as **marks**: an authored route (or any node of a
branched one) carries `marks`, a list of `{from, to, priority}` ranges (inclusive,
`from < to`, disjoint, `priority` `1..3`) over that node's **frame** — its own
`places` followed by everything *downstream* of it, so a mark can start in a head
and end in the shared tail. (`from` must sit in the node's own places; only `to` may
reach past them. The frame is unambiguous because heads branch upstream but every
node has exactly one way down to the destination.) An unmarked stretch rides at `0`
(best). **A mark only bites when a result rides the marked stretch *whole*** —
clipping it, even by one edge, costs nothing. Where the line falls between "brushed
past it" and "rode it" is therefore drawn by the author rather than guessed from a
length constant (there used to be a `TIER_EXEMPT_LENGTH` heuristic; marks replaced
it). Which node *stores* a mark is what scopes it: one on a tree's shared tail rates
every corridor that rides it; one on a head rates only the corridors below that head.
Two levels judge a route's quality (and pick the single best result):

1. **Tier** — the worst priority among the sub-routes a route actually *rides*: the
   `max` over the runs of its max-HHI decomposition (the same chips the UI shows),
   each run's priority being the worst mark that run completes. A route that
   completes no bad mark beats one whose concentrated corridor completes one
   **however long the detour**. Note this is assignment-dependent: a road co-served
   by a good route escapes the downgrade only when riding it *as* the good route is
   at least as concentrated — otherwise the concentrated way to ride it is the
   marked one. (`Graph.edge_priority`, the per-edge best, is a separate, deliberately
   pessimistic thing — an edge merely *inside* a mark reads as rated — that the
   generators use to hunt for a corridor avoiding the mark entirely.)
2. **Concentration** — within a tier, a Herfindahl (HHI) score over how the route's
   length splits across the authored routes it stitches. Not fewest hops, not fewest
   merges. `Route.hhi` is deliberately **priority-free**: priority is the tier's job,
   so re-rating an artery must never move a route's score (or the match % built on
   it). The priority weights `w(p) = 1 - 0.2p` still exist inside
   `concentration.evaluate` as the *tie-break* over equally concentrated credit
   assignments — they decide which artery gets credit for a shared edge (and so
   which reading completes a mark), and hence the sub-route chips and the tier.
   The credit-assignment DP keys its state on `(route, run start edge)` rather than
   `(route, accumulated length)` precisely so a run's *node span* — and therefore
   whether it completes a mark — is known at the moment the run closes.
   Consequence: with `PriorityMode.HARD_TIER` off, the ranking is fully
   priority-blind, since the arena is then the only priority mechanism left.

Both are non-additive, so they can't be optimized inside a single shortest-path
search; `backend/api/graph/routing.py` generates a pool of candidate corridors
(one biased toward each authored route, one confined to each priority tier) and
scores each exactly (`concentration.py`). The pool is sorted **once** by
concentration (`RouteFinder.rank_candidates`), then the top-3 are assembled by a
**priority-arena** walk (`RouteFinder.select_diverse`): round one admits only
tier-0 routes, so the headline result is the best tier-0 corridor; after filling
slot `i` with a route of priority `X` the next round admits `priority ≤ max(i + 1,
X + 1)`. The `X + 1` term lets a deeper pick open the arena beyond itself; the
`i + 1` (slot-index) term widens the arena by at least one tier per slot regardless,
so slot `i` can always reach tier `i` even after a run of same-tier picks. So a
*concentrated* higher-tier corridor surfaces as an alternative once its slot is deep
enough or a prior pick has opened the tier — whichever comes first. Splitting
rank-once from select-cheaply also lets `views.path` select twice over the one
pool — natural, and compromised-free — without a second sort. Two static flags
exist to experiment with: `LengthMode.CROSSROADS_ONLY` and `PriorityMode.HARD_TIER`
(both in `concentration.py`; flipping `HARD_TIER` off drops the arena for a plain
concentration-first pick).

Priority **ranks, it never filters** — the pool stays complete, merely
arena-ordered, so a concentrated tier>0 corridor appears as a real alternative
(and, when the best tier holds only one corridor, the next slots still fall
through to worse tiers) rather than the result list collapsing to one route.
Because a longer or lower-concentration route can therefore appear above a shorter
one, the tier is returned in the API meta and **must** stay visible in the UI, or
it reads as a bug.

Read the module docstrings in `backend/api/graph/` (`core.py`, `search.py`,
`concentration.py`, `routing.py`) before touching the algorithm — each lays
out the reasoning in detail and is more current than the README's "shortest
path" framing, which describes an earlier version.

## Commands

**Backend** (Python 3.11+):
```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py runserver 8000
```

**Frontend** (Node 18+):
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000 (see vite.config.js)
npm run build
```

**Tests** (backend only; no frontend test suite exists):
```bash
cd backend
.venv/bin/python manage.py test api
.venv/bin/python manage.py test api.tests.KShortestPathsTests.test_spec_example_k_to_m  # single test
```

Tests are algorithm-focused (`backend/api/tests.py`), anchored on the spec's
own worked example (routes `[A,B,C,D]`, `[C,M,N,G,E,R]`, `[E,J,K,L,A]`; `K → M`
must yield `[K, J, E, G, N, M]`).

**Console route lookup** — `find_route` (`backend/api/management/commands/find_route.py`)
runs the exact same pipeline as `POST /api/path/`/the home page search
(`rank_candidates` → `select_diverse` twice → top-3), without going through the
UI or HTTP. Use it to inspect a route's stats (match %, priority tier, merged
sub-routes) straight from the CLI:
```bash
cd backend
.venv/bin/python manage.py find_route "<start>" "<end>"
.venv/bin/python manage.py find_route "<start>" "<end>" --via "<stop1>" "<stop2>"
.venv/bin/python manage.py find_route "<start>" "<end>" --json  # raw {paths, meta, compromisedDetour}
```

## Architecture

```
backend/
  api/graph/          the core algorithm — pure Python, no Django dependency
    core.py            Graph: undirected adjacency list; each edge tagged with
                        which authored routes (by index) traverse it
    search.py          single-route generator strategies (MinMergeStrategy,
                        WaypointStrategy) over (node, active_route) state
    concentration.py   evaluate(): exact HHI scoring of a stop chain via a
                        chain-DP over route-credit assignments
    routing.py         RouteFinder: generates + scores + sorts candidate chains
                        once (rank_candidates), then a priority-arena greedy pick
                        of up to k non-overlapping ones (select_diverse)
  api/db.py            filesystem "database" — see below
  api/views.py         DRF function views (@api_view + Response), thin
  api/urls.py           /api/places/, /api/routes/, /api/compromised/, /api/graph/, /api/path/
  data/                routes.json (source of truth) + edge_routes.json
                        (derived) + compromised.json, gitignored contents

frontend/src/
  pages/               HomePage (search), RoutesPage (edit routes + compromised
                        destinations), BrainPage (read-only force-directed graph)
  components/
    layout/            Page (page fade-in wrapper), NavBar (top segmented nav)
    ui/                generic, page-agnostic primitives — see below
    shared/             cross-domain but app-specific: RouteChain family
    home/, routes/, brain/  components used by exactly one page/domain
  api/client.js        thin fetch wrappers, all through /api (no base URL/CORS
                        needed — Vite dev proxy handles it)
  hooks/, utils/        cross-page hooks and graph metrics helpers
  styles/global.css     design tokens (colors, spacing, radii) + shared base
                        classes (.btn variants, .card) — see below
```

### Frontend building blocks — check here before writing a new component

Every page is built from the same small vocabulary of primitives and shared
CSS. **Before adding a new component or class, check this list and
`components/ui/` — a `Pill`, chip, empty state, loader, modal, icon button,
etc. almost certainly already exists.**

`components/ui/` (generic, reused across pages):
- `Autocomplete` — accessible combobox; used by every place-picker (home
  search, route editor add-flow, brain toolbar). Don't build a second one.
- `IconButton` — the only button used for icon-only actions (sizes `sm/md/lg`,
  `danger` variant).
- `Pill` — the generic chip/badge (`as="button"|"span"`, `size`, `tone`
  props); `RemovableChip` extends it with a delete affordance (dnd-kit-aware,
  used for the draggable route-chain stops).
- `EditableList` / `EditableGroupRow` — the list/"add row"/"remove row"
  scaffolding both the route editor and compromised-destinations editor build
  on.
- `FloatingPanel` / `FloatingPanelList[Item]` — the floating card used by the
  brain page's node detail and insights panels.
- `Select` — the generic dropdown (a native `<select>` in design tokens), for a
  short *closed* set of values. `Autocomplete` is the one for searching a long open
  list of places; don't confuse the two. (Currently unused — the route-priority
  picker it was built for became `PriorityMarkPopover`.)
- `ConfirmModal`, `EmptyState`, `LoaderLayout`, `PageHeader`, `SegmentedControl` /
  `SegmentedNav` (tabs vs. router-linked nav), `SwapButton` (start/end swap,
  pairs with `useOriginDestination`).
- `icons/icons.jsx` — every icon as an inline SVG function component
  (`IconPlus`, `IconTrash`, `IconClose`, `IconSwap`, `IconAlert`,
  `IconNetwork`, `IconRoute`, `IconSearch`, `IconFocus`, `IconFit`,
  `IconReset`, `IconPlay`/`IconPause`, `IconDownload`, `IconBulb`,
  `IconFilter`, `IconHub`, `IconChevron`, `IconCheck`, `IconCopy`,
  `IconOrigin`/`IconDestination`, `IconCompass`, …). Add new icons here in the
  same style — never pull in an icon library.

`components/shared/RouteChain/`:
- `RouteChain` — the canonical *read-only* rendering of a stop chain (pills +
  chevron connectors); used for path results.
- `EditableRouteChain` — the drag-to-reorder (dnd-kit) editable version used
  in the route editor. It also owns **stop picking**: `selectionMode` swaps the
  reorder gesture for picking stops (press-and-drag, or tap one end then the other),
  reporting each as `onSelectStop(phase, {key, index}, at)` — a chain reports *which
  of its stops* was picked and nothing more, because a gesture may start in one
  segment and end in another. `ranges` paints stretches onto the pills and `selected`
  the live pick. All of it is deliberately anonymous — the editor's priority marks
  are what fill it; the chain only knows "these stops belong together". `BranchedChain`
  is what resolves a pair of picks into a mark (`resolveRange`) and cuts marks into
  per-segment pieces to paint (`markPieces`/`framePieces`).

Cross-page hooks (`hooks/`): `useAutoSave` (debounced/validated persistence
with save-ordering, used by both RoutesPage editors) and
`useOriginDestination` (controlled start/end pair + swap, used by the home
search form and the brain toolbar's path mode) — reuse rather than
re-deriving this state logic per page.

`utils/`: `graphMetrics.js` (pure helpers over `{nodes, links}` for the brain
view — degree, components, etc.), `placeTypes.js` (classifies a place name
into junction/base/interchange by naming convention, e.g. `"צ. "` prefix =
junction) — the classification regexes are the single source of truth for
place "type" anywhere in the UI — and `priorities.js` (route priority is `0..3`
on the wire but Hebrew letters `א׳..ד׳` in the UI; this is the only place the two
vocabularies meet, so never hardcode a letter in a component). `branches.js` mirrors
the backend's `expand_route` **and** owns every mark edit — `setMark` (overlap-trimming,
so re-marking the middle of a stretch splits it), `removeMark`, the frame arithmetic
(`nodeFrame`, `framePieces`, `resolveRange`, `markPieces`), and the index remapping
every structural edit needs (`patchNodePlaces`, `branchAt`, `removeBranch`,
`reverseRoute`). Its invariant, and what its edits are tested against: a mark keeps
naming **the same road** across every structural edit.

`styles/global.css` defines the whole design-token vocabulary (`--bg`,
`--surface*`, `--accent*`, `--text*`, `--r-*` radii, `--s-*` spacing,
`--shadow-*`) plus shared base classes (`.btn`, `.btn-primary`, `.btn-ghost`,
`.btn-danger`, `.btn-dashed`, `.card`). Component-level `.css` files (one per
component, colocated) build on these tokens rather than hardcoding colors —
follow that pattern for new components instead of introducing new one-off
values. The theme is dark-only (no light-mode branch to maintain).

### The filesystem store (`backend/api/db.py`)

- **`routes.json`** is the source of truth: routes exactly as authored, each
  `{"places": [...], "marks": [...]}`, optionally with `"branches"` (a converging
  tree of heads — see `expand_route`). Every node (root or head) may carry its own
  `marks`. Two pre-marks shapes still load and are upgraded on the next save
  (`upgrade_node`): a bare `[...]` list, and a `"priority": 0..3` field, which
  resolves down the spine exactly as it used to and becomes one mark per *leaf* over
  that leaf's whole frame — i.e. the corridor the field always rated. Marking the
  leaves (not every node) is what keeps the upgrade faithful, and what lets a
  one-stop head keep its rating: it owns no edge, but its corridor does. `expand_route` returns `{"places", "marks"}` per subroute,
  where each mark has become a `(start place, end place, priority)` triple — a leaf
  chain concatenates several nodes and the derived graph is built from *filled*
  chains, so only names line up across both. Marks are deliberately **not** copied
  into the derived graph file — `load_graph()` re-attaches them from here, so this
  stays the one place they live. There is no priority picker anywhere in the
  editor: a rating applies to a range, so it is stated by picking the two ends of a
  stretch on the chain (the `⚑` toggle on each route card) and choosing a priority in
  `PriorityMarkPopover`. A range may run from a head *downstream* into the shared
  tail, never across to a sibling — nothing rides two sibling heads, so a pair of
  stops on both names no road. **No corridor may name the same place twice**
  (`Database._reject_repeats`, mirrored by `isRouteValid`/`corridorStops` in
  `branches.js`, which also keeps the add dropdown from offering one): the graph
  keys its nodes by place, so a repeat collapses into a single node and the stops
  between the two occurrences become a loop the router cuts — yielding a corridor
  that is missing its own middle while still riding one authored route, i.e. at a
  *perfect* concentration score, so it ranks first. Checked over the whole frame,
  since a head repeating one of its shared tail's stops is the same bug.
- **`edge_routes.json`** is derived and rebuilt on every save:
  `[[place_a, place_b, [authored route indices]], ...]`. The adjacency is
  reconstructed from these edges — there's no separate adjacency file. This is
  what `Graph.from_edge_routes` loads.
- **`edge_routes.fingerprint.json`** guards that derived file against drift:
  `{version, routes}` — `DERIVATION_VERSION` plus a digest of `routes.json` as
  stored. Every load checks it (`Database._derived_is_stale`) and rebuilds on any
  mismatch, so a `routes.json` changed outside `save_routes` (seeded, restored,
  hand-edited) or a change to the derivation itself can't leave the router riding
  edges no route asserts. **Bump `DERIVATION_VERSION` whenever a change to
  `expand_route` / `fill_missing_destinations` / `Graph.from_routes` would derive
  different edges from the same routes** — that's what makes existing stores
  rebuild instead of serving output of logic that no longer exists. Tampering with
  the derived file alone is deliberately *not* detected (see
  `DerivedGraphFreshnessTests`); it fingerprints the input, not the output.
- Before building the graph, routes pass through
  `Database.fill_missing_destinations`: if one route hops directly `D → B`
  while another spells out `D, E, F, B`, the skipped stops get spliced back in
  (bounded by `CONFIRMED_GAP`/`LAZY_GAP`, see the method's docstring for the
  reasoning) so the graph never asserts an edge that doesn't really exist.
  `routes.json` always keeps the user's literal input; only the derived graph
  sees the filled version.
- **`compromised.json`** holds groups of temporarily-unavailable destinations.
  It's filtered at read time (`load_routable_graph`) for routing/place-picking;
  it never mutates `routes.json`/`edge_routes.json`. The `/api/graph/` (brain
  view) endpoint shows the full network with compromised nodes flagged rather
  than hidden.
- All writes are atomic (temp file + `os.replace`).
- This filesystem-store and compromised-destinations layer is not described in
  README.md — it was added after the README was last updated.

### Route search flow (a request through the system)

1. `POST /api/path/` with `{start, end, via}` → `views.path`.
2. `database.load_graph()` — the **full** derived graph (compromised places
   included, so the detour report can see what the natural best would have used),
   plus `database.compromised_places()` as the exclusion set.
3. `finder.rank_candidates(start, end, via=via)` — the single expensive step
   (generate + score + one sort):
   - No `via`: `MinMergeStrategy` from both directions, biased once per authored
     route (`prefer_route_penalty`) plus an edge-penalty diversity backfill, to
     build the candidate pool.
   - With `via`: `WaypointStrategy` over optimized stop orderings (bounded by
     `MAX_OPTIMIZED_WAYPOINTS`; a small TSP over hop-count heuristics). Its *hard*
     no-revisit rule is scoped to the **leg** (the stretch between consecutive
     required stops), not the whole route: a required stop may be a dead end, and
     the only way out is back the way you came. Demanding one globally simple path
     makes every degree-1 place unroutable as a `via` and rejects many ordinary
     via-queries outright; a loop *inside* a leg is still banned. Retracing across
     a leg boundary is nevertheless a **last resort, not a free move**: revisits
     are counted and minimised *lexicographically first*, ahead of transfers, hops
     and every penalty in the map, so a globally simple route always wins when one
     exists and a forced one doubles back as little as the road allows. Backing out
     of a junction you could have driven straight through reads as a bug however
     well the route scores — which is why that ordering outranks even
     `avoid_priority_penalty`'s ban.
   - Each candidate is scored exactly by `concentration.evaluate` (the HHI) and
     the pool is sorted once, concentration-first.
   - Then one **refinement round** (`_artery_pair_chains`): a single-artery bias
     charges the same `TRANSFER_WEIGHT` for an off-artery edge as for a route
     transfer, so it fills everything around its stint with the *shortest* filler,
     not the most concentrated one — and a corridor whose optimum is two long
     arteries in sequence is proposed by no single-artery pass at all. Stacking two
     arteries' penalties finds it; the pairs tried are the dominant arteries of the
     best `PAIR_SEED_ARTERIES` distinct-artery candidates, which is why this can
     only run *after* round one is scored. The new chains are scored and merged
     into the existing pool (`_score` + one re-sort), never re-solving round one —
     sound because `q`'s length reference is the **network's** `C_min`, not the
     pool's, so a route's score doesn't depend on what else is in the pool.
4. `finder.select_diverse(ranked, k=None, exclude=…)` — a cheap priority-arena
   greedy pick (neither near-duplicates by `max_overlap` nor excessive detours by
   `max_stretch`), run **twice** over the one ranked pool: once natural (the
   `compromisedDetour` = compromised places the natural top-`TOP_N` would use) and
   once with `exclude=compromised` (the results actually shown). The `TOP_N` (=3)
   truncation is the only place the result count lives — never a magic `k`.
5. Response carries `paths` (stop chains), `meta` (per-result ranking score
   `Route.q` as `match` — the HHI tempered by a length term (crossroad distance,
   or plain hop count, per `LengthMode.CROSSROADS_ONLY` — the same unit
   `evaluate()` sums for the HHI itself), i.e.
   the very quantity the results are ordered and floored by, so the shown % never
   contradicts the shown order; raw `hhi` stays internal and is what the per-run
   `share`s square back to — the priority tier, and which authored routes —
   labeled by their endpoints — each result merges), and `compromisedDetour`.
   The match % is **only comparable within one query**: its length term divides by
   `C_min`, the shortest a route through *these* required stops could be, so adding
   a `via` raises the floor and the identical corridor reports a higher %. Two
   queries' percentages say nothing about each other.

### Frontend/backend contract notes

- No CORS setup: the Vite dev server proxies `/api` to Django on `:8000`
  (`frontend/vite.config.js`); everything shares an origin in dev.
- `frontend/src/api/client.js` is the only place that talks to the backend —
  route through it rather than calling `fetch` directly from components.
- Hebrew strings (validation errors, UI copy) live server- and client-side;
  match the existing tone/RTL conventions rather than introducing English.

## Product/UI conventions (from `tasks/tweeks.md`)

These were explicit product decisions — don't regress them:
- Terminology is "מקומות" (places), not "ערים" (cities).
- No logo/gradient styling — deliberately non-generic-AI look, raw CSS only
  (no CSS frameworks).
- Icons are simple inline SVGs (see `components/ui/icons/`), not an icon
  font/library.
- The dropdown/autocomplete selector from the home page is reused in the route
  editor's "add" flow rather than reimplemented.
