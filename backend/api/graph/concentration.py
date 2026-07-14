"""Route *concentration* scoring — the search objective.

"Best" is the route that **rides one authored route as far as possible**. For a
route split into maximal contiguous runs ``r_1 … r_n`` on a single authored route,
we score the Herfindahl index of how its length is distributed across those runs::

    hhi = Σ_i ( len(r_i) / Σ_j len(r_j) )²

which is ``1.0`` when a single authored route covers the whole trip and falls
toward ``1/n`` as the trip fragments into equal pieces — so maximising it rewards
staying on one artery and only briefly touching others. It is deliberately
*non-monotonic* in ``n``: a route may merge more authored routes if that lets one
run dominate.

``len`` is togglable via :class:`LengthMode` so it can be tuned experimentally.

The metric is **non-additive** (the ``Σ len`` denominator is a global
normaliser), so it cannot be optimised inside a shortest-path search; instead
:mod:`.routing` generates candidate chains and scores each one here. Scoring is
*exact*: a stop chain's edges may each belong to several authored routes, and
:func:`evaluate` picks the route-credit assignment that maximises the score via a
small chain-DP.
"""

from collections import namedtuple

from .core import edge_key

# One contiguous stretch of the route on a single authored route, in travel order.
#   * ``route_id`` — the authored route ridden (or a synthetic edge key fallback).
#   * ``length``   — its length in the active :class:`LengthMode` units (HHI term).
#   * ``hops``     — its edge count (used for the "share of the whole route" %).
#   * ``start`` / ``end`` — the boundary nodes as *travelled*, so a label can be
#     oriented to the direction the route actually goes.
Run = namedtuple("Run", "route_id length hops start end")


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


def _edge_unit(graph, a, b):
    """Length ``edge (a, b)`` contributes — direction-independent (see LengthMode)."""
    if LengthMode.CROSSROADS_ONLY:
        return (1 if graph.is_crossroad(a) else 0) + (1 if graph.is_crossroad(b) else 0)
    return 1


def evaluate(graph, stops):
    """Best-case concentration of a stop chain.

    Returns ``(hhi, runs)`` for the route-credit assignment that maximises the
    Herfindahl score:

      * ``hhi``  — the concentration in ``[0, 1]`` (higher is better).
      * ``runs`` — the contiguous single-route stretches, **in travel order**
        (:class:`Run` each), from which callers derive the distinct routes, the
        per-run share, and travel-oriented labels.

    The total length ``L = Σ unit`` is independent of the assignment (units are
    per-edge), so maximising ``hhi`` is maximising the numerator ``Σ len(r_i)²``;
    a tiny secondary preference for fewer transfers keeps the reported assignment
    clean. When ``L == 0`` (a chain that crosses no crossroads — only possible
    under ``CROSSROADS_ONLY``) the score falls back to the equal-share value
    ``1/route_count`` (so ``1.0`` for a single route), keeping it defined. The
    result is identical for a chain and its reverse.
    """
    if len(stops) < 2:
        return 1.0, []

    edges = list(zip(stops, stops[1:]))
    memberships = [graph.routes_on(a, b) or (edge_key(a, b),) for a, b in edges]
    units = [_edge_unit(graph, a, b) for a, b in edges]
    total_length = sum(units)

    # DP over edges to choose the route-credit assignment maximising Σ(run len)².
    # State: (route credited to this edge, open run's length k). Stored value:
    # (closed_numerator, -transfers) — the closed runs' Σlen², maximised, then
    # fewest transfers; the *open* run's k² is added when we finalise. Units can
    # exceed 1, so we close runs explicitly rather than adding an incremental
    # square term.
    layer = {(r, units[0]): ((0, 0), None) for r in memberships[0]}
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
                cand = (closed + k * k, negtr - 1)
                if state not in cur or cand > cur[state][0]:
                    cur[state] = (cand, (r, k))
        layers.append(cur)

    def final_value(state):
        (_, k), ((closed, negtr), _) = state, layers[-1][state]
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
                    length=sum(units[s:i]),
                    hops=i - s,
                    start=stops[s],
                    end=stops[i],
                )
            )
            s = i

    if total_length == 0:
        distinct = len({run.route_id for run in runs})
        hhi = 1.0 / distinct if distinct else 1.0
    else:
        numerator = sum(run.length * run.length for run in runs)
        hhi = numerator / (total_length * total_length)
    return hhi, runs
