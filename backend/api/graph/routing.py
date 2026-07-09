"""Diverse alternative-route search — the :class:`RouteFinder`.

Route search returns up to ``k`` *genuinely different* options (Waze-style
alternatives), not near-duplicates of the shortest path. A :class:`RouteFinder`
is bound to one :class:`~.core.Graph` and holds the diversity tunables; call
:meth:`RouteFinder.k_shortest_paths` to search it.
"""

import itertools

from .contraction import SegmentGraph, expand
from .search import ShortestPathStrategy, WaypointStrategy

# Above this many required stops the permutation count (n!) makes exhaustive
# order optimisation impractical, so we fall back to the caller's order.
MAX_OPTIMIZED_WAYPOINTS = 7

# With required stops we keep alternatives tight: a route may not exceed the
# best route through those stops by more than this factor. This is what stops
# an alternative from wandering off on a pointless detour when a short
# connection between two stops already exists.
WAYPOINT_MAX_STRETCH = 1.5


class RouteFinder:
    """Finds diverse alternative routes over a fixed :class:`~.core.Graph`.

    The goal is Waze-style options: option 1 is the genuine shortest route, and
    each further option is a meaningfully different corridor rather than the
    shortest path with one node swapped. The tunables shape that diversity:

      * ``penalty_factor`` — how hard reused edges are pushed away (>1).
      * ``max_overlap``    — reject a candidate sharing more than this fraction
                             of its own edges with any accepted route (0..1).
      * ``max_stretch``    — reject alternatives longer than this multiple of
                             the shortest route's length.
    """

    def __init__(self, graph, penalty_factor=3.0, max_overlap=0.6, max_stretch=2.5):
        self.graph = graph
        self.penalty_factor = penalty_factor
        self.max_overlap = max_overlap
        self.max_stretch = max_stretch

    def k_shortest_paths(self, start, end, k=3, via=None):
        """Return up to ``k`` diverse alternative routes from ``start`` to ``end``.

        ``via`` is an optional list of *required stops* the route must pass
        through. When given, every returned route is a real-world simple path —
        **no node is ever visited twice** — that touches the stops in an
        optimised order, and alternatives are kept tight (see
        :data:`WAYPOINT_MAX_STRETCH`) so none of them detours around a connection
        that is already short. With no ``via`` the behaviour is the classic
        diverse shortest-path search.

        Algorithm — the iterative edge-penalty method used by real routing
        engines:

          1. Find the shortest path.
          2. Multiply the weight of every edge on it by ``penalty_factor``.
          3. Search again; the penalty repels the next route away from edges the
             chosen routes already cover, so it takes a different corridor.
          4. Keep a candidate only if it is not too similar to an already-chosen
             route (``max_overlap``) and not an excessive detour
             (``max_stretch``).

        Edge cases:
          * ``start == end`` (no ``via``) -> ``[[start]]`` (if the node exists)
          * ``start``/``end``/``via`` absent from graph -> ``[]``
          * no connection / unreachable stop           -> ``[]``
        """
        graph = self.graph
        waypoints = self._normalise_waypoints(start, end, via)

        if start not in graph or end not in graph:
            return []
        if any(stop not in graph for stop in waypoints):
            return []

        # Contract away transparent (<=2-connection) nodes, keeping the terminals
        # so they stay routable. The search then reasons in crossroad-to-crossroad
        # segments; we expand each result back to a full chain before returning.
        seg_graph = SegmentGraph.build(graph, {start, end, *waypoints})

        # No required stops -> classic diverse shortest-path search.
        if not waypoints:
            if start == end:
                return [[start]]
            strategy = ShortestPathStrategy(seg_graph, start, end)
            routes = self._collect_diverse(strategy, k, self.max_stretch)
            return [expand(start, segments) for segments in routes]

        # Required stops -> strict simple paths, tightly bounded so no route
        # wanders off on a detour. Try candidate stop orders cheapest-first and
        # keep the first order that actually yields a simple route.
        stretch = min(self.max_stretch, WAYPOINT_MAX_STRETCH)
        for points in self._ordered_point_lists(seg_graph, start, end, waypoints):
            strategy = WaypointStrategy(seg_graph, points)
            routes = self._collect_diverse(strategy, k, stretch)
            if routes:
                return [expand(start, segments) for segments in routes]

        return []

    @staticmethod
    def _normalise_waypoints(start, end, via):
        """Clean required stops: drop blanks, de-duplicate, and discard any that
        coincide with start/end (already visited), preserving first-seen order.
        """
        waypoints = []
        seen = {start, end}
        for stop in via or []:
            stop = stop.strip() if isinstance(stop, str) else stop
            if stop and stop not in seen:
                seen.add(stop)
                waypoints.append(stop)
        return waypoints

    def _ordered_point_lists(self, seg_graph, start, end, waypoints):
        """Candidate point sequences ``[start, *stops, end]``, cheapest order first.

        The visiting order of the required stops is a small travelling-salesman
        problem. We score every ordering by the segment-count distances between
        the key nodes (start, end, each stop) and return the reachable orderings
        sorted from cheapest to most expensive. The caller walks this list and
        keeps the first order that yields an actual (simple-path) route — the
        heuristic order is almost always feasible, but this stays correct when it
        is not.

        Beyond :data:`MAX_OPTIMIZED_WAYPOINTS` stops the permutation count
        explodes, so we consider only the caller's given order.
        """
        key_nodes = [start, end, *waypoints]
        costs = {node: seg_graph.source_costs(node) for node in key_nodes}

        def total(order):
            sequence = [start, *order, end]
            acc = 0.0
            for a, b in zip(sequence, sequence[1:]):
                step = costs[a].get(b)
                if step is None:
                    return None  # a required leg is unreachable in the base graph
                acc += step
            return acc

        if len(waypoints) <= MAX_OPTIMIZED_WAYPOINTS:
            orders = itertools.permutations(waypoints)
        else:
            orders = [tuple(waypoints)]

        scored = []
        for order in orders:
            cost = total(order)
            if cost is not None:
                scored.append((cost, [start, *order, end]))
        scored.sort(key=lambda item: item[0])
        return [points for _, points in scored]

    def _collect_diverse(self, strategy, k, max_stretch):
        """Iterative segment-penalty search for up to ``k`` diverse routes.

        ``strategy.find(penalty)`` returns ``(segments, cost)`` for the current
        penalty map — it encapsulates *how* a single route is found (plain
        shortest path, or a simple path through required stops). This method is
        the shared diversity layer: it penalises the segments of each route it
        sees so the next search is pushed onto a different corridor (including a
        parallel road between the same two crossroads), and keeps a candidate
        only if it is neither too similar to an accepted route (``max_overlap``)
        nor an excessive detour (``max_stretch``).

        Returns a list of routes, each an ordered list of
        :class:`~.contraction.Segment` objects, fastest (fewest segments) first.
        """
        penalty = {}
        accepted = []
        accepted_ids = []  # segment-id set per accepted route, parallel to ``accepted``
        shortest_cost = None

        for _ in range(k * 8):
            if len(accepted) >= k:
                break

            segments, cost = strategy.find(penalty)
            if not segments:
                break

            ids = {seg.id for seg in segments}
            # Penalise this route's segments whether or not we keep it, so the
            # next search is pushed somewhere new either way.
            for seg in segments:
                penalty[seg.id] = penalty.get(seg.id, 1.0) * self.penalty_factor

            if any(ids == prior for prior in accepted_ids):
                continue

            if shortest_cost is None:
                shortest_cost = cost  # the first (unpenalised) route is the fastest
            elif cost > shortest_cost * max_stretch:
                continue  # too long a detour to be a useful alternative

            # Reject near-duplicates: too much of this route reuses one we kept.
            if any(
                len(ids & prior) / len(ids) > self.max_overlap
                for prior in accepted_ids
            ):
                continue

            accepted.append(segments)
            accepted_ids.append(ids)

        # Present fastest-first; a stable sort preserves discovery order among ties.
        accepted.sort(key=lambda segments: len(segments))
        return accepted
