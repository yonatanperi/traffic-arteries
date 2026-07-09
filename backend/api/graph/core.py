"""The :class:`Graph` itself: an undirected graph of place names.

Routes are chains of place names. Consecutive places in a route form a
bidirectional edge. From those edges we build an undirected graph stored as an
adjacency list. A :class:`Graph` can be constructed straight from a persisted
adjacency dict, or derived from routes with :meth:`Graph.from_routes`.
"""


def edge_key(a, b):
    """Order-independent key for an undirected edge."""
    return (a, b) if a <= b else (b, a)


class Graph:
    """An undirected graph of places, backed by an adjacency list.

    The adjacency is normalised to ``{place: sorted list of neighbours}``. The
    sorted order is what makes every search deterministic: neighbours are always
    visited in the same sequence, so equal-cost ties resolve the same way.
    """

    def __init__(self, adjacency):
        """Wrap a raw ``{place: iterable of neighbours}`` mapping.

        Neighbours are de-duplicated and sorted, so passing either a freshly
        built adjacency or one loaded from disk yields the same normalised graph.
        """
        self._adjacency = {
            place: sorted(set(neighbours)) for place, neighbours in adjacency.items()
        }

    @classmethod
    def from_routes(cls, routes):
        """Build a graph from routes (lists of place names).

        Each pair of *consecutive* places in a route becomes an undirected edge.
        Every place that appears is guaranteed a node, even if it ends up
        isolated. Self-loops (a place adjacent to itself) are ignored.
        """
        adjacency = {}

        def ensure(place):
            if place not in adjacency:
                adjacency[place] = set()

        for route in routes:
            for place in route:
                ensure(place)
            for a, b in zip(route, route[1:]):
                if a == b:
                    continue
                adjacency[a].add(b)
                adjacency[b].add(a)

        return cls(adjacency)

    @property
    def adjacency(self):
        """JSON-friendly adjacency dict (``place -> sorted neighbour list``).

        A fresh copy, so callers can serialise or mutate it without touching the
        graph's internal state.
        """
        return {place: list(neighbours) for place, neighbours in self._adjacency.items()}

    def __contains__(self, place):
        return place in self._adjacency

    def neighbors(self, place):
        """Sorted neighbours of ``place`` (raises ``KeyError`` if unknown)."""
        return self._adjacency[place]

    def degree(self, place):
        """Number of connections ``place`` has (raises ``KeyError`` if unknown)."""
        return len(self._adjacency[place])

    def crossroads(self, min_degree=3):
        """Sorted places that are real intersections (``degree >= min_degree``).

        Places below the threshold are transparent to routing: they are shape
        points along a road, not decision points, so only travel between
        crossroads is counted. See :class:`~.contraction.SegmentGraph`.
        """
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
