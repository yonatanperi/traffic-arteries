"""Single-route search strategies over a :class:`~.core.Graph`.

The objective is **merge-minimising**: a route is a stitch of authored routes,
and we want the one that merges the *fewest* of them. Each strategy answers the
same question in a different way: *given a map of edge penalties, what is the
single best route right now?* — where "best" is lexicographic
``(route transfers, crossroad hops)``. Exposing that behind a common
:meth:`RouteStrategy.find` interface lets the diversity layer in :mod:`.routing`
stay ignorant of whether it is finding a plain point-to-point route or one that
must pass through required stops.

A *transfer* happens whenever an edge is traversed on a different authored route
than the previous edge — which may be at any node, transparent or not — so the
search carries the ``active_route`` in its state. Among equal-merge routes the
tiebreak is crossroad hops (entering a ``degree >= 3`` node), which keeps
transparent shape-points from inflating cost.
"""

import heapq
import itertools
from collections import deque

from .core import edge_key

# Safety valve for the waypoint search: give up (return "no route") after
# exploring this many partial paths. The route graph is small and sparse, so
# this is never hit in practice; it only guards against pathological blow-ups.
SEARCH_STATE_CAP = 200_000

# A single scalar cost encodes the lexicographic objective
# ``(route transfers, crossroad hops)``: one transfer costs TRANSFER_WEIGHT, one
# crossroad hop costs 1. TRANSFER_WEIGHT dwarfs any achievable hop count, so
# fewer merged routes always wins; hops only break ties. The diversity layer adds
# *additive* per-edge penalties on top (see :mod:`.routing`) — additive, because a
# best route with zero transfers has zero transfer-cost that a multiplier could
# never lift, so reuse must be discouraged by adding, not scaling.
TRANSFER_WEIGHT = 1_000_000.0


def single_source_costs(graph, source):
    """Unweighted single-source hop counts ``{node: cost}`` from ``source``.

    Each edge costs 1. Used only to score candidate waypoint orderings cheaply,
    before the real merge-minimising search runs.
    """
    costs = {source: 0.0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbour in graph.neighbors(node):
            if neighbour not in costs:
                costs[neighbour] = costs[node] + 1.0
                queue.append(neighbour)
    return costs


def _routes_on(graph, a, b):
    """Authored routes on edge ``(a, b)``; fall back to the edge as its own route.

    A graph loaded adjacency-only has no membership, so each edge becomes a
    distinct synthetic route and merge-minimising degrades to fewest-edges.
    """
    return graph.routes_on(a, b) or (edge_key(a, b),)


class RouteStrategy:
    """A way to find one route for a given ``{edge_key: multiplier}`` penalty map.

    Subclasses implement :meth:`find`, returning ``(nodes, route_seq)`` for the
    best route under those penalties (``route_seq`` is the chosen authored route
    per edge, parallel to the edges of ``nodes``), or ``(None, None)`` when none
    exists.
    """

    def find(self, penalty):  # pragma: no cover - interface
        raise NotImplementedError


class MinMergeStrategy(RouteStrategy):
    """Merge-minimising best-first search from ``start`` to ``end``.

    State is ``(node, active_route)``; cost is the scalar
    ``TRANSFER_WEIGHT·transfers + hops + reuse penalties``. With an empty penalty
    map this is exactly ``(merges - 1)`` weighted plus ``crossroad_hops``;
    additive per-edge penalties from the diversity layer steer each subsequent
    search onto a different corridor. A monotonically increasing counter breaks
    ties in insertion order for deterministic output.
    """

    def __init__(self, graph, start, end):
        self.graph = graph
        self.start = start
        self.end = end

    def find(self, penalty):
        graph, start, end = self.graph, self.start, self.end
        counter = itertools.count()
        # Heap entries: (cost, tie, node, active_route, nodes, route_seq).
        heap = [(0.0, next(counter), start, None, (start,), ())]
        best = {(start, None): 0.0}

        while heap:
            cost, _, node, active, nodes, route_seq = heapq.heappop(heap)
            if node == end:
                return list(nodes), route_seq
            if cost > best.get((node, active), float("inf")):
                continue  # a cheaper way to this state was already settled
            for neighbour in graph.neighbors(node):
                if neighbour in nodes:
                    continue  # keep the path simple (cycle-free)
                pen = penalty.get(edge_key(node, neighbour), 0.0)
                hop = 1.0 if graph.is_crossroad(neighbour) else 0.0
                for route in _routes_on(graph, node, neighbour):
                    transfer = 0.0 if route == active else 1.0
                    new_cost = cost + TRANSFER_WEIGHT * transfer + hop + pen
                    state = (neighbour, route)
                    if new_cost < best.get(state, float("inf")):
                        best[state] = new_cost
                        heapq.heappush(
                            heap,
                            (new_cost, next(counter), neighbour, route,
                             nodes + (neighbour,), route_seq + (route,)),
                        )

        return None, None


class WaypointStrategy(RouteStrategy):
    """Merge-minimising simple route visiting ``points`` in order.

    The whole route is a simple path — no node visited twice — that touches the
    required stops in the given order, carrying the same ``active_route`` state as
    :class:`MinMergeStrategy`:

      * a node already on the path is never re-entered (no revisits);
      * a required stop may only be entered when it is the *next* one due;
      * among equal-cost frontiers the earliest-discovered wins (deterministic).

    :meth:`find` returns ``(nodes, route_seq)`` or ``(None, None)`` if no simple
    route visits every stop in order.
    """

    def __init__(self, graph, points):
        self.graph = graph
        self.points = points

    def find(self, penalty):
        graph, points = self.graph, self.points
        point_set = set(points)
        last = len(points) - 1  # index of the final stop (the end)

        counter = itertools.count()
        # Heap entries: (cost, tie, node, active_route, reached, nodes, route_seq).
        heap = [(0.0, next(counter), points[0], None, 1, (points[0],), ())]
        explored = 0

        while heap:
            cost, _, node, active, reached, nodes, route_seq = heapq.heappop(heap)
            if reached > last:
                return list(nodes), route_seq  # reached the final stop, in order

            explored += 1
            if explored > SEARCH_STATE_CAP:
                break

            target = points[reached]
            for neighbour in graph.neighbors(node):
                # The final step may land back on the start node (a round trip
                # where start == end); every other repeat is forbidden.
                revisits = neighbour in nodes
                if revisits and not (neighbour == target and reached == last):
                    continue
                # A required stop is only enterable as the current target.
                if neighbour in point_set and neighbour != target:
                    continue
                pen = penalty.get(edge_key(node, neighbour), 0.0)
                hop = 1.0 if graph.is_crossroad(neighbour) else 0.0
                new_reached = reached + 1 if neighbour == target else reached
                for route in _routes_on(graph, node, neighbour):
                    transfer = 0.0 if route == active else 1.0
                    new_cost = cost + TRANSFER_WEIGHT * transfer + hop + pen
                    heapq.heappush(
                        heap,
                        (new_cost, next(counter), neighbour, route, new_reached,
                         nodes + (neighbour,), route_seq + (route,)),
                    )

        return None, None
