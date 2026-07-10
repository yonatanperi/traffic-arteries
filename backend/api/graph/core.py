"""The :class:`Graph` itself: an undirected graph of place names.

Routes are chains of place names. Consecutive places in a route form a
bidirectional edge. From those edges we build an undirected graph stored as an
adjacency list. A :class:`Graph` can be constructed straight from a persisted
adjacency dict, or derived from routes with :meth:`Graph.from_routes`.

Every edge also remembers **which authored routes traverse it** (by index), so
the router can find the route that merges the fewest authored routes rather than
the shortest one. See :mod:`.search`.
"""


def edge_key(a, b):
    """Order-independent key for an undirected edge."""
    return (a, b) if a <= b else (b, a)


def path_edges(path):
    """The set of undirected edge keys that make up a path."""
    return {edge_key(a, b) for a, b in zip(path, path[1:])}


class Graph:
    """An undirected graph of places, backed by an adjacency list.

    The adjacency is normalised to ``{place: sorted list of neighbours}``. The
    sorted order is what makes every search deterministic: neighbours are always
    visited in the same sequence, so equal-cost ties resolve the same way.

    ``edge_routes`` maps each :func:`edge_key` to the sorted tuple of authored
    route indices that use it. It is optional: a graph loaded adjacency-only (or
    built without route provenance) simply has no membership, and the router then
    treats every edge as its own route.
    """

    def __init__(self, adjacency, edge_routes=None):
        """Wrap a raw ``{place: iterable of neighbours}`` mapping.

        Neighbours are de-duplicated and sorted, so passing either a freshly
        built adjacency or one loaded from disk yields the same normalised graph.
        ``edge_routes`` is an optional ``{edge_key: iterable of route indices}``.
        """
        self._adjacency = {
            place: sorted(set(neighbours)) for place, neighbours in adjacency.items()
        }
        self._edge_routes = {
            edge_key(*edge): tuple(sorted(set(routes)))
            for edge, routes in (edge_routes or {}).items()
        }

    @classmethod
    def from_routes(cls, routes):
        """Build a graph from routes (lists of place names).

        Each pair of *consecutive* places in a route becomes an undirected edge,
        tagged with that route's index in ``edge_routes``. Every place that
        appears is guaranteed a node, even if it ends up isolated. Self-loops (a
        place adjacent to itself) are ignored.
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

        return cls(adjacency, edge_routes)

    @classmethod
    def from_edge_routes(cls, records):
        """Build a graph from persisted ``[[a, b, [route indices]], ...]`` records.

        These records (see :attr:`edge_routes_records`) are the single derived
        representation of the graph: the adjacency is reconstructed from the
        edges. Every connected place appears on at least one edge, so nothing
        routable is lost.
        """
        adjacency = {}
        edge_routes = {}
        for a, b, routes in records:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
            edge_routes[edge_key(a, b)] = routes
        return cls(adjacency, edge_routes)

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
