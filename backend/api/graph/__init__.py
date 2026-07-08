"""Graph construction and diverse alternative-route search.

The public objects:

  * :class:`Graph`       — an undirected graph of place names, built from routes
    (:meth:`Graph.from_routes`) or wrapped around a persisted adjacency dict.
  * :class:`RouteFinder` — Waze-style diverse route search over a ``Graph``.

Internals live in sibling modules: :mod:`.core` (the graph), :mod:`.search`
(single-route strategies), :mod:`.routing` (the diversity layer).
"""

from .core import Graph
from .routing import RouteFinder

__all__ = ["Graph", "RouteFinder"]
