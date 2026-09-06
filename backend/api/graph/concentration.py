"""Route *concentration* scoring — the search objective.

"Best" is the route that **rides one good authored route as far as possible**. The
objective has two levels, and they answer different questions:

**1. The tier** (:func:`tier`) — *may* we ride this corridor at all? An authored
route may carry **priority marks**: rated stretches of it (``0`` = best … ``3`` =
worst), each drawn by the author over a range of that route's stops. A route's tier
is the worst priority among the marks it **rides whole** (:func:`ridden_marks`): a
mark counts when the chain covers its stretch end to end, on the marked route's own
edges. Riding part of a rated stretch is deliberately free, because where the line
falls between "brushed past it" and "rode it" is the author's knowledge, expressed
by how the mark is drawn, and not a length heuristic's guess. Ranking is
lexicographic on the tier first (:data:`PriorityMode.HARD_TIER`), so a route that
rides no bad mark beats one whose concentrated corridor rides one *however long the
detour*.

**A mark rates the road, not the reading of it.** Whether it bites is decided by the
edges the chain covers, before and independently of the credit assignment below —
so a stretch cannot shed its rating by being handed to an artery that co-serves the
same edges and carries no mark, nor by a transfer dropped inside it, nor by a
required stop that cuts it in two. (Marks live on routes only because that is how an
author draws one; where two authored routes overlap, marking either rates the road
for both.) Contrast :meth:`~.core.Graph.edge_priority`, the per-edge best the
generators hunt with, which counts an edge merely *inside* a mark as rated.

**2. The score** (:func:`evaluate`) — *how well* does it ride them? For a route split
into maximal contiguous runs ``r_1 … r_n``, each on a single authored route, we take
the Herfindahl index of how its length is distributed across those runs::

    score = Σ_i  ( len(r_i) / Σ_j len(r_j) )²

That is ``1.0`` when a single authored route covers the whole trip, falling toward
``1/n`` as the trip fragments into equal pieces. So maximising it rewards staying on
one artery and only briefly touching others. It is deliberately *non-monotonic* in
``n``: a route may merge more authored routes if that lets one run dominate. The
score carries **no** opinion on how the arteries are rated — that is the tier's job,
stated once — so re-rating an artery provably cannot move a route's match %.

``len`` is togglable via :class:`LengthMode` so it can be tuned experimentally.

**Required stops generalise it.** :func:`evaluate` scores one uninterrupted stretch,
and that is the whole objective for a plain point-to-point query. A ``via`` stop is a
place the trip actually stops at, so it cuts the trip into *legs*; each leg is scored
here on its own and the trip's concentration is the length-weighted mean of them
(:meth:`~.routing.RouteFinder._combine_legs`). A stop divides the *score* only: the
tier is read over the whole trip chain, so stopping in the middle of a rated road is
still riding it. Expanded, that is a block-diagonal
Herfindahl — credit pools within a leg but never across a required stop — which is
what says that riding one artery into a stop and a different one out of it is two
journeys done well rather than one journey done badly. With no ``via`` there is one
leg and the mean is the identity, so this module stays the single-leg primitive and
its formula above is unchanged.

The metric is **non-additive** (the ``Σ len`` denominator is a global
normaliser), so it cannot be optimised inside a shortest-path search; instead
:mod:`.routing` generates candidate chains and scores each one here. Scoring is
*exact*: a stop chain's edges may each belong to several authored routes, and
:func:`evaluate` picks the route-credit assignment that maximises the score via a
small chain-DP.
"""

from collections import namedtuple

from .core import BEST_PRIORITY, edge_key

# One contiguous stretch of the route on a single authored route, in travel order.
#   * ``route_id`` — the authored route ridden (or a synthetic edge key fallback).
#   * ``length``   — its length in the active :class:`LengthMode` units (score term).
#   * ``hops``     — its edge count (used for the "share of the whole route" %).
#   * ``priority`` — the worst mark the chain rides across this run (see
#     :func:`stamp_runs`); BEST_PRIORITY where the chain rides none. It is what the
#     UI paints on the run's chip, and ``max`` over the runs is the route's tier.
#   * ``start`` / ``end`` — the boundary nodes as *travelled*, so a label can be
#     oriented to the direction the route actually goes.
Run = namedtuple("Run", "route_id length hops priority start end")


class LengthMode:
    """Static switch for what a run's *length* means (flip to experiment).

    * ``CROSSROADS_ONLY = True`` — length counts crossroads
      (``degree > 2``); transparent shape-points don't count, consistent with the
      rest of the routing model.
    * ``CROSSROADS_ONLY = False`` — length is the plain hop count (every edge).

    Length is measured **per edge and symmetrically**, so it is identical whether
    the route is walked forwards or backwards: an edge ``(a, b)`` contributes
    ``is_crossroad(a) + is_crossroad(b)`` (crossroads-only) or ``1`` (every hop).
    A crossroad thus splits its weight between its two incident edges, which keeps
    the total length independent of *where* the route transfers between arteries —
    the property the exact-scoring DP relies on.
    """

    CROSSROADS_ONLY = True


class PriorityMode:
    """Static switch for how hard route priority bites (flip to experiment).

    * ``HARD_TIER = True`` — priority is a **hard tier**: results are ranked
      lexicographically by :func:`tier` first, so a route that stays on well-rated
      arteries beats one that touches a badly-rated one no matter how much longer it
      is. Concentration only decides *within* a tier.
    * ``HARD_TIER = False`` — the tier is dropped from the ranking and pure
      concentration decides. Since the score is priority-free, this makes the
      ranking fully priority-blind: the tier is the only place priority is spent.

    Either way the tier is still computed and reported — the flag only controls
    whether it gates ahead of the score. See :meth:`.routing.RouteFinder.
    select_diverse` for the arena it feeds.
    """

    HARD_TIER = True


def edge_unit(graph, a, b):
    """Length ``edge (a, b)`` contributes — direction-independent (see LengthMode).

    Public because :mod:`.routing` and :mod:`.search` also need "length" for the
    ranking score's crossroad-distance reference, and that reference must use the
    same units :func:`evaluate` sums for the HHI itself, per the active
    :class:`LengthMode` — otherwise the ranking would temper a score with a length
    notion the score doesn't use.
    """
    if LengthMode.CROSSROADS_ONLY:
        return (1 if graph.is_crossroad(a) else 0) + (1 if graph.is_crossroad(b) else 0)
    return 1


def _on_route_spans(memberships, route_id):
    """The maximal node windows over which the chain stays on ``route_id``'s edges.

    A mark names a stretch of *one* authored route, so it is only ridden if the
    chain runs its two endpoints together **on that route's own edges** — otherwise
    a chain that merely visits both names by some other road would read as riding a
    road it never touched. Each span here is one such uninterrupted stretch, as an
    inclusive node window ``[lo, hi]``.
    """
    spans, start = [], None
    for index, routes in enumerate(memberships):
        if route_id in routes:
            if start is None:
                start = index
        elif start is not None:
            spans.append((start, index))
            start = None
    if start is not None:
        spans.append((start, len(memberships)))
    return spans


def ridden_marks(graph, stops):
    """Every mark this chain rides **whole**, as node windows into ``stops``.

    Returns ``((lo, hi, priority), ...)``: the inclusive node window the mark
    occupies on this chain, and its rating. A mark is ridden when the chain covers
    its stretch end to end on the marked route's own edges — in either direction,
    and no matter which authored route the credit assignment below hands that
    stretch to. **A mark rates the road, not the reading**: an artery co-serving the
    same edges cannot absorb the stretch and shed its rating, and neither can a
    transfer dropped inside it. Riding only *part* of a rated stretch stays free —
    the mark never enters this list — which is the author's line between "brushed
    past it" and "rode it", drawn by how the mark is drawn rather than guessed from
    a length constant.

    A chain may repeat a place (a required stop hanging off a junction is left by
    driving back out through it), so every occurrence of both endpoints is
    considered. When nothing is rated at all the whole apparatus is skipped, leaving
    the unrated path exactly as cheap as it was before marks existed.
    """
    if len(stops) < 2 or not graph.has_priorities():
        return ()
    memberships = [graph.routes_on(a, b) for a, b in zip(stops, stops[1:])]
    positions = {}
    for index, place in enumerate(stops):
        positions.setdefault(place, []).append(index)

    ridden = []
    for route_id in {route for routes in memberships for route in routes}:
        marks = graph.route_marks(route_id)
        if not marks:
            continue
        for lo, hi in _on_route_spans(memberships, route_id):
            for start, end, priority in marks:
                heads = [p for p in positions.get(start, ()) if lo <= p <= hi]
                tails = [p for p in positions.get(end, ()) if lo <= p <= hi]
                ridden += [
                    (min(a, b), max(a, b), priority)
                    for a in heads
                    for b in tails
                    if a != b
                ]
    return tuple(ridden)


def stamp_runs(graph, stops, runs, ridden=None):
    """``runs`` with each one carrying the worst ridden mark it **overlaps**.

    The runs tile the chain, so accumulating ``hops`` gives each one its node span.
    Overlap rather than containment, deliberately: a mark the chain rides may fall
    across a run boundary — or across a *required stop* — and it must still be
    reported. Stamping every run it touches is what keeps ``max(run.priority)``
    equal to the chain's own :func:`tier` whatever the assignment does, and what
    puts the rating on the chips the UI paints.

    ``ridden`` may be passed in when the caller has already computed it.
    """
    ridden = ridden_marks(graph, stops) if ridden is None else ridden
    if not ridden:
        return list(runs)  # nothing rated on this chain: every run rides at the best
    stamped, node = [], 0
    for run in runs:
        start, end = node, node + run.hops
        node = end
        worst = max(
            (priority for lo, hi, priority in ridden if lo < end and start < hi),
            default=BEST_PRIORITY,
        )
        stamped.append(run._replace(priority=worst))
    return stamped


def tier(graph, stops):
    """The route's priority: the worst mark it rides **whole** (see
    :func:`ridden_marks`).

    A route is rated by the stretches it actually rides end to end: clipping a
    marked stretch costs nothing, riding one inherits its rating. This is a fact
    about the *chain* — which edges it covers — and not about how :func:`evaluate`
    splits the credit for them, so no reading of the chain can shed a rating that a
    different, equally concentrated reading would pay. Contrast
    :meth:`~.core.Graph.edge_priority`, the *per-edge* best, which the generators
    use to hunt for a physically better-rated corridor: it counts an edge merely
    *inside* a marked stretch as rated, where the tier needs the whole stretch.
    """
    return max(
        (priority for _, _, priority in ridden_marks(graph, stops)),
        default=BEST_PRIORITY,
    )


def evaluate(graph, stops):
    """Best-case concentration of a stop chain, and the ride it implies.

    Returns ``(score, runs)`` for the route-credit assignment that maximises it:

      * ``score`` — the concentration in ``[0, 1]`` (higher is better; it reaches
        ``1.0`` by riding a single authored route the whole way, whatever its
        rating — how *good* that artery is belongs to :func:`tier`, not here).
      * ``runs``  — the contiguous single-route stretches, **in travel order**
        (:class:`Run` each), from which callers derive the distinct routes, the
        per-run share, and travel-oriented labels. Each carries the worst mark the
        chain rides across it (:func:`stamp_runs`), so ``max(run.priority)`` is the
        chain's :func:`tier`.

    The total length ``L = Σ unit`` is independent of the assignment (units are
    per-edge), so maximising ``score`` is maximising the numerator ``Σ len(r_i)²``.
    When ``L == 0`` (a chain that crosses no crossroads — only possible under
    ``CROSSROADS_ONLY``) the score falls back to the equal-share value ``1/n`` over
    the ``n`` distinct routes, keeping it defined. The result is identical for a
    chain and its reverse.

    **The assignment is priority-free**, and deliberately so: it answers *how well
    does this chain ride one artery*, while how well the road it covers is **rated**
    is :func:`tier`'s answer, reported separately and settled before this runs.
    Priority therefore cannot move the score, the runs, or their shares — which
    matters because the API reports the score as the match %, and a number that
    shifted when an artery was re-rated reads as a bug. It also removes the only
    way a route ever dodged a rating: when the tier followed the assignment, a
    weightless edge peeled onto a co-serving artery split a run one edge short of a
    mark at exactly zero cost, and the reading that shed the rating won the tie.
    Ties now go to the **fewest transfers**, so the reported ride is the plainest
    one — and it changes nothing but which equally concentrated reading is shown.
    """
    if len(stops) < 2:
        return 1.0, []

    edges = list(zip(stops, stops[1:]))
    memberships = [graph.routes_on(a, b) or (edge_key(a, b),) for a, b in edges]
    units = [edge_unit(graph, a, b) for a, b in edges]
    total_length = sum(units)

    # Prefix sums of the units, so a run's length is one subtraction: the run
    # covering edges [start, end) is ``prefix[end] - prefix[start]`` long.
    prefix = [0] * (len(units) + 1)
    for index, unit in enumerate(units):
        prefix[index + 1] = prefix[index] + unit

    # DP over edges to choose the credit assignment: maximise Σ len(r_i)², then
    # prefer the fewest transfers among the assignments that tie there. Squares are
    # strictly superadditive, so a tie means the piece split off carries *no*
    # length — a transfer that buys nothing — and the tie-break drops it, keeping
    # the reported ride free of runs that ride nothing.
    # State: (route credited to this edge, index of the open run's first edge).
    # Stored value: (closed, -transfers) — the closed runs' Σ len², maximised first;
    # the *open* run's k² is added when we finalise. Units can exceed 1, so we close
    # runs explicitly rather than adding an incremental square term.
    layers = [{(r, 0): ((0.0, 0), None) for r in memberships[0]}]

    for j in range(1, len(edges)):
        routes = memberships[j]
        cur = {}
        for (r, start), (value, _) in layers[-1].items():
            closed, negtr = value
            # Continue the current run (only if this edge also carries route r).
            # The run keeps its start, so this can only ever land on one state.
            if r in routes:
                cur[(r, start)] = (value, (r, start))
            # Or switch to another member route: close this run — it covered edges
            # [start, j) — and open a fresh one at j.
            others = [r2 for r2 in routes if r2 != r]
            if others:
                k = prefix[j] - prefix[start]
                cand = (closed + k * k, negtr - 1)
                for r2 in others:
                    state = (r2, j)
                    if state not in cur or cand > cur[state][0]:
                        cur[state] = (cand, (r, start))
        layers.append(cur)

    def final_value(state):
        (r, start), ((closed, negtr), _) = state, layers[-1][state]
        k = prefix[len(edges)] - prefix[start]
        return (closed + k * k, negtr)

    best_state = max(layers[-1], key=final_value)

    # Walk the backpointers to recover the winning per-edge assignment.
    assigned = []
    state = best_state
    for j in range(len(edges) - 1, -1, -1):
        assigned.append(state[0])
        state = layers[j][state][1]
    assigned.reverse()

    # Group the assignment into runs, in travel order. A run covers edges
    # [s, e], i.e. nodes stops[s..e+1]; adjacent runs share the boundary node.
    runs = []
    s = 0
    for i in range(1, len(assigned) + 1):
        if i == len(assigned) or assigned[i] != assigned[s]:
            runs.append(
                Run(
                    route_id=assigned[s],
                    length=prefix[i] - prefix[s],
                    hops=i - s,
                    priority=BEST_PRIORITY,
                    start=stops[s],
                    end=stops[i],
                )
            )
            s = i
    runs = stamp_runs(graph, stops, runs)

    if total_length == 0:
        distinct = {run.route_id for run in runs}
        score = 1.0 / len(distinct) if distinct else 1.0
    else:
        numerator = sum(run.length * run.length for run in runs)
        score = numerator / (total_length * total_length)
    return score, runs
