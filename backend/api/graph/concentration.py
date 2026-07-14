"""Route *concentration* scoring — the search objective.

"Best" is the route that **rides one good authored route as far as possible**. The
objective has two levels, and they answer different questions:

**1. The tier** (:func:`tier`) — *may* we ride this corridor at all? Every authored
route carries a priority (``0`` = best … ``3`` = worst); a chain's tier is the worst
priority it is forced to touch. Ranking is lexicographic on the tier first
(:data:`PriorityMode.HARD_TIER`), so a corridor that stays on well-rated arteries
beats one that dips into a badly-rated one *however long the detour*.

**2. The score** (:func:`evaluate`) — *how well* does it ride them? For a route split
into maximal contiguous runs ``r_1 … r_n``, each on a single authored route, we take
the Herfindahl index of how its length is distributed across those runs, with each
run's share discounted by its artery's priority::

    score = Σ_i  w(priority(r_i)) · ( len(r_i) / Σ_j len(r_j) )²

    w(p) = 1 − PRIORITY_STEP · p        →  1.0, 0.8, 0.6, 0.4

Unweighted (everything priority 0) this is exactly the Herfindahl index: ``1.0``
when a single authored route covers the whole trip, falling toward ``1/n`` as the
trip fragments into equal pieces. So maximising it rewards staying on one artery
and only briefly touching others. It is deliberately *non-monotonic* in ``n``: a
route may merge more authored routes if that lets one run dominate. The weights add
a second pressure on top: within a tier, *briefly touching* a poorly-rated artery
still beats *riding* one.

``len`` is togglable via :class:`LengthMode` so it can be tuned experimentally.

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
#   * ``priority`` — the ridden artery's priority, i.e. what discounted its credit.
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


# How much of an artery's credit each priority level below the best discounts:
# w(p) = 1 - PRIORITY_STEP * p, so 0.2 gives weights 1.0 / 0.8 / 0.6 / 0.4. At this
# step, riding one priority-1 artery end to end (0.8) beats splitting evenly across
# two priority-0 arteries (0.5), but riding one priority-3 artery (0.4) loses to it.
PRIORITY_STEP = 0.2


class PriorityMode:
    """Static switch for how hard route priority bites (flip to experiment).

    * ``HARD_TIER = True`` — priority is a **hard tier**: results are ranked
      lexicographically by :func:`tier` first, so a route that stays on well-rated
      arteries beats one that touches a badly-rated one no matter how much longer it
      is. Concentration only decides *within* a tier.
    * ``HARD_TIER = False`` — the tier is dropped from the ranking and only the
      priority-weighted concentration remains. Priority still discourages bad
      arteries, but a short, clean corridor through a mediocre one can win.

    The weighted score (:func:`evaluate`) is in play either way; this flag only
    controls whether the tier gates ahead of it. See :meth:`.routing.RouteFinder.
    _select_diverse` for the sort it feeds.
    """

    HARD_TIER = True


def _edge_unit(graph, a, b):
    """Length ``edge (a, b)`` contributes — direction-independent (see LengthMode)."""
    if LengthMode.CROSSROADS_ONLY:
        return (1 if graph.is_crossroad(a) else 0) + (1 if graph.is_crossroad(b) else 0)
    return 1


def _route_weight(graph, route_id):
    """How much credit a run on ``route_id`` earns — its priority discount."""
    return 1.0 - PRIORITY_STEP * graph.route_priority(route_id)


def tier(graph, stops):
    """The worst priority the chain ``stops`` is *forced* to touch.

    An edge may be carried by several authored routes, so travelling it only commits
    you to the best-rated of them (:meth:`~.core.Graph.edge_priority`); the chain's
    tier is the worst such commitment along it. This asks "what is the best possible
    priority profile this chain can be walked with", which makes it **independent of
    the credit assignment** :func:`evaluate` picks — and that is the point. Were it
    read off the score-maximising runs instead, a chain could be pushed into a worse
    tier merely because crediting one long run to a poorly-rated artery happened to
    outscore splitting it across two well-rated ones.
    """
    edges = list(zip(stops, stops[1:]))
    if not edges:
        return BEST_PRIORITY
    return max(graph.edge_priority(a, b) for a, b in edges)


def evaluate(graph, stops):
    """Best-case priority-weighted concentration of a stop chain.

    Returns ``(score, runs)`` for the route-credit assignment that maximises it:

      * ``score`` — the weighted concentration in ``[0, 1]`` (higher is better; it
        reaches ``1.0`` only by riding a single *priority-0* route the whole way).
      * ``runs``  — the contiguous single-route stretches, **in travel order**
        (:class:`Run` each), from which callers derive the distinct routes, the
        per-run share, and travel-oriented labels.

    The total length ``L = Σ unit`` is independent of the assignment (units are
    per-edge), so maximising ``score`` is maximising the numerator
    ``Σ w(priority(r_i))·len(r_i)²``; a tiny secondary preference for fewer
    transfers keeps the reported assignment clean. When ``L == 0`` (a chain that
    crosses no crossroads — only possible under ``CROSSROADS_ONLY``) the score falls
    back to the equal-share value ``Σ w(r)/n²`` over the ``n`` distinct routes (so
    ``1.0`` for a single priority-0 route), keeping it defined. The result is
    identical for a chain and its reverse.

    Because the weights favour well-rated arteries, an edge carried by both a
    priority-0 and a priority-3 route is credited to the priority-0 one for free —
    that is simply the assignment that scores higher.
    """
    if len(stops) < 2:
        return 1.0, []

    edges = list(zip(stops, stops[1:]))
    memberships = [graph.routes_on(a, b) or (edge_key(a, b),) for a, b in edges]
    units = [_edge_unit(graph, a, b) for a, b in edges]
    total_length = sum(units)

    weights = {r: _route_weight(graph, r) for routes in memberships for r in routes}

    # DP over edges to choose the credit assignment maximising Σ w(r_i)·len(r_i)².
    # State: (route credited to this edge, open run's length k). Stored value:
    # (closed_numerator, -transfers) — the closed runs' Σ w·len², maximised, then
    # fewest transfers; the *open* run's w·k² is added when we finalise. Units can
    # exceed 1, so we close runs explicitly rather than adding an incremental
    # square term.
    layer = {(r, units[0]): ((0.0, 0), None) for r in memberships[0]}
    layers = [layer]

    for j in range(1, len(edges)):
        routes = memberships[j]
        u = units[j]
        cur = {}
        for (r, k), (value, _) in layers[-1].items():
            closed, negtr = value
            # Continue the current run (only if this edge also carries route r).
            if r in routes:
                state = (r, k + u)
                cand = (closed, negtr)
                if state not in cur or cand > cur[state][0]:
                    cur[state] = (cand, (r, k))
            # Or switch to another member route: close this run, open a fresh one.
            for r2 in routes:
                if r2 == r:
                    continue
                state = (r2, u)
                cand = (closed + weights[r] * k * k, negtr - 1)
                if state not in cur or cand > cur[state][0]:
                    cur[state] = (cand, (r, k))
        layers.append(cur)

    def final_value(state):
        (r, k), ((closed, negtr), _) = state, layers[-1][state]
        return (closed + weights[r] * k * k, negtr)

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
                    length=sum(units[s:i]),
                    hops=i - s,
                    priority=graph.route_priority(assigned[s]),
                    start=stops[s],
                    end=stops[i],
                )
            )
            s = i

    if total_length == 0:
        distinct = {run.route_id for run in runs}
        share = 1.0 / len(distinct) if distinct else 1.0
        score = sum(weights[r] * share * share for r in distinct) if distinct else 1.0
    else:
        numerator = sum(weights[run.route_id] * run.length * run.length for run in runs)
        score = numerator / (total_length * total_length)
    return score, runs
