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
  3. **Refine** — a one-artery bias fills everything around its stint with the
     *shortest* filler rather than the most concentrated one, so a corridor whose
     optimum is two long arteries in sequence is never proposed by any single pass.
     :meth:`RouteFinder._artery_pair_chains` searches the leading arteries two at a
     time to close exactly that gap, and the few new chains are scored and merged
     into the pool. It needs round 2's scores to know which arteries to combine,
     which is why generation is two rounds and not one.
  4. **Select** — :meth:`RouteFinder.select_diverse` walks that ranked pool with a
     *priority arena*: round 1 admits only tier-0 routes and picks the most
     concentrated diverse one; after yielding a route of priority ``X`` the next
     round admits priority ``≤ X + 1``. So a concentrated tier>0 corridor surfaces
     as an alternative once the arena opens to its tier, while the headline result
     stays the best tier-0 route. Selection is cheap and can run more than once
     over the one ranked pool (e.g. with and without an ``exclude`` set), which is
     how compromised-destination filtering avoids a second sort.

**Required stops split the problem.** A ``via`` stop is a place the trip actually
stops at, so the trip is several trips: :meth:`RouteFinder._leg_ranked_pool` runs the
four steps above once per *leg* — the stretch between two consecutive required stops —
and combines the per-leg pools into whole routes, whose concentration is the
length-weighted mean of their legs' (:meth:`RouteFinder._combine_legs`). Everything
downstream — the arena, the floors, the diversity budgets — is blind to the split, and
a query with no ``via`` is a one-leg trip scored by the identical formula.

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
from collections import namedtuple

from .concentration import LengthMode, PriorityMode, evaluate
from .core import BEST_PRIORITY, path_edges
from .search import (
    TRANSFER_WEIGHT,
    MinMergeStrategy,
    PenalisedStrategy,
    add_penalties,
    avoid_places_penalty,
    avoid_priority_penalty,
    min_crossroad_distance,
    prefer_route_penalty,
    single_source_costs,
)

# Above this many required stops the permutation count (n!) makes exhaustive
# order optimisation impractical, so we fall back to the caller's order.
MAX_OPTIMIZED_WAYPOINTS = 7

# Safety valve on the leg-combination pool (see :meth:`RouteFinder._rank_leg_
# combinations`). The real bound is :meth:`RouteFinder.select_diverse` itself, run per
# leg: its arena, overlap budget and :data:`ALTERNATIVE_FLOOR` cut a raw leg pool of
# dozens down to a median of 3 candidates (max 12) on the live network, so the product
# lands at a median of 6 for one required stop and 38 for three (worst seen: 400).
# This is not a tuning knob for that — it only stops eight legs (the
# :data:`MAX_OPTIMIZED_WAYPOINTS` ceiling) from multiplying out, the way a state cap
# used to guard the single monolithic waypoint search.
MAX_LEG_COMBINATIONS = 2_000

# How many arteries the pair pass combines (see :meth:`RouteFinder._artery_pair_chains`):
# the dominant artery of each of the best this-many *distinct*-artery candidates,
# tried two at a time. Measured over 50 random queries on the live network, against
# the one-artery pool alone: 2 seeds already lift the top-3 in 36 of them for +1%
# query time, 3 lift 37 for +3%, and 4 and 5 buy exactly one more hit for +6% and
# +10%. The curve is flat past 3, so 3 is where it stops paying — not a guess, and
# worth re-measuring if generation changes.
PAIR_SEED_ARTERIES = 3

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
LENGTH_EXPONENT = 0.5

# The relative quality floor for *alternatives* (see :meth:`select_diverse`). An
# alternative is only worth showing if its ranking score is at least this
# fraction of the headline's. Because the bar is *relative* to the #1 route it
# self-adapts: a perfect headline demands near-perfect alternatives (junk detours
# vanish), while a mediocre headline keeps its genuinely-comparable ones. The
# ranked pool is monotone, so with at most a few slots this single floor is also
# what trims a junk tail ("#1, #2 solid, #3 junk" is exactly q_3 < FLOOR * q_1).
ALTERNATIVE_FLOOR = 0.65


def _rank_key(route):
    """The pool's sort key: best ranking score first, then fewest merged routes,
    fewest intersections, shortest, and an orientation-independent tie-break so the
    same corridor sorts the same way whichever direction the query is posed. See
    :meth:`RouteFinder._rank` for why priority is deliberately absent.
    """
    return (
        -route.q,
        route.route_count,
        route.crossroad_hops,
        route.total_hops,
        min(tuple(route.stops), tuple(route.stops[::-1])),  # canonical orientation
    )


# One leg of a result: the stretch between two consecutive *required* stops (for a
# query with no ``via`` there is exactly one leg, spanning the whole route).
#   * ``start_index`` / ``end_index`` — inclusive node indices into ``Route.stops``.
#     Adjacent legs share their boundary node — the required stop itself.
#   * ``hhi``      — this leg's own concentration, scored on its own by
#                    :func:`~.concentration.evaluate`. The route's ``hhi`` is the
#                    length-weighted mean of these (see :meth:`RouteFinder._combine_legs`).
#   * ``priority`` — this leg's tier: the worst mark its own runs complete.
#   * ``runs``     — this leg's slice of ``Route.runs``, in travel order.
Leg = namedtuple("Leg", "start_index end_index hhi priority runs")


class Route:
    """One result route: the stop chain plus how well it rides one good artery.

      * ``stops``          — full place-name chain (consecutive pairs are edges).
                             A chain may repeat a place: a required stop hanging off
                             a junction is left by driving back out through it.
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
      * ``length``         — ``Σ run.length``: the same length notion measured over
                             the runs rather than the nodes. This is what weights a
                             leg in the trip's concentration.
      * ``legs``           — the stretches between consecutive required stops
                             (:class:`Leg` each), **always at least one**. Without
                             ``via`` there is exactly one leg spanning the whole
                             chain, so every caller has a single shape to read.
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

    def __init__(self, stops, hhi, runs, crossroad_hops, priority, legs=None):
        self.stops = list(stops)
        self.priority = priority
        self.hhi = hhi
        self.runs = list(runs)
        self.route_ids = sorted({r.route_id for r in runs if isinstance(r.route_id, int)})
        self.route_count = len(self.route_ids)
        self.run_lengths = [r.length for r in runs]
        self.length = sum(self.run_lengths)
        self.crossroad_hops = crossroad_hops
        self.total_hops = max(len(self.stops) - 1, 0)
        self.legs = list(legs) if legs else [
            Leg(0, self.total_hops, hhi, priority, list(self.runs))
        ]
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
            ranked = self._ranked_pool(
                MinMergeStrategy(graph, start, end),
                MinMergeStrategy(graph, end, start),
                [start, end],
            )
            return ranked, self.max_stretch

        # Required stops -> one search per leg, combined. Try candidate stop orders
        # cheapest-first and keep the first order that yields a pool.
        stretch = min(self.max_stretch, WAYPOINT_MAX_STRETCH)
        for points in self._ordered_point_lists(start, end, waypoints):
            ranked = self._leg_ranked_pool(points)
            if ranked:
                return ranked, stretch

        return [], stretch

    def _leg_ranked_pool(self, points):
        """The ranked pool for ``[start, *required stops, end]``, leg by leg.

        A required stop is not a hint, it is a place the trip actually stops at — so
        the trip *is* several trips, and each stretch between two consecutive stops is
        its own routing problem: generated on its own (:meth:`_leg_candidates`), scored
        on its own, and only then combined (:meth:`_rank_leg_combinations`).

        This is the whole fix for the corridor a monolithic waypoint search could not
        reach. The whole-sequence search this replaces minimised node revisits
        *lexicographically first*, ahead of transfers, hops and every penalty in the
        map — so where a required stop hangs off a junction as a spur, it would never
        propose backing out of that junction while any non-retracing corridor existed,
        however much worse that corridor was. Searching a leg at a time makes retracing
        across a stop boundary free at generation time (the leg that leaves the spur
        knows nothing about the leg that arrived), and the ranking then judges it like
        every other corridor.

        The one thing a leg is *not* free to do is collect another leg's required stop,
        which :meth:`_leg_candidates` keeps it off.

        Returns ``[]`` if any leg is unroutable, which is the caller's signal to try
        the next stop order.
        """
        stops = points[1:-1]  # the required stops; the trip's own ends are not "stops"
        pools = []
        for a, b in zip(points, points[1:]):
            pool = self._leg_candidates(a, b, [p for p in stops if p not in (a, b)])
            if not pool:
                return []
            pools.append(pool)
        return self._rank_leg_combinations(pools, points)

    def _leg_candidates(self, a, b, banned):
        """One leg's candidates — *literally* the two steps a plain query takes.

        A leg is a point-to-point query, so it is answered by the same pair of calls
        :meth:`rank_candidates` makes for one: :meth:`_ranked_pool` to generate and
        score, then :meth:`select_diverse` to pick. Reusing that second method rather
        than re-deriving a cheaper filter here is what makes the **priority arena**
        hold for a leg exactly as it holds for a whole route — round one admits only
        tier-0 candidates, so a leg always contributes its best clean corridor, and
        the wider arenas then add its downgraded ones.

        Picking a leg by concentration alone breaks the arena's one guarantee before
        the arena ever runs: where a leg's *most concentrated* corridor is the
        downgraded one, the clean corridor is the poorer-scoring candidate and is
        dropped, so the trip can only be assembled at the worse tier — even though a
        tier-0 trip exists (:class:`~api.tests.LegPriorityArenaTests`). Selecting the
        same way at both levels also inherits ``max_overlap`` and
        :data:`ALTERNATIVE_FLOOR` for free — which is what keeps the cartesian product
        in :meth:`_rank_leg_combinations` small without a candidate-count knob — and
        makes both levels track :data:`~.concentration.PriorityMode.HARD_TIER`
        together, so turning the tier gate off is priority-blind end to end.

        ``banned`` is the trip's *other* required stops. A leg that drives through one
        collects a stop belonging to another leg, which makes the ordered visit
        meaningless and leaves that leg doubling back over ground already driven;
        keeping each leg to its own stop is the rule the old whole-sequence waypoint
        search enforced internally (a required stop was only enterable as the current
        target). Two deliberate limits on it:

          * It is a **soft** ban — :func:`~.search.avoid_places_penalty` added to every
            search by :class:`~.search.PenalisedStrategy` — not a deletion. A required
            stop is often a transparent degree-2 point in the middle of a road, and
            deleting it severs the road rather than routing around it, so the leg comes
            back with a corridor far worse than the one it would have found and the
            whole trip is downgraded with it. Softly banned, the search goes round the
            stop when it can and through it when there is no other way, which also
            means the ban can never make a leg unroutable.
          * It covers the required *stops* only, never the trip's own start and end. A
            leg driving back through the trip's start is the ordinary shape of
            collecting a stop that lies off to one side — you drive out to it and back
            the way you came — and it is the exact mirror of a leg driving through the
            destination, so no orientation-independent rule can forbid one and keep the
            other. Both are judged on the score, like every other corridor.

        Because nothing is removed, generation and scoring both run on ``self.graph``.
        A sub-graph would have different degrees, and therefore a different
        :func:`~.concentration.edge_unit`, and therefore a different meaning for a
        run's length — which every leg's ``hhi`` has to share for the weighted mean in
        :meth:`_combine_legs` to mean anything.
        """
        avoid = avoid_places_penalty(self.graph, banned)
        return self.select_diverse(
            self._ranked_pool(
                PenalisedStrategy(MinMergeStrategy(self.graph, a, b), avoid),
                PenalisedStrategy(MinMergeStrategy(self.graph, b, a), avoid),
                [a, b],
            )
        )

    def _rank_leg_combinations(self, pools, points):
        """Combine the per-leg pools into whole-route candidates and sort once.

        Every way of picking one candidate per leg is a route, so the pool is the
        cartesian product — already bounded by :meth:`_leg_candidates`'s use of
        :meth:`select_diverse`, with :data:`MAX_LEG_COMBINATIONS` as the valve for the
        many-legged tail. Trimming takes the *weakest* tail of the *largest* pool.
        Because each leg arrives in arena order — its clean corridor first, its
        downgraded ones behind — that tail is the worst-tiered candidates, and no leg
        is ever reduced below its own best.

        The combined routes go on to the unchanged :meth:`select_diverse` — same arena,
        same floor, same overlap and stretch budgets — so everything after this point
        is blind to whether a query had required stops.
        """
        pools = [list(pool) for pool in pools]
        total = 1
        for pool in pools:
            total *= len(pool)
        while total > MAX_LEG_COMBINATIONS:
            largest = max(range(len(pools)), key=lambda i: len(pools[i]))
            if len(pools[largest]) < 2:
                break  # every leg is down to its best; the product is as small as it gets
            total = total // len(pools[largest]) * (len(pools[largest]) - 1)
            pools[largest] = pools[largest][:-1]
        routes = [self._combine_legs(combo) for combo in itertools.product(*pools)]
        self._apply_ranking_score(routes, points)
        routes.sort(key=_rank_key)
        return routes

    def _combine_legs(self, leg_routes):
        """Stitch one candidate per leg into a whole-route :class:`Route`.

        **The trip's concentration is the length-weighted mean of its legs'**::

            hhi = Σ_i (L_i / L) · hhi_i        L_i = leg i's length, L = Σ L_i

        Expanded that is ``Σ_i Σ_r len_ir² / (L_i · L)``, against the undivided
        route's ``Σ_r (Σ_i len_ir)² / L²`` — a *block-diagonal* Herfindahl, in which
        credit pools within a leg but never across a required stop. Which is what a
        required stop means: the driver stops there, so riding one artery into it and
        a different one out of it is not a compromise to be scored down, it is two
        journeys each done well. Scoring the chain undivided is what ranked the
        reported bug's fragmented 27-hop corridor above the 24-hop one that rides a
        single artery out of the stop.

        With one leg this is the identity ``L_1 / L = 1``, so a query with no ``via``
        is scored by the very same code and formula it always was.

        ``L == 0`` — a trip crossing no crossroad at all, reachable only under
        ``CROSSROADS_ONLY`` — falls back to the plain mean, mirroring
        :func:`~.concentration.evaluate`'s own zero-length branch. It must not be a
        weighted mean there: a zero-length leg would carry zero weight, which lets a
        route that wanders off through transparent nodes score as if that stretch
        weren't part of the trip.
        """
        chain = list(leg_routes[0].stops)
        legs, runs, offset = [], [], 0
        for route in leg_routes:
            if legs:
                chain += route.stops[1:]  # adjacent legs share the required stop
            start_index, offset = offset, offset + route.total_hops
            legs.append(Leg(start_index, offset, route.hhi, route.priority, list(route.runs)))
            runs += route.runs
        total = sum(route.length for route in leg_routes)
        if total:
            hhi = sum(route.length / total * route.hhi for route in leg_routes)
        else:
            hhi = sum(route.hhi for route in leg_routes) / len(leg_routes)
        priority = max((run.priority for run in runs), default=BEST_PRIORITY)
        return Route(chain, hhi, runs, self._crossroad_hops(chain), priority, legs)

    def _ranked_pool(self, forward, reverse, points):
        """The whole ranked pool for one point sequence: generate, rank, refine, re-rank.

        Two rounds, because the second one needs the first one's answer to know what
        to try: :meth:`_generate` biases toward one artery at a time, and only once
        those are scored is it clear which arteries actually carry a corridor here —
        which is what :meth:`_artery_pair_chains` combines. The refinement round is
        scored on its own and merged, never re-solving round one.
        """
        ranked = self._rank(self._bidirectional_chains(forward, reverse), points)
        if not ranked:
            return ranked
        extra = self._artery_pair_chains(forward, reverse, ranked)
        if extra:
            ranked.extend(self._score(extra, points))
            ranked.sort(key=_rank_key)
        return ranked

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
        (the chips the UI shows) — each run's being the worst mark it *completes* —
        so it is read straight off ``runs`` rather than recomputed via
        :func:`~.concentration.tier`, which would cost a second, redundant solve.

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
                nodes, _ = strategy.find(add_penalties(prefer, self._avoid(floor)))
                chains.append(nodes)

        # One corridor per tier: the best route that never leaves it. Nothing else
        # in the pool has any reason to detour *around* a badly-rated artery, and
        # under HARD_TIER these are exactly the routes that win.
        for max_priority in range(graph.worst_priority()):
            nodes, _ = strategy.find(self._avoid(max_priority))
            chains.append(nodes)

        chains.extend(self._penalty_diversity(strategy))

        return self._dedup_chains(c for c in chains if c and len(c) >= 2)

    def _artery_pair_chains(self, forward, reverse, ranked):
        """Chains biased toward **two** arteries at once — the corridor no
        one-artery pass can generate.

        :func:`~.search.prefer_route_penalty` charges the same
        :data:`~.search.TRANSFER_WEIGHT` for one off-artery edge as the search
        charges for one route transfer. So while the *stint* on the preferred
        artery comes out right, everything around it is filled by whatever is
        **shortest**, not by whatever is most concentrated: a filler that rides one
        artery four edges further loses to a fragmented one that saves four edges.
        A corridor whose optimum is two long arteries in sequence therefore never
        appears in the pool — each artery's own pass pairs it with the cheap filler
        and neither pass ever proposes the two together. (Live example: ``מחסום
        בזק → צאלים via צ. רבדים``, where riding *מחסום בזק - כביש 6* into *כביש 6
        - נחל עוז* beats everything one-artery biasing produces, and only shows up
        when a required stop happens to pin the first half.)

        Stacking both arteries' penalties fixes it directly: an edge on either one
        is charged nothing, an edge on neither is charged twice, so the search rides
        one into the other and neither has to be the filler. The pairs worth trying
        are read off round one — the dominant artery of each of the best
        :data:`PAIR_SEED_ARTERIES` distinct-artery candidates, i.e. the arteries
        already proven to carry a real corridor between these places, which is why
        this cannot run before round one is scored.
        """
        graph = self.graph
        seen = {frozenset(path_edges(route.stops)) for route in ranked}
        chains = []
        for a, b in itertools.combinations(self._leading_arteries(ranked), 2):
            penalty = add_penalties(
                prefer_route_penalty(graph, a), prefer_route_penalty(graph, b)
            )
            for strategy, backwards in ((forward, False), (reverse, True)):
                nodes, _ = strategy.find(penalty)
                if not nodes or len(nodes) < 2:
                    continue
                if backwards:
                    nodes = nodes[::-1]
                edges = frozenset(path_edges(nodes))
                if edges not in seen:  # the pair usually re-finds a corridor we have
                    seen.add(edges)
                    chains.append(nodes)
        return chains

    @staticmethod
    def _leading_arteries(ranked, limit=PAIR_SEED_ARTERIES):
        """The dominant arteries of the best ``limit`` candidates that don't repeat one.

        "Dominant" is the longest run — the artery the candidate mostly *is*.
        Walking the ranked pool and skipping repeats is what makes these ``limit``
        genuinely different arteries rather than one artery's near-duplicates.
        """
        arteries = []
        for route in ranked:
            if not route.runs:
                continue
            artery = max(route.runs, key=lambda run: run.length).route_id
            if artery not in arteries:
                arteries.append(artery)
                if len(arteries) == limit:
                    break
        return arteries

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

        With required stops, ``hhi`` is the legs' length-weighted mean rather than one
        undivided Herfindahl (:meth:`_combine_legs`), and ``C_min`` is already chained
        leg by leg (:meth:`_min_crossroad_distance`) — so both halves of the formula
        measure the same divided trip. Nothing else here changes, and with one leg both
        reduce to what they always were.

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
        routes = self._score(chains, points)
        routes.sort(key=_rank_key)
        return routes

    def _score(self, chains, points):
        """Score chains into :class:`Route` objects with their ``q`` filled in, unsorted.

        Split out of :meth:`_rank` so a later pass can *extend* an already-ranked
        pool (see :meth:`_artery_pair_chains`) by scoring only its own new chains
        and re-sorting, instead of re-running :func:`~.concentration.evaluate` over
        candidates that were already solved. Safe precisely because ``q``'s length
        reference is the network's ``C_min``, not the pool's: a route's score does
        not depend on what else is in the pool, so scores computed in two rounds
        are directly comparable.
        """
        return self._apply_ranking_score(
            [self._make_route(nodes) for nodes in chains], points
        )

    def _apply_ranking_score(self, routes, points):
        """Fill in each route's ``q`` — its ``hhi`` tempered by the length term.

        Split out of :meth:`_score` because the leg-combination pool builds its
        :class:`Route` objects a different way (:meth:`_combine_legs`) but must be
        scored on exactly the same scale, against the same ``C_min`` chained over
        ``points``.
        """
        min_cross = self._min_crossroad_distance(points)
        for r in routes:
            # No adjustment when either distance is 0 (nothing between these places
            # crosses a junction at all — a tiny or purely linear stretch of the
            # network), mirroring evaluate()'s L == 0 branch.
            if min_cross and r.crossroad_hops:
                r.q = r.hhi * (min_cross / r.crossroad_hops) ** LENGTH_EXPONENT
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
