"""Single-route search over a :class:`~.core.Graph`.

:class:`MinMergeStrategy` answers one question: *given a map of edge penalties,
what is the single best route from here to there right now?* — where "best" is
lexicographic ``(route transfers, crossroad hops)``. It is deliberately only ever
asked about a plain point-to-point stretch. Required stops used to be a second
strategy that solved the whole ordered sequence at once; they are now handled a leg
at a time in :meth:`~.routing.RouteFinder._leg_ranked_pool`, so this layer has one
shape of problem to solve and the penalty maps below compose over it uniformly.

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

from .concentration import LengthMode
from .core import edge_key

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


def min_crossroad_distance(graph, source, target):
    """Shortest ``source -> target`` distance, in the active :class:`~.concentration.
    LengthMode` units, or ``None`` if unreachable.

    This is the ranking score's length reference (see :meth:`~.routing.RouteFinder.
    _rank`), so it must use the same length notion :func:`~.concentration.evaluate`
    sums for the HHI itself — otherwise the ranking tempers a score with a unit the
    score never used. It depends only on the network's shape — never on how routes
    are rated — which is exactly the point: the reported match % must not move when
    an artery is re-prioritised.

    Under plain hop counting (``CROSSROADS_ONLY = False``) every edge costs 1, so
    this is just unweighted shortest-path distance. Under ``CROSSROADS_ONLY`` every
    node on the path counts, both endpoints included, transparent (degree-2)
    shape-points counting for nothing — entering a node costs 1 or 0, which makes
    this a 0-1 BFS (a deque where free steps go to the front and crossroad steps to
    the back keeps the queue monotone, so it stays linear rather than needing a
    heap). Same distance notion as :meth:`~.routing.RouteFinder._crossroad_hops`
    either way.
    """
    if source not in graph or target not in graph:
        return None

    if not LengthMode.CROSSROADS_ONLY:
        return single_source_costs(graph, source).get(target)

    def weight(node):
        return 1 if graph.is_crossroad(node) else 0

    best = {source: weight(source)}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        cost = best[node]
        for neighbour in graph.neighbors(node):
            step = weight(neighbour)
            if neighbour not in best or cost + step < best[neighbour]:
                best[neighbour] = cost + step
                if step:
                    queue.append(neighbour)
                else:
                    queue.appendleft(neighbour)
    return best.get(target)


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
    exists. The interface outlives its second implementation: :mod:`.routing` takes
    a *pair* of strategies (one per direction) everywhere, and keeping the seam means
    a future generator slots in without touching the generation layer.
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
