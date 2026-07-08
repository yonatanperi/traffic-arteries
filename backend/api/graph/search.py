"""Single-route search strategies over a :class:`~.core.Graph`.

Each strategy answers the same question in a different way: *given a map of edge
penalties, what is the single best route right now?* Exposing that behind a
common :meth:`RouteStrategy.find` interface lets the diversity layer in
:mod:`.routing` stay ignorant of whether it is finding a plain shortest path or
a simple path through required stops — it just keeps calling ``find`` with a
growing penalty map to push each successive route onto a fresh corridor.
"""

import heapq
import itertools

from .core import edge_key

# Safety valve for the simple-path search: give up (return "no route") after
# exploring this many partial paths. The route graph is small and sparse, so
# this is never hit in practice; it only guards against pathological blow-ups.
SEARCH_STATE_CAP = 200_000


def single_source_costs(graph, source):
    """Unweighted single-source shortest-path costs from ``source``.

    Returns ``{node: cost}`` for every node reachable from ``source`` (each edge
    costs 1). Used to score candidate waypoint orderings cheaply, before running
    the real penalty-weighted search.
    """
    costs = {source: 0.0}
    heap = [(0.0, source)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > costs.get(node, float("inf")):
            continue
        for neighbour in graph.neighbors(node):
            new_cost = cost + 1.0
            if new_cost < costs.get(neighbour, float("inf")):
                costs[neighbour] = new_cost
                heapq.heappush(heap, (new_cost, neighbour))
    return costs


class RouteStrategy:
    """A way to find one route for a given ``{edge_key: multiplier}`` penalty map.

    Subclasses implement :meth:`find`, returning ``(path, cost)`` for the best
    route under those penalties, or ``(None, inf)`` when none exists.
    """

    def find(self, penalty):  # pragma: no cover - interface
        raise NotImplementedError


class ShortestPathStrategy(RouteStrategy):
    """Dijkstra from ``start`` to ``end`` over penalty-weighted edges.

    Every edge has base cost 1, multiplied by any accumulated penalty in the
    ``penalty`` map. With no penalties this is just an unweighted shortest path;
    penalising the edges of already-chosen routes steers each subsequent search
    onto a different corridor.

    A monotonically increasing counter breaks cost ties in insertion order, so
    among equal-cost paths the one whose nodes come first (neighbours are
    iterated in sorted order) wins — stable, deterministic output.
    """

    def __init__(self, graph, start, end):
        self.graph = graph
        self.start = start
        self.end = end

    def find(self, penalty):
        graph, start, end = self.graph, self.start, self.end
        counter = itertools.count()
        # Heap entries: (cost, tie_breaker, node, path_so_far).
        heap = [(0.0, next(counter), start, [start])]
        best_cost = {start: 0.0}

        while heap:
            cost, _, node, path = heapq.heappop(heap)
            if node == end:
                return path, cost
            if cost > best_cost.get(node, float("inf")):
                continue  # a cheaper route to this node was already settled
            for neighbour in graph.neighbors(node):
                if neighbour in path:
                    continue  # keep the path simple (cycle-free)
                step = penalty.get(edge_key(node, neighbour), 1.0)
                new_cost = cost + step
                if new_cost < best_cost.get(neighbour, float("inf")):
                    best_cost[neighbour] = new_cost
                    heapq.heappush(
                        heap, (new_cost, next(counter), neighbour, path + [neighbour])
                    )

        return None, float("inf")


class WaypointStrategy(RouteStrategy):
    """Penalty-weighted shortest *simple* path visiting ``points`` in order.

    Real-world routing: the whole route is a simple path — no node is ever
    visited twice — that touches the required stops in the given order. It is a
    best-first search over partial simple paths:

      * a node already on the path is never re-entered (no revisits);
      * a required stop may only be entered when it is the *next* one due —
        stepping onto a later stop early would strand it and dead-end;
      * among equal-cost frontiers the earliest-discovered wins, so output is
        deterministic (neighbours are iterated in sorted order).

    Because it always expands the cheapest frontier first, the very first route
    it returns is the genuine shortest one for this order — so when a direct
    connection between two stops exists it is used, never detoured around.

    :meth:`find` returns ``(path, cost)`` or ``(None, inf)`` if no simple route
    visits every stop in order.
    """

    def __init__(self, graph, points):
        self.graph = graph
        self.points = points

    def find(self, penalty):
        graph, points = self.graph, self.points
        point_set = set(points)
        last = len(points) - 1  # index of the final stop (the end)

        counter = itertools.count()
        # Heap entries: (cost, tie_breaker, node, reached, path). ``reached`` is
        # how many entries of ``points`` we have hit so far; we start already on
        # the first one, so the next stop due is ``points[reached]``.
        heap = [(0.0, next(counter), points[0], 1, (points[0],))]
        explored = 0

        while heap:
            cost, _, node, reached, path = heapq.heappop(heap)
            if reached > last:
                return list(path), cost  # reached the final stop, in order

            explored += 1
            if explored > SEARCH_STATE_CAP:
                break

            target = points[reached]
            for neighbour in graph.neighbors(node):
                # The final step may land back on the start node (a round trip
                # where start == end); every other repeat is forbidden.
                revisits = neighbour in path
                if revisits and not (neighbour == target and reached == last):
                    continue
                # A required stop is only enterable as the current target.
                if neighbour in point_set and neighbour != target:
                    continue
                step = penalty.get(edge_key(node, neighbour), 1.0)
                new_reached = reached + 1 if neighbour == target else reached
                heapq.heappush(
                    heap,
                    (cost + step, next(counter), neighbour, new_reached, path + (neighbour,)),
                )

        return None, float("inf")
