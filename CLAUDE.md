# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

צירי תנועה (Traffic Arteries): given a set of authored routes (each a list of
place names, walked as bidirectional chains), find the top-3 best routes
between two places. Full-stack Django REST Framework + React, with a
filesystem JSON store (no SQL). The UI is Hebrew/RTL.

**The routing objective is concentration, not shortest-path**, gated by a hard
priority tier. Each authored route carries a `priority` (int `0..3`, `0` = best).
Ranking is lexicographic:

1. **Tier** — the worst priority a route is *forced* to touch (per-edge min of the
   routes on it, maxed along the chain). A route that stays on well-rated arteries
   beats one that dips into a badly-rated one **however long the detour**.
2. **Concentration** — within a tier, a priority-weighted Herfindahl (HHI) score
   over how the route's length splits across the authored routes it stitches
   (`w(p) = 1 - 0.2p`). Not fewest hops, not fewest merges.

Both are non-additive, so they can't be optimized inside a single shortest-path
search; `backend/api/graph/routing.py` generates a pool of candidate corridors
(one biased toward each authored route, one confined to each priority tier) and
scores each exactly (`concentration.py`) before picking the top-3 diverse results.
Two static flags exist to experiment with: `LengthMode.CROSSROADS_ONLY` and
`PriorityMode.HARD_TIER` (both in `concentration.py`).

Priority **ranks, it never filters** — the candidate list stays complete, merely
tier-ordered, so alternatives fall through to worse tiers rather than the result
list collapsing to one route. Because a longer route can therefore outrank a
shorter one, the tier is returned in the API meta and **must** stay visible in the
UI, or it reads as a bug.

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
    routing.py         RouteFinder: generates diverse candidate chains, scores
                        them, and greedily selects up to k non-overlapping ones
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
  short *closed* set of values (e.g. the route-priority picker). `Autocomplete` is
  the one for searching a long open list of places; don't confuse the two.
- `ConfirmModal`, `EmptyState`, `Loader`, `PageHeader`, `SegmentedControl` /
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
  in the route editor.

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
vocabularies meet, so never hardcode a letter in a component).

`styles/global.css` defines the whole design-token vocabulary (`--bg`,
`--surface*`, `--accent*`, `--text*`, `--r-*` radii, `--s-*` spacing,
`--shadow-*`) plus shared base classes (`.btn`, `.btn-primary`, `.btn-ghost`,
`.btn-danger`, `.btn-dashed`, `.card`). Component-level `.css` files (one per
component, colocated) build on these tokens rather than hardcoding colors —
follow that pattern for new components instead of introducing new one-off
values. The theme is dark-only (no light-mode branch to maintain).

### The filesystem store (`backend/api/db.py`)

- **`routes.json`** is the source of truth: routes exactly as authored, each
  `{"places": [...], "priority": 0..3}`. A bare `[...]` list (the pre-priority
  shape) still loads, as priority 0, and is upgraded on the next save. Priority is
  deliberately **not** copied into the derived graph file — `load_graph()`
  re-attaches it from here, so this stays the one place it lives.
- **`edge_routes.json`** is derived and rebuilt on every save:
  `[[place_a, place_b, [authored route indices]], ...]`. The adjacency is
  reconstructed from these edges — there's no separate adjacency file. This is
  what `Graph.from_edge_routes` loads.
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
2. `database.load_routable_graph()` — the derived graph minus compromised places.
3. `RouteFinder(graph).find_routes(start, end, k=3, via=via)`:
   - No `via`: `routing.py` runs `MinMergeStrategy` from both directions,
     biased once per authored route (`prefer_route_penalty`) plus an
     edge-penalty diversity backfill, to build a candidate pool.
   - With `via`: `WaypointStrategy` over optimized stop orderings (bounded by
     `MAX_OPTIMIZED_WAYPOINTS`; a small TSP over hop-count heuristics).
   - Every candidate is scored exactly by `concentration.evaluate` (the HHI),
     then `_select_diverse` greedily keeps up to `k` results that are neither
     near-duplicates (`max_overlap`) nor excessive detours (`max_stretch`).
4. Response carries `paths` (stop chains) and `meta` (per-result HHI as
   `match`, and which authored routes — labeled by their endpoints — each
   result merges).

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
