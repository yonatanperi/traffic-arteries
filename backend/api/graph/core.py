"""The :class:`Graph` itself: an undirected graph of place names.

Routes are chains of place names. Consecutive places in a route form a
bidirectional edge. From those edges we build an undirected graph stored as an
adjacency list. A :class:`Graph` can be constructed straight from a persisted
adjacency dict, or derived from routes with :meth:`Graph.from_routes`.

Every edge also remembers **which authored routes traverse it** (by index), so
the router can find the route that merges the fewest authored routes rather than
the shortest one. See :mod:`.search`.

An authored route may also carry **priority marks** (``0`` = best … ``3`` = worst),
which is what makes some arteries worth riding more than others. A mark rates one
*stretch* of a route rather than the whole of it, and it only bites when a result
rides that stretch **entirely** — see :func:`~.concentration.ridden_marks`, which
is what every result is rated by. The graph is where marks live, since both the
scorer (:mod:`.concentration`) and the candidate generators (:mod:`.search`) need
them.

A mark reaches the graph as a ``(start place, end place, priority)`` triple rather
than the index range the author drew, because the graph holds edges, not chains —
and the chains it was derived from were *filled* (:meth:`~api.db.Database.
fill_missing_destinations`), so the authored indices no longer line up anyway.
Names do, and they are enough: a route's chain is a simple path, so a stretch of a
result that stays on that route's edges and holds both endpoint names necessarily
holds the whole marked stretch between them.
"""

# Authored-route priority: 0 is best, WORST_PRIORITY is worst. An unmarked stretch
# (and any edge with no authored-route provenance) is best by default, so a graph
# that knows nothing about priorities behaves exactly as it did before the feature
# existed.
BEST_PRIORITY = 0
WORST_PRIORITY = 3


def edge_key(a, b):
    """Order-independent key for an undirected edge."""
    return (a, b) if a <= b else (b, a)


def path_edges(path):
    """The set of undirected edge keys that make up a path."""
    return {edge_key(a, b) for a, b in zip(path, path[1:])}


def _marks_map(marks):
    """``{route index: ((start, end, priority), ...)}`` from a sequence parallel
    to the routes.

    Best-priority marks are dropped (they say nothing — an unmarked stretch is
    already best), and so are routes left with none, so a graph where nothing is
    rated carries an empty map and every priority lookup short-circuits.
    """
    if not marks:
        return {}
    out = {}
    for index, entries in enumerate(marks):
        rated = tuple(
            (start, end, priority)
            for start, end, priority in (entries or ())
            if priority != BEST_PRIORITY
        )
        if rated:
            out[index] = rated
    return out


class Graph:
    """An undirected graph of places, backed by an adjacency list.

    The adjacency is normalised to ``{place: sorted list of neighbours}``. The
    sorted order is what makes every search deterministic: neighbours are always
    visited in the same sequence, so equal-cost ties resolve the same way.

    ``edge_routes`` maps each :func:`edge_key` to the sorted tuple of authored
    route indices that use it. It is optional: a graph loaded adjacency-only (or
    built without route provenance) simply has no membership, and the router then
    treats every edge as its own route.

    ``route_marks`` maps an authored route index to its priority marks, each a
    ``(start place, end place, priority)`` triple naming a rated stretch of that
    route. Also optional — a route with no marks rides at :data:`BEST_PRIORITY`
    throughout.
    """

    def __init__(self, adjacency, edge_routes=None, route_marks=None):
        """Wrap a raw ``{place: iterable of neighbours}`` mapping.

        Neighbours are de-duplicated and sorted, so passing either a freshly
        built adjacency or one loaded from disk yields the same normalised graph.
        ``edge_routes`` is an optional ``{edge_key: iterable of route indices}``,
        and ``route_marks`` an optional ``{route index: marks}`` (see the class
        docstring).
        """
        self._adjacency = {
            place: sorted(set(neighbours)) for place, neighbours in adjacency.items()
        }
        self._edge_routes = {
            edge_key(*edge): tuple(sorted(set(routes)))
            for edge, routes in (edge_routes or {}).items()
        }
        self._route_marks = dict(route_marks or {})
        # Per-edge mark priorities, derived lazily and only for rated routes —
        # see :meth:`_marked_edges`. Not part of the graph's identity.
        self._marked_edges_cache = {}

    @classmethod
    def from_routes(cls, routes, marks=None):
        """Build a graph from routes (lists of place names).

        Each pair of *consecutive* places in a route becomes an undirected edge,
        tagged with that route's index in ``edge_routes``. Every place that
        appears is guaranteed a node, even if it ends up isolated. Self-loops (a
        place adjacent to itself) are ignored.

        ``marks`` is an optional sequence parallel to ``routes``, each entry that
        route's ``(start, end, priority)`` triples; omit it and every route rides
        at :data:`BEST_PRIORITY`.
        """
        adjacency = {}
        edge_routes = {}

        def ensure(place):
            if place not in adjacency:
                adjacency[place] = set()

        for index, route in enumerate(routes):
            for place in route:
                ensure(place)
            for a, b in zip(route, route[1:]):
                if a == b:
                    continue
                adjacency[a].add(b)
                adjacency[b].add(a)
                edge_routes.setdefault(edge_key(a, b), set()).add(index)

        return cls(adjacency, edge_routes, _marks_map(marks))

    @classmethod
    def from_edge_routes(cls, records, marks=None):
        """Build a graph from persisted ``[[a, b, [route indices]], ...]`` records.

        These records (see :attr:`edge_routes_records`) are the single derived
        representation of the graph: the adjacency is reconstructed from the
        edges. Every connected place appears on at least one edge, so nothing
        routable is lost.

        ``marks`` is an optional sequence indexed by authored route — it is *not*
        part of the derived records, it comes straight from the routes file, which
        stays the single source of truth for it.
        """
        adjacency = {}
        edge_routes = {}
        for a, b, routes in records:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
            edge_routes[edge_key(a, b)] = routes
        return cls(adjacency, edge_routes, _marks_map(marks))

    @property
    def adjacency(self):
        """JSON-friendly adjacency dict (``place -> sorted neighbour list``).

        A fresh copy, so callers can serialise or mutate it without touching the
        graph's internal state.
        """
        return {place: list(neighbours) for place, neighbours in self._adjacency.items()}

    @property
    def edge_routes_records(self):
        """JSON-friendly graph: ``[[a, b, [route indices]], ...]``.

        Both the topology (edges) and the authored-route provenance in one
        structure — persisted as the sole derived graph file.
        """
        return [
            [a, b, list(routes)] for (a, b), routes in sorted(self._edge_routes.items())
        ]

    def routes_on(self, a, b):
        """Sorted tuple of authored route indices that use edge ``(a, b)``."""
        return self._edge_routes.get(edge_key(a, b), ())

    def route_ids(self):
        """Sorted authored-route indices present on any edge.

        The set of arteries the router can bias toward when enumerating diverse
        alternatives (one candidate per dominant route). See :mod:`.routing`.
        """
        ids = set()
        for routes in self._edge_routes.values():
            ids.update(routes)
        return sorted(ids)

    def route_marks(self, route_id):
        """The rated stretches of authored route ``route_id``.

        A tuple of ``(start place, end place, priority)``; empty for an unrated
        route — including the synthetic edge-key "routes" a provenance-less graph
        falls back on, which aren't authored routes at all and so can't be rated.
        """
        return self._route_marks.get(route_id, ())

    def run_priority(self, route_id, span):
        """The priority a *run* on ``route_id`` covering ``span`` rides at.

        ``span`` is the run's node sequence (any container of place names). A mark
        counts only when the run holds **both** of its endpoints: riding part of a
        rated stretch is deliberately free, and the mark is the author's statement
        of how much of the artery has to be driven before the rating applies. The
        worst such mark wins; a run completing none rides at :data:`BEST_PRIORITY`.

        Testing by endpoint names is exact — every edge of the run is on
        ``route_id`` and that route's chain is a simple path, so a contiguous run
        holding both endpoints holds the whole stretch between them. (Hot callers
        don't come through here: :func:`~.concentration.ridden_marks` walks the
        candidate chain once and reports integer windows instead.)
        """
        marks = self._route_marks.get(route_id)
        if not marks:
            return BEST_PRIORITY
        nodes = span if isinstance(span, (set, frozenset)) else set(span)
        return max(
            (priority for start, end, priority in marks if start in nodes and end in nodes),
            default=BEST_PRIORITY,
        )

    def route_priority(self, route_id):
        """The worst priority route ``route_id`` can inflict (``0`` when unmarked).

        The rating a route is capable of, not one it necessarily applies: what a
        given ride actually pays is :meth:`run_priority`. This is the *floor* the
        candidate generators bias against in :meth:`~.routing.RouteFinder.
        _generate_chains`.
        """
        marks = self._route_marks.get(route_id)
        if not marks:
            return BEST_PRIORITY
        return max(priority for _, _, priority in marks)

    def _route_chain(self, route_id):
        """Reconstruct route ``route_id``'s stop chain from the edges tagged with it.

        The graph persists edges, not chains, but a mark's *edge set* (which
        :meth:`edge_priority` needs) can't be known without the order. The edges of
        one authored route form a path, so walking them recovers it. Returns
        ``None`` when they don't — a route that revisits a place — which the caller
        handles conservatively rather than guessing an order.
        """
        adjacency = {}
        for (a, b), routes in self._edge_routes.items():
            if route_id in routes:
                adjacency.setdefault(a, []).append(b)
                adjacency.setdefault(b, []).append(a)
        if not adjacency:
            return None
        ends = [node for node, near in adjacency.items() if len(near) == 1]
        if len(ends) != 2 or any(len(near) > 2 for near in adjacency.values()):
            return None
        chain = [min(ends)]
        previous = None
        while True:
            onward = [n for n in adjacency[chain[-1]] if n != previous]
            if not onward:
                break
            previous = chain[-1]
            chain.append(onward[0])
        return chain if len(chain) == len(adjacency) else None

    def _marked_edges(self, route_id):
        """``{edge_key: worst mark priority}`` for the edges inside ``route_id``'s marks.

        Memoised, and only ever computed for a route that actually carries marks.
        When the chain can't be recovered (see :meth:`_route_chain`) every edge of
        the route counts as marked at its worst rating: this feeds *generators*
        only, where over-banning costs a detour candidate, never a wrong score.
        """
        cached = self._marked_edges_cache.get(route_id)
        if cached is not None:
            return cached
        marks = self._route_marks.get(route_id, ())
        marked = {}
        if marks:
            chain = self._route_chain(route_id)
            if chain is None:
                worst = max(priority for _, _, priority in marks)
                marked = {
                    edge: worst
                    for edge, routes in self._edge_routes.items()
                    if route_id in routes
                }
            else:
                position = {}
                for index, place in enumerate(chain):
                    position.setdefault(place, index)
                for start, end, priority in marks:
                    i, j = position.get(start), position.get(end)
                    if i is None or j is None:
                        continue
                    if i > j:
                        i, j = j, i
                    for a, b in zip(chain[i:j], chain[i + 1 : j + 1]):
                        key = edge_key(a, b)
                        marked[key] = max(marked.get(key, BEST_PRIORITY), priority)
        self._marked_edges_cache[route_id] = marked
        return marked

    def edge_priority(self, a, b):
        """The best priority available on edge ``(a, b)``.

        An edge may be carried by several authored routes; travelling it commits
        you to *at least* the best-rated of them, so the edge's priority is their
        minimum — where a single route rates the edge by the worst of its marks
        covering it. Note this is **not** the route *tier* (that needs the marked
        stretch ridden *whole* — see :func:`~.concentration.tier`); it is the
        per-edge best the generators use to hunt for a physically better-rated
        corridor, and the skip test in
        :meth:`~.routing.RouteFinder._crosses_forced_below`. Deliberately
        pessimistic next to the tier: an edge merely *inside* a marked stretch reads
        as rated here even though clipping that stretch would cost nothing, which
        keeps the generators hunting for a corridor that avoids the mark entirely.
        Optimistic in the one way the tier is not, too — an edge co-served by an
        unmarked route reads as best here, while the tier rates the road whoever
        carries it — for the same reason: this is a hint for generation, and it
        errs toward *looking* for a cleaner corridor rather than toward rating one.
        """
        routes = self.routes_on(a, b)
        if not routes:
            return BEST_PRIORITY
        key = edge_key(a, b)
        return min(
            self._marked_edges(route).get(key, BEST_PRIORITY) for route in routes
        )

    def has_priorities(self):
        """Whether any authored route carries a mark worse than :data:`BEST_PRIORITY`.

        When nothing is rated, priority cannot change any ranking, so the
        priority-aware candidate passes in :mod:`.routing` are skipped entirely
        and the search costs exactly what it did before the feature existed.
        """
        return bool(self._route_marks)

    def worst_priority(self):
        """The worst priority any mark carries (``0`` when nothing is rated)."""
        return max(
            (priority for marks in self._route_marks.values() for _, _, priority in marks),
            default=BEST_PRIORITY,
        )

    def __contains__(self, place):
        return place in self._adjacency

    def neighbors(self, place):
        """Sorted neighbours of ``place`` (raises ``KeyError`` if unknown)."""
        return self._adjacency[place]

    def degree(self, place):
        """Number of connections ``place`` has (raises ``KeyError`` if unknown)."""
        return len(self._adjacency[place])

    def is_crossroad(self, place, min_degree=3):
        """Whether ``place`` is a real intersection (``degree >= min_degree``).

        Places below the threshold are transparent: shape points along a road,
        not decision points. Crossroad count is the router's tiebreak once the
        merged-route count is settled.
        """
        return len(self._adjacency[place]) >= min_degree

    def crossroads(self, min_degree=3):
        """Sorted places that are real intersections (``degree >= min_degree``)."""
        return sorted(
            place for place in self._adjacency if len(self._adjacency[place]) >= min_degree
        )

    def places(self):
        """Sorted list of every place in the graph (autocomplete source)."""
        return sorted(self._adjacency)

    def without_places(self, places):
        """A copy of this graph with ``places`` (and their incident edges) removed."""
        exclude = set(places)
        adjacency = {
            place: [n for n in neighbours if n not in exclude]
            for place, neighbours in self._adjacency.items()
            if place not in exclude
        }
        edge_routes = {
            edge: routes
            for edge, routes in self._edge_routes.items()
            if edge[0] not in exclude and edge[1] not in exclude
        }
        return Graph(adjacency, edge_routes, self._route_marks)

    def to_network(self):
        """Shape the graph for react-force-graph-2d: ``{nodes, links}``.

        Undirected edges are de-duplicated by ordering each pair so a link is
        only emitted once.
        """
        nodes = [{"id": place} for place in self.places()]

        seen = set()
        links = []
        for place, neighbours in self._adjacency.items():
            for neighbour in neighbours:
                key = edge_key(place, neighbour)
                if key in seen:
                    continue
                seen.add(key)
                links.append({"source": key[0], "target": key[1]})

        return {"nodes": nodes, "links": links}
