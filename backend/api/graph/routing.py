"""Diverse alternative-route search — the :class:`RouteFinder`.

Route search returns up to ``k`` *genuinely different* options, and "best" means
the route that **merges the fewest authored routes** from ``routes.json`` (not
the shortest one). A :class:`RouteFinder` is bound to one :class:`~.core.Graph`
and holds the diversity tunables; call :meth:`RouteFinder.find_routes` for the
rich results (stops + which authored routes are merged) or
:meth:`RouteFinder.k_shortest_paths` for just the stop chains.
"""

import itertools

from .core import path_edges
from .search import TRANSFER_WEIGHT, MinMergeStrategy, WaypointStrategy, single_source_costs

# Above this many required stops the permutation count (n!) makes exhaustive
# order optimisation impractical, so we fall back to the caller's order.
MAX_OPTIMIZED_WAYPOINTS = 7

# With required stops we keep alternatives tight: a route may not exceed the
# best route through those stops by more than this factor (measured in crossroad
# hops). This stops an alternative from wandering off on a pointless detour.
WAYPOINT_MAX_STRETCH = 1.5


class Route:
    """One result route: the stop chain plus the authored routes it merges.

      * ``stops``          — full place-name chain (consecutive pairs are edges).
      * ``route_ids``      — sorted distinct authored-route indices it stitches.
      * ``route_count``    — how many authored routes are merged (the "best" key).
      * ``crossroad_hops`` — intersections crossed (the tiebreak).
    """

    def __init__(self, stops, route_ids, crossroad_hops):
        self.stops = list(stops)
        self.route_ids = sorted(set(route_ids))
        self.route_count = len(self.route_ids)
        self.crossroad_hops = crossroad_hops


class RouteFinder:
    """Finds diverse alternative routes over a fixed :class:`~.core.Graph`.

    Option 1 is the genuine best (fewest merged authored routes, then fewest
    intersections); each further option is a meaningfully different corridor. The
    tunables shape that diversity:

      * ``penalty_step``  — how much cost each reuse of an edge *adds* (additive,
                            in the search's cost units). One transfer costs
                            :data:`~.search.TRANSFER_WEIGHT`, so a step of that
                            size means "reusing an edge is about as bad as an
                            extra route merge", enough to flip onto a fresh
                            corridor even against a zero-transfer best route.
      * ``max_overlap``    — reject a candidate sharing more than this fraction
                             of its own edges with any accepted route (0..1).
      * ``max_stretch``    — reject alternatives whose crossroad-hop count exceeds
                             the best route's by more than this factor.
    """

    def __init__(self, graph, penalty_step=TRANSFER_WEIGHT, max_overlap=0.6, max_stretch=2.5):
        self.graph = graph
        self.penalty_step = penalty_step
        self.max_overlap = max_overlap
        self.max_stretch = max_stretch

    def find_routes(self, start, end, k=3, via=None):
        """Return up to ``k`` diverse :class:`Route` results, best first.

        ``via`` is an optional list of *required stops* the route must pass
        through (visited in an optimised order, alternatives kept tight so none
        detours around an already-short connection). "Best" is the route merging
        the fewest authored routes, tiebroken by fewest crossroad hops.

        Algorithm — the iterative edge-penalty method used by real routing
        engines:

          1. Find the best (fewest-merge) route.
          2. Multiply the penalty of every edge on it by ``penalty_factor``.
          3. Search again; the penalty repels the next route onto a different
             corridor.
          4. Keep a candidate only if it is not too similar to an already-chosen
             route (``max_overlap``) and not an excessive detour (``max_stretch``).

        Edge cases:
          * ``start == end`` (no ``via``) -> a single trivial ``Route([start])``
          * ``start``/``end``/``via`` absent from graph -> ``[]``
          * no connection / unreachable stop           -> ``[]``
        """
        graph = self.graph
        waypoints = self._normalise_waypoints(start, end, via)

        if start not in graph or end not in graph:
            return []
        if any(stop not in graph for stop in waypoints):
            return []

        # No required stops -> plain point-to-point merge-minimising search.
        if not waypoints:
            if start == end:
                return [Route([start], [], 0)]
            strategy = MinMergeStrategy(graph, start, end)
            return self._collect_diverse(strategy, k, self.max_stretch)

        # Required stops -> strict simple paths, tightly bounded. Try candidate
        # stop orders cheapest-first and keep the first order that yields a route.
        stretch = min(self.max_stretch, WAYPOINT_MAX_STRETCH)
        for points in self._ordered_point_lists(start, end, waypoints):
            strategy = WaypointStrategy(graph, points)
            routes = self._collect_diverse(strategy, k, stretch)
            if routes:
                return routes

        return []

    def k_shortest_paths(self, start, end, k=3, via=None):
        """Backward-compatible view of :meth:`find_routes`: just the stop chains."""
        return [route.stops for route in self.find_routes(start, end, k=k, via=via)]

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

    def _ordered_point_lists(self, start, end, waypoints):
        """Candidate point sequences ``[start, *stops, end]``, cheapest order first.

        The visiting order of the required stops is a small travelling-salesman
        problem. We score every ordering by the unweighted hop distances between
        the key nodes (start, end, each stop) and return the reachable orderings
        sorted from cheapest to most expensive. The caller walks this list and
        keeps the first order that yields an actual (simple-path) route — the
        heuristic order is almost always feasible, but this stays correct when it
        is not.

        Beyond :data:`MAX_OPTIMIZED_WAYPOINTS` stops the permutation count
        explodes, so we consider only the caller's given order.
        """
        key_nodes = [start, end, *waypoints]
        costs = {node: single_source_costs(self.graph, node) for node in key_nodes}

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

    def _crossroad_hops(self, nodes):
        """Intersections entered along ``nodes`` (crossroads after the start)."""
        return sum(1 for node in nodes[1:] if self.graph.is_crossroad(node))

    def _collect_diverse(self, strategy, k, max_stretch):
        """Iterative edge-penalty search for up to ``k`` diverse :class:`Route`s.

        ``strategy.find(penalty)`` returns ``(nodes, route_seq)`` for the current
        penalty map — it encapsulates *how* a single route is found (plain
        point-to-point, or a simple path through required stops). This is the
        shared diversity layer: it penalises the edges of each route it sees so
        the next search is pushed onto a different corridor, and keeps a candidate
        only if it is neither too similar to an accepted route (``max_overlap``)
        nor an excessive detour — more than ``max_stretch`` times the best route's
        length. (Length, not crossroad hops: a detour down a chain of transparent
        nodes adds no hops yet is still a pointless detour.)

        Results are returned best-first: fewest merged routes, then fewest
        crossroad hops, then fewest stops.
        """
        penalty = {}
        accepted = []
        accepted_edges = []  # edge set per accepted route, parallel to ``accepted``
        best_stops = None

        for _ in range(k * 8):
            if len(accepted) >= k:
                break

            nodes, route_seq = strategy.find(penalty)
            if not nodes or len(nodes) < 2:
                break

            edges = path_edges(nodes)
            # Penalise this route's edges (additively) whether or not we keep it,
            # so the next search is pushed somewhere new either way.
            for edge in edges:
                penalty[edge] = penalty.get(edge, 0.0) + self.penalty_step

            if any(edges == prior for prior in accepted_edges):
                continue

            if best_stops is None:
                best_stops = len(nodes)  # the first (unpenalised) route is the best
            elif len(nodes) > best_stops * max_stretch:
                continue  # too long a detour to be a useful alternative

            # Reject near-duplicates: too much of this route reuses one we kept.
            if any(
                len(edges & prior) / len(edges) > self.max_overlap
                for prior in accepted_edges
            ):
                continue

            accepted.append(Route(nodes, route_seq, self._crossroad_hops(nodes)))
            accepted_edges.append(edges)

        # Best-first: fewest merged routes, then fewest intersections, then stops.
        accepted.sort(key=lambda r: (r.route_count, r.crossroad_hops, len(r.stops)))
        return accepted
