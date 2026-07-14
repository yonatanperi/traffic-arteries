"""Single-route search strategies over a :class:`~.core.Graph`.

Each strategy answers the same question in a different way: *given a map of edge
penalties, what is the single best route right now?* — where "best" is
lexicographic ``(route transfers, crossroad hops)``. Exposing that behind a
common :meth:`RouteStrategy.find` interface lets the candidate-generation layer
in :mod:`.routing` stay ignorant of whether it is finding a plain point-to-point
route or one that must pass through required stops.

These strategies are **generators**: they minimise route transfers (a good, cheap
proxy), and the actual objective — riding one authored route as far as possible —
is scored *exactly* per candidate in :mod:`.concentration` and used to rank them.
Feeding a strategy a :func:`prefer_route_penalty` map biases it toward one
artery, which is how :mod:`.routing` enumerates genuinely different corridors.

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


def prefer_route_penalty(graph, route_id, bias=TRANSFER_WEIGHT):
    """Penalty map biasing any strategy toward *riding* ``route_id``.

    Every edge whose membership excludes ``route_id`` gets ``bias`` added, so a
    ``strategy.find(...)`` prefers to stay on ``route_id`` and only leaves it when
    it must. Enumerating this for each authored route is how :mod:`.routing`
    produces one candidate per dominant artery — the diversity axis that matters
    under the concentration objective.
    """
    return {
        edge_key(a, b): bias
        for a, b, routes in graph.edge_routes_records
        if route_id not in routes
    }


def ban_weight(graph):
    """A penalty heavy enough to outweigh *any* number of route transfers.

    A simple path visits each place at most once, so it can never make more than
    ``len(places)`` transfers, each costing :data:`TRANSFER_WEIGHT`. One unit of
    this therefore strictly dominates the whole rest of the cost function — which
    is what turns an additive penalty into an effective *ban*: the search will
    accept arbitrarily many transfers before it crosses a banned edge, and only
    crosses one when there is no other way through at all.
    """
    return TRANSFER_WEIGHT * (len(graph.places()) + 1)


def avoid_priority_penalty(graph, max_priority, bias=None):
    """Penalty map confining any strategy to arteries rated ``max_priority`` or better.

    Every edge whose best-rated artery is worse than ``max_priority``
    (:meth:`~.core.Graph.edge_priority`) is effectively banned (see
    :func:`ban_weight`), so ``strategy.find(...)`` returns the best route that never
    leaves that tier — however long a detour that takes — and falls back to crossing
    a worse edge only when the tier simply doesn't connect the endpoints.

    This is what puts a *tier-clean corridor* in the candidate pool at all. Scoring
    can only rank what generation produced, and nothing else in the pool has any
    reason to detour around a badly-rated artery. See :mod:`.routing`.
    """
    if bias is None:
        bias = ban_weight(graph)
    return {
        edge_key(a, b): bias
        for a, b, _ in graph.edge_routes_records
        if graph.edge_priority(a, b) > max_priority
    }


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

    Like :class:`MinMergeStrategy`, dominated states are pruned via a ``best``
    dict keyed on ``(node, active_route, reached)`` — the same approximation:
    the *cheapest* way to reach a state wins even though, in principle, a
    costlier arrival could have a different visited-node history that later
    avoids a revisit the cheap one can't. Without this pruning the search
    re-explores the same state once per distinct path prefix, which blows up
    combinatorially (and reliably burns through :data:`SEARCH_STATE_CAP`)
    whenever a required stop sits on a well-connected hub.

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
        best = {(points[0], None, 1): 0.0}
        explored = 0

        while heap:
            cost, _, node, active, reached, nodes, route_seq = heapq.heappop(heap)
            if reached > last:
                return list(nodes), route_seq  # reached the final stop, in order

            explored += 1
            if explored > SEARCH_STATE_CAP:
                break

            if cost > best.get((node, active, reached), float("inf")):
                continue  # a cheaper way to this state was already settled

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
                    state = (neighbour, route, new_reached)
                    if new_cost < best.get(state, float("inf")):
                        best[state] = new_cost
                        heapq.heappush(
                            heap,
                            (new_cost, next(counter), neighbour, route, new_reached,
                             nodes + (neighbour,), route_seq + (route,)),
                        )

        return None, None
