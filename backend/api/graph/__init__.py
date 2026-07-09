"""Graph construction and merge-minimising route search.

The public objects:

  * :class:`Graph`       — an undirected graph of place names, built from routes
    (:meth:`Graph.from_routes`) or wrapped around a persisted adjacency dict.
    Every edge remembers which authored routes traverse it.
  * :class:`RouteFinder` — diverse route search over a ``Graph`` whose "best"
    route merges the fewest authored routes.
  * :class:`Route`       — one result: stops plus the authored routes it merges.

Internals live in sibling modules: :mod:`.core` (the graph), :mod:`.search`
(single-route strategies over ``(node, active-route)`` state), :mod:`.routing`
(the diversity layer).
"""

from .core import Graph
from .routing import Route, RouteFinder

__all__ = ["Graph", "Route", "RouteFinder"]
