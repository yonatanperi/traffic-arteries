"""The :class:`Graph` itself: an undirected graph of place names.

Routes are chains of place names. Consecutive places in a route form a
bidirectional edge. From those edges we build an undirected graph stored as an
adjacency list. A :class:`Graph` can be constructed straight from a persisted
adjacency dict, or derived from routes with :meth:`Graph.from_routes`.

Every edge also remembers **which authored routes traverse it** (by index), so
the router can find the route that merges the fewest authored routes rather than
the shortest one. See :mod:`.search`.

Each authored route also carries a **priority** (``0`` = best … ``3`` = worst),
which is what makes some arteries worth riding more than others. The graph is
where that lives, since both the scorer (:mod:`.concentration`) and the candidate
generators (:mod:`.search`) need it per edge.
"""

# Authored-route priority: 0 is best, WORST_PRIORITY is worst. A route with no
# stated priority (and any edge with no authored-route provenance) is best by
# default, so a graph that knows nothing about priorities behaves exactly as it
# did before the feature existed.
BEST_PRIORITY = 0
WORST_PRIORITY = 3


def edge_key(a, b):
    """Order-independent key for an undirected edge."""
    return (a, b) if a <= b else (b, a)


def path_edges(path):
    """The set of undirected edge keys that make up a path."""
    return {edge_key(a, b) for a, b in zip(path, path[1:])}


def _priority_map(priorities):
    """``{route index: priority}`` from a sequence parallel to the routes.

    Default-priority routes are left out, so a graph where nothing is rated
    carries an empty map and every priority lookup short-circuits.
    """
    if not priorities:
        return {}
    return {
        index: priority
        for index, priority in enumerate(priorities)
        if priority != BEST_PRIORITY
    }


class Graph:
    """An undirected graph of places, backed by an adjacency list.

    The adjacency is normalised to ``{place: sorted list of neighbours}``. The
    sorted order is what makes every search deterministic: neighbours are always
    visited in the same sequence, so equal-cost ties resolve the same way.

    ``edge_routes`` maps each :func:`edge_key` to the sorted tuple of authored
    route indices that use it. It is optional: a graph loaded adjacency-only (or
    built without route provenance) simply has no membership, and the router then
    treats every edge as its own route.

    ``route_priorities`` maps an authored route index to its priority
    (:data:`BEST_PRIORITY` … :data:`WORST_PRIORITY`). Also optional — an unrated
    route is :data:`BEST_PRIORITY`.
    """

    def __init__(self, adjacency, edge_routes=None, route_priorities=None):
        """Wrap a raw ``{place: iterable of neighbours}`` mapping.

        Neighbours are de-duplicated and sorted, so passing either a freshly
        built adjacency or one loaded from disk yields the same normalised graph.
        ``edge_routes`` is an optional ``{edge_key: iterable of route indices}``,
        and ``route_priorities`` an optional ``{route index: priority}``.
        """
        self._adjacency = {
            place: sorted(set(neighbours)) for place, neighbours in adjacency.items()
        }
        self._edge_routes = {
            edge_key(*edge): tuple(sorted(set(routes)))
            for edge, routes in (edge_routes or {}).items()
        }
        self._route_priorities = dict(route_priorities or {})

    @classmethod
    def from_routes(cls, routes, priorities=None):
        """Build a graph from routes (lists of place names).

        Each pair of *consecutive* places in a route becomes an undirected edge,
        tagged with that route's index in ``edge_routes``. Every place that
        appears is guaranteed a node, even if it ends up isolated. Self-loops (a
        place adjacent to itself) are ignored.

        ``priorities`` is an optional sequence parallel to ``routes``; omit it and
        every route is :data:`BEST_PRIORITY`.
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

        return cls(adjacency, edge_routes, _priority_map(priorities))

    @classmethod
    def from_edge_routes(cls, records, priorities=None):
        """Build a graph from persisted ``[[a, b, [route indices]], ...]`` records.

        These records (see :attr:`edge_routes_records`) are the single derived
        representation of the graph: the adjacency is reconstructed from the
        edges. Every connected place appears on at least one edge, so nothing
        routable is lost.

        ``priorities`` is an optional sequence indexed by authored route — it is
        *not* part of the derived records, it comes straight from the routes file,
        which stays the single source of truth for it.
        """
        adjacency = {}
        edge_routes = {}
        for a, b, routes in records:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
            edge_routes[edge_key(a, b)] = routes
        return cls(adjacency, edge_routes, _priority_map(priorities))

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

    def route_priority(self, route_id):
        """Priority of authored route ``route_id`` (``0`` = best).

        Anything unrated is :data:`BEST_PRIORITY` — including the synthetic
        edge-key "routes" a provenance-less graph falls back on, which aren't
        authored routes at all and so can't be rated.
        """
        return self._route_priorities.get(route_id, BEST_PRIORITY)

    def edge_priority(self, a, b):
        """The best priority available on edge ``(a, b)``.

        An edge may be carried by several authored routes; travelling it commits
        you to *at least* the best-rated of them, so the edge's priority is their
        minimum. This is the per-edge term the route *tier* is a max over — see
        :func:`~.concentration.tier`.
        """
        routes = self.routes_on(a, b)
        if not routes:
            return BEST_PRIORITY
        return min(self.route_priority(route) for route in routes)

    def has_priorities(self):
        """Whether any authored route is rated worse than :data:`BEST_PRIORITY`.

        When nothing is rated, priority cannot change any ranking, so the
        priority-aware candidate passes in :mod:`.routing` are skipped entirely
        and the search costs exactly what it did before the feature existed.
        """
        return bool(self._route_priorities)

    def worst_priority(self):
        """The worst priority any authored route carries (``0`` when none are rated)."""
        return max(self._route_priorities.values(), default=BEST_PRIORITY)

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
        return Graph(adjacency, edge_routes, self._route_priorities)

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
