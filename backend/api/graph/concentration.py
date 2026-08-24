"""Route *concentration* scoring — the search objective.

"Best" is the route that **rides one good authored route as far as possible**. The
objective has two levels, and they answer different questions:

**1. The tier** (:func:`tier`) — *may* we ride this corridor at all? An authored
route may carry **priority marks**: rated stretches of it (``0`` = best … ``3`` =
worst), each drawn by the author over a range of that route's stops. A route's
tier is the worst priority among the marks its ridden sub-routes **complete** —
the sub-routes being the runs of the score's own credit assignment below, i.e. the
chips the UI shows. A mark counts only when one run holds the stretch *entire*:
riding part of a rated stretch is deliberately free, because where the line falls
between "brushed past it" and "rode it" is the author's knowledge, expressed by how
the mark is drawn, and not a length heuristic's guess. Ranking is lexicographic on
the tier first (:data:`PriorityMode.HARD_TIER`), so a route that completes no bad
mark beats one whose concentrated corridor completes one *however long the detour*.
Because the tier reads the ridden sub-routes, a road that is *also* served by a
good route only escapes the downgrade when riding it as that good route is at least
as concentrated — otherwise the concentrated way to ride it is the marked one, and
the tier says so.

**2. The score** (:func:`evaluate`) — *how well* does it ride them? For a route split
into maximal contiguous runs ``r_1 … r_n``, each on a single authored route, we take
the Herfindahl index of how its length is distributed across those runs, with each
run's share discounted by the marks that run completes::

    score = Σ_i  w(priority(r_i)) · ( len(r_i) / Σ_j len(r_j) )²

    w(p) = 1 − PRIORITY_STEP · p        →  1.0, 0.8, 0.6, 0.4

Unweighted (everything priority 0) this is exactly the Herfindahl index: ``1.0``
when a single authored route covers the whole trip, falling toward ``1/n`` as the
trip fragments into equal pieces. So maximising it rewards staying on one artery
and only briefly touching others. It is deliberately *non-monotonic* in ``n``: a
route may merge more authored routes if that lets one run dominate. The weights add
a second pressure on top: within a tier, *clipping* a marked stretch still beats
completing it.

``len`` is togglable via :class:`LengthMode` so it can be tuned experimentally.

The metric is **non-additive** (the ``Σ len`` denominator is a global
normaliser), so it cannot be optimised inside a shortest-path search; instead
:mod:`.routing` generates candidate chains and scores each one here. Scoring is
*exact*: a stop chain's edges may each belong to several authored routes, and
:func:`evaluate` picks the route-credit assignment that maximises the score via a
small chain-DP.
"""

from bisect import bisect_left
from collections import namedtuple

from .core import BEST_PRIORITY, edge_key

# One contiguous stretch of the route on a single authored route, in travel order.
#   * ``route_id`` — the authored route ridden (or a synthetic edge key fallback).
#   * ``length``   — its length in the active :class:`LengthMode` units (score term).
#   * ``hops``     — its edge count (used for the "share of the whole route" %).
#   * ``priority`` — the worst mark this run *completes*, i.e. what discounted its
#     credit. A run that merely clips a rated stretch is BEST_PRIORITY.
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
# step, completing one priority-1 mark end to end (0.8) beats splitting evenly
# across two unrated arteries (0.5), but completing a priority-3 one (0.4) loses
# to it.
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


def _mark_windows(graph, stops, memberships):
    """The marks reachable on this chain, indexed by position in ``stops``.

    ``{route_id: [(start positions, end positions, priority), ...]}``, each
    position list ascending. A run occupies a contiguous node window ``[lo, hi]``
    of ``stops``, so "does this run complete that mark" becomes two binary
    searches rather than a scan over the run's nodes — which matters because the
    credit-assignment DP asks it once per closed run, not once per result.

    A mark whose endpoints don't both appear on this chain can never be completed,
    so it is dropped here instead of being retested per state. When nothing is
    rated at all the whole apparatus is skipped and every weight is 1.0, leaving
    the unrated path exactly as cheap as it was before marks existed.
    """
    if not graph.has_priorities():
        return {}
    positions = {}
    for index, place in enumerate(stops):
        positions.setdefault(place, []).append(index)
    windows = {}
    for route_id in {route for routes in memberships for route in routes}:
        entries = [
            (positions[start], positions[end], priority)
            for start, end, priority in graph.route_marks(route_id)
            if start in positions and end in positions
        ]
        if entries:
            windows[route_id] = entries
    return windows


def _within(positions, lo, hi):
    """Whether any of the ascending ``positions`` falls in the inclusive window."""
    index = bisect_left(positions, lo)
    return index < len(positions) and positions[index] <= hi


def _window_priority(entries, lo, hi):
    """The worst priority among ``entries`` whose *both* endpoints sit in ``[lo, hi]``."""
    worst = BEST_PRIORITY
    for starts, ends, priority in entries:
        if priority > worst and _within(starts, lo, hi) and _within(ends, lo, hi):
            worst = priority
    return worst


def tier(graph, stops):
    """The route's priority: the worst mark the sub-routes it *rides* complete.

    The sub-routes are the maximal single-route runs of the max-HHI credit
    assignment (:func:`evaluate`) — exactly the breakdown the UI shows as chips. A
    route is therefore rated by the stretches it actually rides end to end: clipping
    a marked stretch costs nothing, completing one inherits its rating.

    This is deliberately **assignment-dependent**. An edge may also be served by a
    better-rated route, but that only rescues the tier when riding it *as* that
    better route is at least as concentrated — because then :func:`evaluate` credits
    the run there anyway (a higher weight at equal length scores higher). When the
    marked route is the only one that spans the stretch in a single run, that is
    genuinely the corridor being ridden, and the tier says so. Contrast
    :meth:`~.core.Graph.edge_priority`, the *per-edge* best, which the generators
    use to hunt for a physically different, better-rated corridor.
    """
    _, runs = evaluate(graph, stops)
    return max((run.priority for run in runs), default=BEST_PRIORITY)


def evaluate(graph, stops):
    """Best-case concentration of a stop chain, and the ride it implies.

    Returns ``(score, runs)`` for the route-credit assignment that maximises it:

      * ``score`` — the concentration in ``[0, 1]`` (higher is better; it reaches
        ``1.0`` by riding a single authored route the whole way, whatever its
        rating — how *good* that artery is belongs to :func:`tier`, not here).
      * ``runs``  — the contiguous single-route stretches, **in travel order**
        (:class:`Run` each), from which callers derive the distinct routes, the
        per-run share, and travel-oriented labels.

    The total length ``L = Σ unit`` is independent of the assignment (units are
    per-edge), so maximising ``score`` is maximising the numerator ``Σ len(r_i)²``.
    When ``L == 0`` (a chain that crosses no crossroads — only possible under
    ``CROSSROADS_ONLY``) the score falls back to the equal-share value ``1/n`` over
    the ``n`` distinct routes, keeping it defined. The result is identical for a
    chain and its reverse.

    **The score is priority-free**, and deliberately so: it answers *how well does
    this chain ride one artery*, while how well that artery is **rated** is
    :func:`tier`'s answer, reported separately. Priority therefore cannot move the
    score, the runs, or their shares — which matters because the API reports the
    score as the match %, and a number that shifted when an artery was re-rated
    reads as a bug. Priority does still choose *between* assignments, but only as a
    tie-break: among the readings of the chain that are equally concentrated, the
    priority-weighted ``Σ w(r_i)·len(r_i)²`` is maximised, so an edge carried by both
    an unmarked and a marked route is credited to the unmarked one for free — and a
    reading that stops short of completing a mark wins over one that completes it,
    whenever the two are equally concentrated. Fewest transfers breaks any remaining
    tie, keeping the reported assignment clean.
    """
    if len(stops) < 2:
        return 1.0, []

    edges = list(zip(stops, stops[1:]))
    memberships = [graph.routes_on(a, b) or (edge_key(a, b),) for a, b in edges]
    units = [edge_unit(graph, a, b) for a, b in edges]
    total_length = sum(units)

    # Prefix sums of the units, so a run's length is one subtraction. The DP below
    # carries a run's *start edge* rather than its accumulated length: the two hold
    # the same information (length = prefix[end] - prefix[start]) and cost the same
    # number of states, but the start is what makes the run's node span known at the
    # moment it closes — and a mark is completed or not by that span.
    prefix = [0] * (len(units) + 1)
    for index, unit in enumerate(units):
        prefix[index + 1] = prefix[index] + unit

    windows = _mark_windows(graph, stops, memberships)

    def run_priority(route_id, lo, hi):
        """The worst mark of ``route_id`` the run spanning nodes ``[lo, hi]`` completes."""
        entries = windows.get(route_id)
        return _window_priority(entries, lo, hi) if entries else BEST_PRIORITY

    def weight(route_id, lo, hi):
        return 1.0 - PRIORITY_STEP * run_priority(route_id, lo, hi)

    # DP over edges to choose the credit assignment, on a two-level objective:
    # maximise the plain Σ len(r_i)² first, and only among the assignments that tie
    # there prefer the priority-weighted Σ w(r_i)·len(r_i)² — i.e. concentration
    # decides, and priority merely picks which artery gets the credit when the ride
    # is equally concentrated either way. That ordering is what keeps the score, the
    # runs and their shares priority-free: re-rating an artery can only change which
    # of two *equally concentrated* readings of the same chain is reported.
    # State: (route credited to this edge, index of the open run's first edge).
    # Stored value: (closed_plain, closed_weighted, -transfers) — the closed runs'
    # Σ len² and Σ w·len², maximised in that order, then fewest transfers; the *open*
    # run's k² / w·k² is added when we finalise. Units can exceed 1, so we close runs
    # explicitly rather than adding an incremental square term.
    layers = [{(r, 0): ((0.0, 0.0, 0), None) for r in memberships[0]}]

    for j in range(1, len(edges)):
        routes = memberships[j]
        cur = {}
        for (r, start), (value, _) in layers[-1].items():
            plain, closed, negtr = value
            # Continue the current run (only if this edge also carries route r).
            # The run keeps its start, so this can only ever land on one state.
            if r in routes:
                cur[(r, start)] = (value, (r, start))
            # Or switch to another member route: close this run — it covered edges
            # [start, j), i.e. nodes stops[start..j] — and open a fresh one at j.
            others = [r2 for r2 in routes if r2 != r]
            if others:
                k = prefix[j] - prefix[start]
                cand = (
                    plain + k * k,
                    closed + weight(r, start, j) * k * k,
                    negtr - 1,
                )
                for r2 in others:
                    state = (r2, j)
                    if state not in cur or cand > cur[state][0]:
                        cur[state] = (cand, (r, start))
        layers.append(cur)

    def final_value(state):
        (r, start), ((plain, closed, negtr), _) = state, layers[-1][state]
        k = prefix[len(edges)] - prefix[start]
        return (
            plain + k * k,
            closed + weight(r, start, len(edges)) * k * k,
            negtr,
        )

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
                    priority=run_priority(assigned[s], s, i),
                    start=stops[s],
                    end=stops[i],
                )
            )
            s = i

    if total_length == 0:
        distinct = {run.route_id for run in runs}
        score = 1.0 / len(distinct) if distinct else 1.0
    else:
        numerator = sum(run.length * run.length for run in runs)
        score = numerator / (total_length * total_length)
    return score, runs
