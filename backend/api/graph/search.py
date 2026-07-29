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

from .concentration import LengthMode
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
    """Merge-minimising route visiting ``points`` in order.

    The route touches the required stops in the given order and is simple *leg by
    leg*, carrying the same ``active_route`` state as :class:`MinMergeStrategy`:

      * no node is re-entered **within a leg** — a leg being the stretch between
        two consecutive required stops, which is where a pointless loop would be;
      * a required stop may only be entered when it is the *next* one due;
      * among equal-cost frontiers the earliest-discovered wins (deterministic).

    Simplicity is deliberately scoped to the leg, not to the whole route. A
    required stop can be a **dead end** (``נחל עוז`` and 26 other places in the
    live network have degree 1) or sit behind a bridge, and the only way back out
    is the way you came in — so the leg that leaves it must re-cross nodes the
    leg that arrived already used. Demanding one globally simple path makes every
    such stop unroutable, and in a sparse road network it also rejects plenty of
    ordinary via-queries that simply have no simple path visiting the stops in
    order. Retracing across a leg boundary is what driving to a spur and back
    actually looks like; looping inside one leg is not, and stays banned.

    Like :class:`MinMergeStrategy`, dominated states are pruned via a ``best``
    dict keyed on ``(node, active_route, reached)`` — the same approximation:
    the *cheapest* way to reach a state wins even though, in principle, a
    costlier arrival could have a different visited-node history that later
    avoids a revisit the cheap one can't. Without this pruning the search
    re-explores the same state once per distinct path prefix, which blows up
    combinatorially (and reliably burns through :data:`SEARCH_STATE_CAP`)
    whenever a required stop sits on a well-connected hub. Note ``reached`` is
    already part of that key, so scoping the visited set to the leg costs no
    extra states — the legs were separated in the pruning key all along.

    :meth:`find` returns ``(nodes, route_seq)`` or ``(None, None)`` if no such
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
        # Heap entries: (cost, tie, node, active_route, reached, nodes, route_seq,
        # leg) — `leg` being the nodes visited since the last required stop, i.e.
        # the set the no-revisit rule applies to. It resets at every stop.
        heap = [(0.0, next(counter), points[0], None, 1, (points[0],), (),
                 frozenset((points[0],)))]
        best = {(points[0], None, 1): 0.0}
        explored = 0

        while heap:
            cost, _, node, active, reached, nodes, route_seq, leg = heapq.heappop(heap)
            if reached > last:
                return list(nodes), route_seq  # reached the final stop, in order

            explored += 1
            if explored > SEARCH_STATE_CAP:
                break

            if cost > best.get((node, active, reached), float("inf")):
                continue  # a cheaper way to this state was already settled

            target = points[reached]
            for neighbour in graph.neighbors(node):
                # No looping back onto this leg. Reaching the target is always
                # allowed — that is how a dead-end stop is left (back out through
                # the node you came in by) and how a round trip closes on its own
                # start when start == end.
                if neighbour in leg and neighbour != target:
                    continue
                # A required stop is only enterable as the current target.
                if neighbour in point_set and neighbour != target:
                    continue
                pen = penalty.get(edge_key(node, neighbour), 0.0)
                hop = 1.0 if graph.is_crossroad(neighbour) else 0.0
                reaches_stop = neighbour == target
                new_reached = reached + 1 if reaches_stop else reached
                # A stop starts the next leg, so the visited set restarts there.
                new_leg = frozenset((neighbour,)) if reaches_stop else leg | {neighbour}
                for route in _routes_on(graph, node, neighbour):
                    transfer = 0.0 if route == active else 1.0
                    new_cost = cost + TRANSFER_WEIGHT * transfer + hop + pen
                    state = (neighbour, route, new_reached)
                    if new_cost < best.get(state, float("inf")):
                        best[state] = new_cost
                        heapq.heappush(
                            heap,
                            (new_cost, next(counter), neighbour, route, new_reached,
                             nodes + (neighbour,), route_seq + (route,), new_leg),
                        )

        return None, None
