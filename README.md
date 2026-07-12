# צירי תנועה · Traffic Arteries

Find the shortest paths between two places across a network of bidirectional
routes. Given routes like `[A, B, C, D]`, `[C, M, N, G, E, R]`, `[E, J, K, L, A]`,
the app builds an undirected graph and returns the **top 3 shortest paths**
between any two points (e.g. `K → M ⇒ [K, J, E, G, N, M]`), or reports that no
route exists.

Full-stack **Django REST Framework + React**, with a **filesystem JSON store**
(no SQL). The UI is fully **Hebrew / RTL**. The store starts empty — routes are
added through the editor.

## Architecture

```
backend/                     Django + DRF (function views)
  api/graph/                 graph build + merge-minimising route search (the core)
  api/db.py                  filesystem DB: routes.json (truth) -> edge_routes.json (derived)
  api/views.py / urls.py     @api_view endpoints
  data/                      routes.json + edge_routes.json (generated on first run)
frontend/                    React + Vite (raw CSS)
  src/pages/                 HomePage, RoutesPage, BrainPage
  src/components/            NavBar, Autocomplete, PathResults, RouteEditor, GraphView, ...
```

### How it works

- **routes.json** is the source of truth (a list of routes; each a list of place names).
- On every save it is validated and **edge_routes.json** — the derived graph, each
  edge tagged with the authored routes that use it — is regenerated with an atomic
  write, so the graph (adjacency reconstructed from the edges) loads straight from
  disk.
- **Route search** (`api/graph/`) finds the route that **rides one authored route
  as far as possible** — the highest _concentration_ (Herfindahl) score over how
  the route's length is split across the authored routes it stitches. Since that
  objective is non-additive, it generates candidate corridors (one biased toward
  each artery) and scores each exactly, returning up to 3 distinct alternatives
  best-first. Whether "length" counts every hop or only crossroads (`degree > 2`)
  is a togglable flag (`graph.LengthMode`).

## API

| Method | Path           | Purpose                                           |
| ------ | -------------- | ------------------------------------------------- |
| GET    | `/api/places/` | all place names (autocomplete)                    |
| GET    | `/api/routes/` | current routes list                               |
| PUT    | `/api/routes/` | replace routes, regenerate graph (400 on invalid) |
| GET    | `/api/graph/`  | `{nodes, links}` for the graph view               |
| POST   | `/api/path/`   | `{start, end}` → `{paths: [...], meta: [...]}`    |

## Running locally

**Backend** (Python 3.11+):

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py runserver 8000
```

**Frontend** (Node 18+), in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` to Django on
port 8000, so no CORS setup is needed.

## Tests

Algorithm correctness (anchored on the spec's own `K → M` example):

```bash
cd backend
.venv/bin/python manage.py test api
```

## Pages

- **צירים** — search two points (autocomplete) and get the top 3 routes.
- **עריכת צירים** — build/edit routes as chains of place chips; save rebuilds the graph.
- **הצצה למוח** — interactive, read-only force-directed view of the whole network.
