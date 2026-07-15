"""Diverse alternative-route search — the :class:`RouteFinder`.

Route search returns up to ``k`` *genuinely different* options, and "best" means
the route that **rides one good authored route as far as possible** — the best
:mod:`concentration <.concentration>` tier and score, not the shortest route and
not simply the fewest merges.

Because the concentration objective is non-additive it cannot be optimised inside
a single search. Instead a :class:`RouteFinder` *generates* a pool of candidate
chains and scores each one exactly:

  1. **Generate** — one candidate per authored route, biased to ride that artery
     (:func:`~.search.prefer_route_penalty`), one per priority tier, confined to
     arteries rated that well (:func:`~.search.avoid_priority_penalty`), plus the
     unbiased best and an edge-penalty diversity backfill. The dominant artery is
     the natural axis of diversity here, so this yields structurally different
     corridors, not one-hop tweaks.
  2. **Score & rank** — evaluate each chain's exact tier + concentration, sort by
     tier first, then concentration.
  3. **Select** — greedily keep the best, then each next-best that is different
     enough (edge overlap) and not an excessive detour, up to ``k``.

The priority-aware passes are skipped whenever no authored route is rated worse
than best (the common case), so the search costs exactly what it did before
priorities existed.

Call :meth:`RouteFinder.find_routes` for the rich results (stops + concentration +
which authored routes are merged) or :meth:`RouteFinder.k_shortest_paths` for
just the stop chains.
"""

import itertools

from .concentration import PriorityMode, evaluate
from .core import BEST_PRIORITY, path_edges
from .search import (
    TRANSFER_WEIGHT,
    MinMergeStrategy,
    WaypointStrategy,
    avoid_priority_penalty,
    prefer_route_penalty,
    single_source_costs,
)

# Above this many required stops the permutation count (n!) makes exhaustive
# order optimisation impractical, so we fall back to the caller's order.
MAX_OPTIMIZED_WAYPOINTS = 7

# With required stops we keep alternatives tight: a route may not exceed the
# best route through those stops by more than this factor (measured in stops).
# This stops an alternative from wandering off on a pointless detour.
WAYPOINT_MAX_STRETCH = 1.5


def _add_penalties(*maps):
    """Combine ``{edge_key: cost}`` penalty maps by *adding* the costs.

    The search's penalties are additive (see :data:`~.search.TRANSFER_WEIGHT`), so
    stacking two biases means summing them, not overwriting: an edge that is both
    off the preferred artery and below the priority floor should be discouraged on
    both counts.
    """
    combined = {}
    for penalty in maps:
        for edge, cost in penalty.items():
            combined[edge] = combined.get(edge, 0.0) + cost
    return combined


class Route:
    """One result route: the stop chain plus how well it rides one good artery.

      * ``stops``          — full place-name chain (consecutive pairs are edges).
      * ``priority``       — its *tier*: the worst priority among the sub-routes it
                             rides — ``max`` over ``runs`` (``0`` = rides only the
                             best arteries). The primary ranking key under
                             :data:`~.concentration.PriorityMode.HARD_TIER`.
      * ``hhi``            — priority-weighted concentration in ``[0, 1]`` (higher is
                             better — 1.0 means one priority-0 route covers it all).
      * ``runs``           — the contiguous single-route stretches in travel order
                             (:class:`~.concentration.Run` each): the sub-routes.
      * ``route_ids``      — sorted distinct authored-route indices it stitches.
      * ``route_count``    — how many distinct authored routes are merged.
      * ``run_lengths``    — length of each run (in the active length mode), in order.
      * ``crossroad_hops`` — intersections crossed.
      * ``total_hops``     — number of edges.
    """

    def __init__(self, stops, hhi, runs, crossroad_hops, priority):
        self.stops = list(stops)
        self.priority = priority
        self.hhi = hhi
        self.runs = list(runs)
        self.route_ids = sorted({r.route_id for r in runs if isinstance(r.route_id, int)})
        self.route_count = len(self.route_ids)
        self.run_lengths = [r.length for r in runs]
        self.crossroad_hops = crossroad_hops
        self.total_hops = max(len(self.stops) - 1, 0)


class RouteFinder:
    """Finds diverse alternative routes over a fixed :class:`~.core.Graph`.

    Option 1 is the genuine best (highest concentration); each further option is a
    meaningfully different corridor, best-first. The tunables shape that
    diversity:

      * ``penalty_step``  — how much cost each reuse of an edge *adds* in the
                            edge-penalty diversity backfill (additive, in the
                            search's cost units). One transfer costs
                            :data:`~.search.TRANSFER_WEIGHT`.
      * ``max_overlap``    — reject a candidate sharing more than this fraction
                             of its own edges with any accepted route (0..1). This
                             is what forbids "changed one hop = second best".
      * ``max_stretch``    — reject alternatives whose stop count exceeds the best
                             route's by more than this factor.
    """

    def __init__(self, graph, penalty_step=TRANSFER_WEIGHT, max_overlap=0.6, max_stretch=2.5):
        self.graph = graph
        self.penalty_step = penalty_step
        self.max_overlap = max_overlap
        self.max_stretch = max_stretch
        self._avoid_cache = {}  # tier -> its avoid-penalty map (see :meth:`_avoid`)

    def find_routes(self, start, end, k=3, via=None):
        """Return up to ``k`` diverse :class:`Route` results, best first.

        ``via`` is an optional list of *required stops* the route must pass
        through (visited in an optimised order, alternatives kept tight so none
        detours around an already-short connection). "Best" is the route with the
        highest concentration — the one riding a single authored route furthest.

        ``k=None`` lifts the cap entirely, returning every diverse candidate the
        pool contains (still subject to ``max_overlap``/``max_stretch`` — not
        literally unbounded, just uncapped by count). This is effectively free
        compared to a small ``k``: the whole pool is generated and scored before
        ``k`` is ever consulted, so raising (or removing) the cap doesn't repeat
        any work — it only changes how many already-ranked results are kept.

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

        # No required stops -> plain point-to-point concentration search.
        if not waypoints:
            if start == end:
                return [self._make_route([start])]
            chains = self._bidirectional_chains(
                MinMergeStrategy(graph, start, end),
                MinMergeStrategy(graph, end, start),
            )
            return self._select_diverse(chains, k, self.max_stretch)

        # Required stops -> strict simple paths, tightly bounded. Try candidate
        # stop orders cheapest-first and keep the first order that yields a route.
        stretch = min(self.max_stretch, WAYPOINT_MAX_STRETCH)
        for points in self._ordered_point_lists(start, end, waypoints):
            chains = self._bidirectional_chains(
                WaypointStrategy(graph, points),
                WaypointStrategy(graph, points[::-1]),
            )
            routes = self._select_diverse(chains, k, stretch)
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
        """Intersections on ``nodes`` — counted over all nodes so it is the same
        whichever direction the route is walked (a deep, symmetric tiebreak)."""
        return sum(1 for node in nodes if self.graph.is_crossroad(node))

    def _make_route(self, nodes):
        """Wrap a stop chain in a scored :class:`Route` (exact concentration + tier).

        The tier is the worst priority among the sub-routes :func:`evaluate` credits
        (the chips the UI shows), so it is read straight off ``runs`` rather than
        recomputed — see :func:`~.concentration.tier`.
        """
        hhi, runs = evaluate(self.graph, nodes)
        priority = max((run.priority for run in runs), default=BEST_PRIORITY)
        return Route(nodes, hhi, runs, self._crossroad_hops(nodes), priority)

    def _bidirectional_chains(self, forward, reverse):
        """Candidate chains generated from *both* endpoints, unioned.

        The concentration objective is direction-independent, but the generators
        are not: a strategy returns the min-*transfer* path, and among equally
        biased paths its tie-break depends on the search direction, so searching
        from ``start`` and from ``end`` surface different corridors. Generating
        both ways (reversing the backward chains so they read ``start -> end``)
        makes the pool — and therefore the result and its score — the same
        whichever way the query is posed.
        """
        chains = self._generate(forward)
        chains += [chain[::-1] for chain in self._generate(reverse)]
        return self._dedup_chains(chains)

    @staticmethod
    def _dedup_chains(chains):
        """Drop chains that repeat an earlier one's edge set (order-independent)."""
        seen = set()
        unique = []
        for chain in chains:
            edges = frozenset(path_edges(chain))
            if edges not in seen:
                seen.add(edges)
                unique.append(chain)
        return unique

    def _generate(self, strategy):
        """Candidate stop chains for ``strategy``, deduped by edge set.

        The concentration objective's natural axis of diversity is the *dominant
        artery*, so the pool is: the unbiased best, one candidate per authored
        route biased to ride it (:func:`~.search.prefer_route_penalty`), the
        priority-aware corridors below, and an edge-penalty diversity backfill for
        extra corridors. Scoring/selection is left to :meth:`_select_diverse`.
        """
        graph = self.graph
        chains = []

        nodes, _ = strategy.find({})
        chains.append(nodes)

        for route_id in graph.route_ids():
            prefer = prefer_route_penalty(graph, route_id)
            nodes, _ = strategy.find(prefer)
            chains.append(nodes)

            # "Ride this artery, without crossing a road that can *only* be driven
            # as something worse-rated than it." The plain prefer() above fills the
            # gaps between stints on `route_id` with whatever is cheapest, which may
            # cross such a road — but only *sometimes*, so re-searching for every
            # artery unconditionally doubles the query for nothing. The constrained
            # search differs only if the chain we just got actually crosses an edge
            # the constraint would ban; otherwise it returns the same corridor, skip.
            floor = graph.route_priority(route_id)
            if nodes and self._crosses_forced_below(nodes, floor):
                nodes, _ = strategy.find(_add_penalties(prefer, self._avoid(floor)))
                chains.append(nodes)

        # One corridor per tier: the best route that never leaves it. Nothing else
        # in the pool has any reason to detour *around* a badly-rated artery, and
        # under HARD_TIER these are exactly the routes that win.
        for max_priority in range(graph.worst_priority()):
            nodes, _ = strategy.find(self._avoid(max_priority))
            chains.append(nodes)

        chains.extend(self._penalty_diversity(strategy))

        return self._dedup_chains(c for c in chains if c and len(c) >= 2)

    def _crosses_forced_below(self, nodes, floor):
        """Whether ``nodes`` crosses an edge the ``floor`` constraint would ban — an
        edge whose *best* available route is still worse-rated than ``floor``, so it
        can only be driven as something below it. Cheap (per-edge best), and exactly
        the condition under which :func:`~.search.avoid_priority_penalty` changes the
        search result."""
        return any(
            self.graph.edge_priority(a, b) > floor for a, b in zip(nodes, nodes[1:])
        )

    def _avoid(self, max_priority):
        """:func:`~.search.avoid_priority_penalty`, memoised per tier.

        The map depends only on the graph and the tier, but it is asked for once
        per artery *and* once per direction — rebuilding it over every edge each
        time is pure waste.
        """
        if max_priority not in self._avoid_cache:
            self._avoid_cache[max_priority] = avoid_priority_penalty(
                self.graph, max_priority
            )
        return self._avoid_cache[max_priority]

    def _penalty_diversity(self, strategy, rounds=6):
        """Iterative edge-penalty search yielding successive different corridors.

        Each route seen has its edges penalised (additively) so the next search is
        pushed somewhere new. A pure candidate *source* — no scoring or filtering.
        """
        penalty = {}
        for _ in range(rounds):
            nodes, _ = strategy.find(penalty)
            if not nodes or len(nodes) < 2:
                break
            for edge in path_edges(nodes):
                penalty[edge] = penalty.get(edge, 0.0) + self.penalty_step
            yield nodes

    def _select_diverse(self, chains, k, max_stretch):
        """Score the candidate chains and greedily pick up to ``k`` diverse routes.

        Sorted best-first by ``(tier, -hhi, route_count, crossroad_hops,
        total_hops)`` — the tier first (:data:`~.concentration.PriorityMode.
        HARD_TIER`), so a route that rides only well-rated arteries outranks one
        whose corridor rides a badly-rated one however much shorter it is; then highest
        concentration, then (among equally concentrated routes) fewest merged
        routes, fewest intersections, and shortest, with a final
        orientation-independent tie-break so the same corridor wins whichever way
        the query is posed. A candidate is kept only if it is neither a
        near-duplicate of an accepted route (``max_overlap`` of its edges) nor an
        excessive detour — more than ``max_stretch`` times the best route's stop
        count. If fewer than ``k`` distinct corridors exist, fewer are returned;
        near-duplicates never pad the list. ``k=None`` keeps every candidate that
        survives those checks, uncapped by count.

        Priority **ranks, it never filters**: the list stays complete, merely
        tier-ordered. So when the best tier holds only one distinct corridor, the
        alternatives fall through to worse tiers rather than the result list
        collapsing to a single route — you still get real alternatives, ordered so
        the clean one leads. (Callers surface :attr:`Route.priority` so a long
        tier-0 detour outranking a short tier-2 hop is *visible* rather than
        looking like a bug.)
        """
        routes = [self._make_route(nodes) for nodes in chains]
        routes.sort(
            key=lambda r: (
                r.priority if PriorityMode.HARD_TIER else 0,
                -r.hhi,
                r.route_count,
                r.crossroad_hops,
                r.total_hops,
                min(tuple(r.stops), tuple(r.stops[::-1])),  # canonical orientation
            )
        )
        if not routes:
            return []

        best_stops = len(routes[0].stops)  # the best route sets the length baseline
        accepted = []
        accepted_edges = []  # edge set per accepted route, parallel to ``accepted``
        for route in routes:
            if k is not None and len(accepted) >= k:
                break
            edges = frozenset(path_edges(route.stops))
            if any(edges == prior for prior in accepted_edges):
                continue
            if len(route.stops) > best_stops * max_stretch:
                continue  # too long a detour to be a useful alternative
            if any(
                len(edges & prior) / len(edges) > self.max_overlap
                for prior in accepted_edges
            ):
                continue
            accepted.append(route)
            accepted_edges.append(edges)

        return accepted
