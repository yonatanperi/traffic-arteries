"""Graph construction and concentration-maximising route search.

The public objects:

  * :class:`Graph`       — an undirected graph of place names, built from routes
    (:meth:`Graph.from_routes`) or wrapped around a persisted adjacency dict.
    Every edge remembers which authored routes traverse it.
  * :class:`RouteFinder` — diverse route search over a ``Graph`` whose "best"
    route rides one authored route as far as possible (highest concentration).
  * :class:`Route`       — one result: stops, concentration, and the merged routes.
  * :class:`LengthMode`  — static flag toggling how a run's length is measured
    (crossroad hops only vs. every hop); :func:`evaluate` scores a chain.

Internals live in sibling modules: :mod:`.core` (the graph), :mod:`.search`
(single-route generator strategies over ``(node, active-route)`` state),
:mod:`.concentration` (the exact per-chain objective), :mod:`.routing` (candidate
generation, scoring and diverse selection).
"""

from .concentration import LengthMode, evaluate
from .core import Graph
from .routing import Route, RouteFinder

__all__ = ["Graph", "Route", "RouteFinder", "LengthMode", "evaluate"]
