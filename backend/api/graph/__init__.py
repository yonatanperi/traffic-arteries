"""Graph construction and concentration-maximising route search.

The public objects:

  * :class:`Graph`        — an undirected graph of place names, built from routes
    (:meth:`Graph.from_routes`) or wrapped around a persisted adjacency dict.
    Every edge remembers which authored routes traverse it, and an authored route
    may carry *priority marks* — rated stretches of it (``0`` = best … ``3`` =
    worst) that bite only when a result rides the stretch whole.
  * :class:`RouteFinder`  — diverse route search over a ``Graph`` whose "best" route
    rides one *good* authored route as far as possible: best priority tier first,
    then highest concentration.
  * :class:`Route`        — one result: stops, tier, concentration, merged routes,
    and the *legs* a required stop splits the trip into (one leg without ``via``).
  * :class:`LengthMode`   — static flag toggling how a run's length is measured
    (crossroad hops only vs. every hop).
  * :class:`PriorityMode` — static flag toggling whether priority is a hard tier or
    only a weight on the score.
  * :func:`evaluate` scores a chain; :func:`tier` gives the worst priority among
    the sub-routes it rides — each run's being the worst mark that run completes,
    and ``0`` for a run that only clips one.

Internals live in sibling modules: :mod:`.core` (the graph), :mod:`.search`
(the single-route generator, over ``(node, active-route)`` state),
:mod:`.concentration` (the exact per-chain objective), :mod:`.routing` (candidate
generation, scoring and diverse selection).
"""

from .concentration import LengthMode, PriorityMode, evaluate, tier
from .core import BEST_PRIORITY, WORST_PRIORITY, Graph
from .routing import Route, RouteFinder

__all__ = [
    "Graph",
    "Route",
    "RouteFinder",
    "LengthMode",
    "PriorityMode",
    "BEST_PRIORITY",
    "WORST_PRIORITY",
    "evaluate",
    "tier",
]
