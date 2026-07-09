"""The :class:`SegmentGraph`: the routing graph with transparent nodes removed.

A place with **2 or fewer connections is not a real decision point** — it is a
shape point along a road, not an intersection. Only travel **between crossroads**
(``degree >= 3``) should count. This module collapses each maximal chain of such
transparent nodes into a single :class:`Segment` of weight 1, so the search in
:mod:`.search` reasons about intersection-to-intersection travel while the caller
still gets back the full, edge-valid place-name chain.

The nodes kept in the segment graph are ``K = crossroads ∪ {required terminals}``
— the query's start, end and via stops are always kept even when transparent, so
they stay routable. Two *different* roads between the same pair of crossroads
become two distinct segments (a multigraph), so alternative routes can diverge
between the same two intersections.

Key invariant: a transparent node (degree ≤ 2) belongs to exactly one segment, so
a route that never revisits a kept node never revisits a segment or an interior
node — simplicity at the kept-node level implies a simple full path.
"""

import heapq


class Segment:
    """One road between two kept nodes: a full node chain of weight 1.

    ``nodes`` is the chain in canonical (endpoint-sorted) orientation; its
    interior is entirely transparent. Parallel roads between the same two kept
    nodes are separate ``Segment`` objects with separate ids.
    """

    def __init__(self, id, nodes):
        self.id = id
        self.nodes = tuple(nodes)
        self.endpoints = (self.nodes[0], self.nodes[-1])

    def other(self, node):
        """The endpoint opposite ``node``."""
        a, b = self.endpoints
        return b if node == a else a

    def oriented(self, from_node):
        """The node chain oriented to start at ``from_node``."""
        return self.nodes if self.nodes[0] == from_node else self.nodes[::-1]


class SegmentGraph:
    """Crossroad-to-crossroad view of a :class:`~.core.Graph`.

    Built with :meth:`build`. Nodes are the kept nodes ``K``; edges are
    :class:`Segment` objects (weight 1). The search layer treats each segment as
    a single unit of travel and penalises it by :attr:`Segment.id`.
    """

    def __init__(self, nodes, incident):
        self._nodes = set(nodes)
        self._incident = incident

    def __contains__(self, node):
        return node in self._nodes

    def incident(self, node):
        """Segments touching ``node``, in a deterministic order (empty if none)."""
        return self._incident.get(node, [])

    def source_costs(self, source):
        """Segment-count shortest-path costs ``{node: cost}`` from ``source``.

        Each segment costs 1, so this measures distance in intersections. Used to
        score candidate waypoint orderings before the penalty-weighted search.
        """
        costs = {source: 0.0}
        heap = [(0.0, source)]
        while heap:
            cost, node = heapq.heappop(heap)
            if cost > costs.get(node, float("inf")):
                continue
            for segment in self.incident(node):
                other = segment.other(node)
                new_cost = cost + 1.0
                if new_cost < costs.get(other, float("inf")):
                    costs[other] = new_cost
                    heapq.heappush(heap, (new_cost, other))
        return costs

    @classmethod
    def build(cls, graph, keep):
        """Contract ``graph`` (a :class:`~.core.Graph`) to its kept nodes.

        ``keep`` is the set of required terminals; combined with the crossroads
        it forms ``K``. Every maximal transparent chain between two kept nodes
        becomes a :class:`Segment`. Determinism comes from iterating ``K`` and
        neighbours in sorted order, so segment ids and adjacency are stable.
        """
        kept = set(graph.crossroads()) | {t for t in keep if t in graph}

        segments = []
        seen = set()  # canonical node tuples already turned into a segment
        for u in sorted(kept):
            for first in graph.neighbors(u):
                chain = _walk_segment(graph, kept, u, first)
                if chain is None:
                    continue
                if chain[-1] == u:
                    continue  # self-loop chain, of no use to routing
                canonical = tuple(chain) if chain[0] <= chain[-1] else tuple(reversed(chain))
                if canonical in seen:
                    continue  # same segment already found from the other end
                seen.add(canonical)
                segments.append(Segment(len(segments), canonical))

        incident = {node: [] for node in kept}
        for segment in segments:
            incident[segment.endpoints[0]].append(segment)
            incident[segment.endpoints[1]].append(segment)
        for node, segs in incident.items():
            segs.sort(key=lambda seg: seg.oriented(node))

        return cls(kept, incident)


def _walk_segment(graph, kept, u, first):
    """Follow the chain ``u -> first -> …`` through transparent nodes to a kept node.

    Returns the full node chain (kept endpoints, transparent interior), or
    ``None`` for a chain that dead-ends before reaching another kept node.
    """
    chain = [u, first]
    prev, node = u, first
    while node not in kept:
        forward = [n for n in graph.neighbors(node) if n != prev]
        if not forward:
            return None  # dead-end transparent chain, leads nowhere useful
        # A transparent node has degree <= 2, so there is at most one way forward.
        prev, node = node, forward[0]
        if node in chain:
            return None  # transparent cycle with no other kept node: no segment
        chain.append(node)
    return chain


def expand(start, segments):
    """Stitch an ordered segment route into one full place-name chain.

    ``segments`` are the segments traversed from ``start`` in order; each is
    oriented to continue from where the previous one ended and appended without
    repeating the shared boundary node, so consecutive elements are real edges.
    """
    full = [start]
    node = start
    for segment in segments:
        sub = segment.oriented(node)
        full.extend(sub[1:])
        node = sub[-1]
    return full
