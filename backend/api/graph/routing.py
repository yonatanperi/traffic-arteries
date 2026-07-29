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
  2. **Rank** — :meth:`RouteFinder.rank_candidates` scores each chain's exact
     concentration and sorts the pool once, best-concentration-first. This is the
     only expensive step, and it happens once per query.
  3. **Select** — :meth:`RouteFinder.select_diverse` walks that ranked pool with a
     *priority arena*: round 1 admits only tier-0 routes and picks the most
     concentrated diverse one; after yielding a route of priority ``X`` the next
     round admits priority ``≤ X + 1``. So a concentrated tier>0 corridor surfaces
     as an alternative once the arena opens to its tier, while the headline result
     stays the best tier-0 route. Selection is cheap and can run more than once
     over the one ranked pool (e.g. with and without an ``exclude`` set), which is
     how compromised-destination filtering avoids a second sort.

The priority-aware passes are skipped whenever no authored route is rated worse
than best (the common case), so the search costs exactly what it did before
priorities existed.

Call :meth:`RouteFinder.find_routes` for the rich results (stops + concentration +
which authored routes are merged) or :meth:`RouteFinder.k_shortest_paths` for
just the stop chains. :meth:`rank_candidates` + :meth:`select_diverse` are the
two-step form for callers (e.g. :func:`api.views.path`) that need to select more
than once over a single ranked pool.
"""

import itertools

from .concentration import LengthMode, PriorityMode, evaluate
from .core import BEST_PRIORITY, path_edges
from .search import (
    TRANSFER_WEIGHT,
    MinMergeStrategy,
    WaypointStrategy,
    avoid_priority_penalty,
    min_crossroad_distance,
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

# Length pressure on the ranking (see :meth:`RouteFinder._rank`). Concentration
# (HHI) is a *share-of-total* and so scale-free: a 50/50 split scores the same at
# 4 hops or 15, which lets a monster detour tie the obvious route on rounding
# noise. The ranking score multiplies HHI by ``(C_min / C) ** LENGTH_EXPONENT`` —
# a *gentle* preference for the shorter route among near-equally-concentrated
# ones. "Length" (:attr:`Route.crossroad_hops`) is whatever the active
# :class:`~.concentration.LengthMode` says it is — the same units
# :func:`~.concentration.evaluate` sums for the HHI itself, so this length term
# never tempers a score with a unit the score doesn't use. Under
# ``CROSSROADS_ONLY`` that's the crossroad distance, not the raw edge count, so a
# long transparent (shape-point) chain still counts as the one crossroad-to-
# crossroad hop it is. The exponent is deliberately small: concentration must
# stay dominant (a perfect single-artery corridor still beats a shorter
# fragmented one), so this only breaks ties HHI leaves scale-blind. Larger values
# start sacrificing real concentration for shortness.
LENGTH_EXPONENT = 0.15

# The relative quality floor for *alternatives* (see :meth:`select_diverse`). An
# alternative is only worth showing if its ranking score is at least this
# fraction of the headline's. Because the bar is *relative* to the #1 route it
# self-adapts: a perfect headline demands near-perfect alternatives (junk detours
# vanish), while a mediocre headline keeps its genuinely-comparable ones. The
# ranked pool is monotone, so with at most a few slots this single floor is also
# what trims a junk tail ("#1, #2 solid, #3 junk" is exactly q_3 < FLOOR * q_1).
ALTERNATIVE_FLOOR = 0.65


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
      * ``hhi``            — concentration in ``[0, 1]``: the plain Herfindahl
                             ``Σ (len_i / L)²`` over the sub-routes ridden (1.0 means
                             a single authored route covers the whole trip). *How well
                             the route rides one artery*, with no opinion on how that
                             artery is rated — **priority-free**, so re-prioritising an
                             authored route provably cannot move it. Priority is
                             expressed once, by the ``priority`` tier, instead of a
                             second time inside the score. Exactly the sum of the
                             squared per-sub-route shares the UI shows, since ``runs``
                             comes from the same solve.
      * ``runs``           — the contiguous single-route stretches in travel order
                             (:class:`~.concentration.Run` each): the sub-routes.
      * ``route_ids``      — sorted distinct authored-route indices it stitches.
      * ``route_count``    — how many distinct authored routes are merged.
      * ``run_lengths``    — length of each run (in the active length mode), in order.
      * ``crossroad_hops`` — the route's length, in the active
                             :class:`~.concentration.LengthMode` units (crossroads
                             crossed, or plain hop count) — the length term the
                             ranking score uses (see :meth:`RouteFinder._rank`).
      * ``total_hops``     — number of edges.
      * ``q``              — the *ranking* score: ``hhi`` tempered by a gentle
                             length preference (see :meth:`RouteFinder._rank`).
                             Defaults to ``hhi`` and is filled in once the pool's
                             minimum length is known — it is pool-relative, so a lone ``Route``
                             carries only its concentration. It drives the ordering
                             and the alternative floor, and is what the API reports
                             as the match % — so the number shown always agrees with
                             the order the results are shown in, and is free of
                             priority, which the tier reports on its own.
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
        self.q = hhi  # pool-relative ranking score; set by RouteFinder._rank


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

    def __init__(self, graph, penalty_step=TRANSFER_WEIGHT, max_overlap=0.85, max_stretch=2.5):
        self.graph = graph
        self.penalty_step = penalty_step
        self.max_overlap = max_overlap
        self.max_stretch = max_stretch
        self._avoid_cache = {}  # tier -> its avoid-penalty map (see :meth:`_avoid`)

    def find_routes(self, start, end, k=3, via=None, exclude=None):
        """Return up to ``k`` diverse :class:`Route` results, best first.

        ``via`` is an optional list of *required stops* the route must pass
        through (visited in an optimised order, alternatives kept tight so none
        detours around an already-short connection). "Best" is the route with the
        highest concentration — the one riding a single authored route furthest.

        ``exclude`` is an optional set of place names to keep out of every result
        (any route touching one is dropped) — a generic hook the caller uses for
        temporarily-unavailable destinations; the router itself stays oblivious to
        why a place is excluded.

        ``k=None`` lifts the cap entirely, returning every diverse candidate the
        pool contains (still subject to ``max_overlap``/``max_stretch`` — not
        literally unbounded, just uncapped by count). This is effectively free
        compared to a small ``k``: the whole pool is generated and scored before
        ``k`` is ever consulted, so raising (or removing) the cap doesn't repeat
        any work — it only changes how many already-ranked results are kept.

        This is the one-call convenience over :meth:`rank_candidates` +
        :meth:`select_diverse`; callers that select more than once over a single
        ranked pool should use those directly.

        Edge cases:
          * ``start == end`` (no ``via``) -> a single trivial ``Route([start])``
          * ``start``/``end``/``via`` absent from graph -> ``[]``
          * no connection / unreachable stop           -> ``[]``
        """
        ranked, stretch = self.rank_candidates(start, end, via=via)
        return self.select_diverse(ranked, k=k, max_stretch=stretch, exclude=exclude)

    def rank_candidates(self, start, end, via=None):
        """Generate and score this query's candidate pool, sorted once.

        Returns ``(ranked, max_stretch)``: the scored :class:`Route` objects
        best-concentration-first, and the stretch bound :meth:`select_diverse`
        should apply (tighter when ``via`` stops are required). This is the
        expensive step — generation, exact scoring, and the single sort — so a
        caller that needs several selections (e.g. with and without an exclusion
        set) does it once and hands ``ranked`` to :meth:`select_diverse` repeatedly.

        Edge cases mirror :meth:`find_routes`: an unknown endpoint/stop or no
        connection yields an empty pool; ``start == end`` (no ``via``) yields the
        single trivial ``Route([start])``.
        """
        graph = self.graph
        waypoints = self._normalise_waypoints(start, end, via)

        if start not in graph or end not in graph:
            return [], self.max_stretch
        if any(stop not in graph for stop in waypoints):
            return [], self.max_stretch

        # No required stops -> plain point-to-point concentration search.
        if not waypoints:
            if start == end:
                return [self._make_route([start])], self.max_stretch
            chains = self._bidirectional_chains(
                MinMergeStrategy(graph, start, end),
                MinMergeStrategy(graph, end, start),
            )
            return self._rank(chains, [start, end]), self.max_stretch

        # Required stops -> leg-wise simple paths, tightly bounded. Try candidate
        # stop orders cheapest-first and keep the first order that yields a pool.
        stretch = min(self.max_stretch, WAYPOINT_MAX_STRETCH)
        for points in self._ordered_point_lists(start, end, waypoints):
            chains = self._bidirectional_chains(
                WaypointStrategy(graph, points),
                WaypointStrategy(graph, points[::-1]),
            )
            ranked = self._rank(chains, points)
            if ranked:
                return ranked, stretch

        return [], stretch

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

    def _min_crossroad_distance(self, points):
        """The ranking score's length reference: the shortest a route through
        ``points`` (``[start, *required stops, end]``) could possibly be, in the
        active :class:`~.concentration.LengthMode` units.

        Chains :func:`~.search.min_crossroad_distance` leg by leg. Under
        ``CROSSROADS_ONLY`` a required stop sits on two legs and so is counted
        twice, hence the correction — which keeps this a genuine lower bound on
        :meth:`_crossroad_hops` of any candidate visiting the points in this order,
        and therefore keeps the length factor in ``(0, 1]``. Off that mode each leg
        is plain hop distance, which concatenates across legs with no double-count
        to correct for. Returns ``0`` when a leg is unreachable, which :meth:`_rank`
        reads as "no length adjustment" rather than dividing by nothing.
        """
        total = 0
        for a, b in zip(points, points[1:]):
            leg = min_crossroad_distance(self.graph, a, b)
            if leg is None:
                return 0
            total += leg
        if LengthMode.CROSSROADS_ONLY:
            for stop in points[1:-1]:
                if self.graph.is_crossroad(stop):
                    total -= 1
        return max(total, 0)

    def _crossroad_hops(self, nodes):
        """``nodes``' length for the ranking reference, in the active
        :class:`~.concentration.LengthMode` units — the same units
        :func:`~.concentration.evaluate` sums for the HHI, so the ranking's length
        term never tempers a score with a unit the score doesn't use.

        Under ``CROSSROADS_ONLY`` this is intersections crossed, counted over all
        nodes so it is the same whichever direction the route is walked (a deep,
        symmetric tiebreak); otherwise it's the plain hop count.
        """
        if not LengthMode.CROSSROADS_ONLY:
            return max(len(nodes) - 1, 0)
        return sum(1 for node in nodes if self.graph.is_crossroad(node))

    def _make_route(self, nodes):
        """Wrap a stop chain in a scored :class:`Route` (exact concentration + tier).

        The tier is the worst priority among the sub-routes :func:`evaluate` credits
        (the chips the UI shows), so it is read straight off ``runs`` rather than
        recomputed — see :func:`~.concentration.tier`.

        One solve answers both: :func:`~.concentration.evaluate` maximises the plain
        concentration and uses priority only to break ties between equally
        concentrated readings, so the score, the ``runs`` and their shares are all
        priority-free while the tier still names the arteries actually ridden.
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
        extra corridors. Scoring/selection is left to :meth:`select_diverse`.
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

    def _rank(self, chains, points):
        """Score each candidate chain and sort the pool once, concentration-first.

        The single expensive ordering step. Each route's ranking score ``q`` is its
        concentration tempered by a gentle crossroad-distance preference::

            q = hhi * (C_min / C) ** LENGTH_EXPONENT

        where ``C`` is the route's length (:attr:`Route.crossroad_hops`, in the active
        :class:`~.concentration.LengthMode` units) and ``C_min`` the shortest *any*
        route through ``points`` could be in those same units
        (:func:`~.search.min_crossroad_distance`, chained over the required stops). So
        the factor is ``1.0`` for a route that detours not at all and ``< 1`` in
        proportion to how far round it goes. This is what stops HHI's scale-freeness
        from ranking a monster detour above the obvious route when they tie on
        concentration; the small exponent keeps concentration dominant.

        ``C_min`` is deliberately a property of the *network*, not of the candidate
        pool. A pool minimum would be cheaper, but generating candidates depends on
        priority (there is a pass per tier), so re-rating an artery could change the
        pool's shortest member and rescale every reported match % with it — the exact
        surprise this score is meant to avoid. Note the choice is invisible to the
        ordering either way: ``C_min`` is one factor common to the whole pool, so it
        cancels out of both the sort and :meth:`select_diverse`'s relative floor, and
        only sets the scale the percentages are reported on.

        The base :attr:`Route.hhi` is the **priority-free** concentration: ``q``
        measures *how well the route rides one artery*, and re-rating an authored
        route must not move it. Priority is expressed once, by the tier gate below,
        instead of leaking a second time into the score — and since ``q`` is also the
        reported match %, that keeps the number stable when a priority is edited. The
        priority weights still do their own job upstream, inside
        :meth:`_make_route`'s other solve: they pick the credit assignment, so an edge
        served by both a good and a bad route is credited to the good one, and the
        tier reads that assignment.

        The sort key is ``(-q, route_count, crossroad_hops, total_hops, canonical
        orientation)``: best ranking score first, then (among equal ``q``) fewest
        merged routes, fewest intersections, shortest, and a final
        orientation-independent tie-break so the same corridor sorts the same way
        whichever direction the query is posed. Priority is deliberately **not** in
        this key — the tier gate belongs to :meth:`select_diverse`'s arena, so one
        ranked pool can be selected over with different priority behaviour without
        re-sorting.
        """
        routes = [self._make_route(nodes) for nodes in chains]
        min_cross = self._min_crossroad_distance(points)
        for r in routes:
            # No adjustment when either distance is 0 (nothing between these places
            # crosses a junction at all — a tiny or purely linear stretch of the
            # network), mirroring evaluate()'s L == 0 branch.
            if min_cross and r.crossroad_hops:
                r.q = r.hhi * (min_cross / r.crossroad_hops) ** LENGTH_EXPONENT
        routes.sort(
            key=lambda r: (
                -r.q,
                r.route_count,
                r.crossroad_hops,
                r.total_hops,
                min(tuple(r.stops), tuple(r.stops[::-1])),  # canonical orientation
            )
        )
        return routes

    def select_diverse(self, ranked, k=None, max_stretch=None, exclude=None):
        """Pick up to ``k`` diverse routes from a pre-ranked pool via priority arenas.

        ``ranked`` is a concentration-first list from :meth:`rank_candidates` /
        :meth:`_rank`. Selection is a cheap greedy walk, so it can run several
        times over one ranked pool (the whole point of splitting it from ranking).

        **Priority arena.** Under :data:`~.concentration.PriorityMode.HARD_TIER`,
        each round has an arena ``X``: only candidates with ``priority <= X`` are
        eligible, and the most concentrated diverse one among them is taken. Round
        one's arena is ``0`` (so the headline result is the best tier-0 route);
        after a round fills slot ``i`` with a route of priority ``X`` the next arena
        is ``max(i + 1, X + 1)``. The ``X + 1`` term lets a deeper pick open the
        arena beyond itself; the ``i + 1`` (slot-index) term guarantees the arena
        widens by at least one tier per slot regardless, so slot ``i`` can always
        reach tier ``i`` even after a run of same-tier picks. A concentrated tier>0
        corridor therefore surfaces as an alternative once its slot is deep enough or
        a prior pick has opened the tier, whichever comes first. If no candidate is
        eligible at the current arena (a tier is absent, or none exists at ``0``),
        the arena jumps to the cheapest priority still present rather than the list
        collapsing. With ``HARD_TIER`` off, arenas are skipped and selection is
        plain concentration-first.

        Priority **ranks, it never filters**: the pool stays complete, merely
        arena-ordered, so you still get real alternatives — ordered so the clean
        one leads. (Callers surface :attr:`Route.priority` so a long tier-0 route
        outranking a short tier>0 one is *visible* rather than looking like a bug.)

        A candidate is kept only if it is neither a near-duplicate of an accepted
        route (``max_overlap`` of its edges) nor an excessive detour — more than
        ``max_stretch`` times the best route's stop count — nor below the relative
        quality floor: an alternative whose ranking score is under
        :data:`ALTERNATIVE_FLOOR` of the headline's is dropped as not worth showing.
        The headline is always kept, and the floor is measured against *this pass's*
        headline, so a perfect #1 leaves only near-perfect alternatives while a
        mediocre #1 keeps its comparable ones. ``exclude`` is a set of place names;
        any candidate touching one is dropped from the pool up front, so the arena,
        the floor, and the diversity budget are all computed among the routes that
        can actually be shown. ``k=None`` keeps every survivor, uncapped by count.
        """
        if not ranked:
            return []
        if max_stretch is None:
            max_stretch = self.max_stretch
        hard = PriorityMode.HARD_TIER

        # The eventual #1 (best under the full priority-first key) sets the length
        # baseline — a `min` scan, not a second sort.
        best = min(
            ranked,
            key=lambda r: (
                r.priority if hard else 0,
                -r.q,
                r.route_count,
                r.crossroad_hops,
                r.total_hops,
                min(tuple(r.stops), tuple(r.stops[::-1])),
            ),
        )
        best_stops = len(best.stops)

        accepted = []
        accepted_edges = []  # edge set per accepted route, parallel to ``accepted``

        def passes(route, edges):
            # Relative quality floor: an alternative is only worth showing if its
            # ranking score is within ALTERNATIVE_FLOOR of this pass's headline
            # (``accepted[0]`` — the route actually shown as #1, so the two
            # selection passes each floor against their own leader). The headline
            # itself is always kept (nothing accepted yet).
            if accepted and route.q < ALTERNATIVE_FLOOR * accepted[0].q:
                return False
            if any(edges == prior for prior in accepted_edges):
                return False
            if len(route.stops) > best_stops * max_stretch:
                return False  # too long a detour to be a useful alternative
            if edges and any(
                len(edges & prior) / len(edges) > self.max_overlap
                for prior in accepted_edges
            ):
                return False
            return True

        remaining = [
            r for r in ranked if not (exclude and exclude.intersection(r.stops))
        ]

        if not hard:
            for route in remaining:
                if k is not None and len(accepted) >= k:
                    break
                edges = frozenset(path_edges(route.stops))
                if passes(route, edges):
                    accepted.append(route)
                    accepted_edges.append(edges)
            return accepted

        # Priority-arena walk. ``remaining`` stays concentration-ordered, so the
        # first eligible (priority <= arena) candidate that passes is the most
        # concentrated one in the arena.
        arena = 0
        while remaining and (k is None or len(accepted) < k):
            picked = picked_edges = None
            for route in list(remaining):
                if route.priority > arena:
                    continue  # not in this arena yet; keep for a later, wider one
                edges = frozenset(path_edges(route.stops))
                if passes(route, edges):
                    picked, picked_edges = route, edges
                    break
                remaining.remove(route)  # a greedy reject can never pass later
            if picked is None:
                # Nothing eligible at this arena: open it to the cheapest tier
                # still present rather than stopping short.
                beyond = [r.priority for r in remaining if r.priority > arena]
                if not beyond:
                    break
                arena = min(beyond)
                continue
            accepted.append(picked)
            accepted_edges.append(picked_edges)
            remaining.remove(picked)
            # Next arena widens by at least one tier per slot: ``max(slot index,
            # picked.priority + 1)``. ``len(accepted)`` is the just-filled count and
            # so the 0-based index of the next slot, which floors the arena — so slot
            # ``i`` can always reach tier ``i`` even after a run of same-tier picks,
            # while a deeper pick still opens the arena the usual +1 beyond itself.
            arena = max(len(accepted), picked.priority + 1)

        return accepted
