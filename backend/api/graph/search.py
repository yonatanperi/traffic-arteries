"""Single-route search strategies over a :class:`~.contraction.SegmentGraph`.

Each strategy answers the same question in a different way: *given a map of
segment penalties, what is the single best route right now?* A route is an
ordered list of :class:`~.contraction.Segment` objects (crossroad-to-crossroad
roads); its cost is the number of segments, penalty-weighted. Exposing this
behind a common :meth:`RouteStrategy.find` interface lets the diversity layer in
:mod:`.routing` stay ignorant of whether it is finding a plain shortest path or a
simple path through required stops — it just keeps calling ``find`` with a growing
penalty map to push each successive route onto a fresh corridor.
"""

import heapq
import itertools

# Safety valve for the simple-path search: give up (return "no route") after
# exploring this many partial paths. The route graph is small and sparse, so
# this is never hit in practice; it only guards against pathological blow-ups.
SEARCH_STATE_CAP = 200_000


class RouteStrategy:
    """A way to find one route for a given ``{segment_id: multiplier}`` penalty map.

    Subclasses implement :meth:`find`, returning ``(segments, cost)`` for the best
    route under those penalties, or ``(None, inf)`` when none exists.
    """

    def find(self, penalty):  # pragma: no cover - interface
        raise NotImplementedError


class ShortestPathStrategy(RouteStrategy):
    """Dijkstra from ``start`` to ``end`` over penalty-weighted segments.

    Every segment has base cost 1, multiplied by any accumulated penalty in the
    ``penalty`` map. With no penalties this is just the fewest-intersections
    route; penalising the segments of already-chosen routes steers each
    subsequent search onto a different corridor (including a parallel road
    between the same two crossroads).

    A monotonically increasing counter breaks cost ties in insertion order, so
    among equal-cost paths the one whose nodes come first (segments are iterated
    in sorted order) wins — stable, deterministic output.
    """

    def __init__(self, graph, start, end):
        self.graph = graph
        self.start = start
        self.end = end

    def find(self, penalty):
        graph, start, end = self.graph, self.start, self.end
        counter = itertools.count()
        # Heap entries: (cost, tie_breaker, node, nodes_so_far, segments_so_far).
        heap = [(0.0, next(counter), start, (start,), ())]
        best_cost = {start: 0.0}

        while heap:
            cost, _, node, nodes, segments = heapq.heappop(heap)
            if node == end:
                return list(segments), cost
            if cost > best_cost.get(node, float("inf")):
                continue  # a cheaper route to this node was already settled
            for segment in graph.incident(node):
                neighbour = segment.other(node)
                if neighbour in nodes:
                    continue  # keep the path simple (cycle-free at kept nodes)
                step = penalty.get(segment.id, 1.0)
                new_cost = cost + step
                if new_cost < best_cost.get(neighbour, float("inf")):
                    best_cost[neighbour] = new_cost
                    heapq.heappush(
                        heap,
                        (new_cost, next(counter), neighbour, nodes + (neighbour,), segments + (segment,)),
                    )

        return None, float("inf")


class WaypointStrategy(RouteStrategy):
    """Penalty-weighted shortest *simple* route visiting ``points`` in order.

    Real-world routing: the whole route is a simple path — no kept node is ever
    visited twice — that touches the required stops in the given order. It is a
    best-first search over partial simple routes:

      * a kept node already on the path is never re-entered (no revisits);
      * a required stop may only be entered when it is the *next* one due —
        stepping onto a later stop early would strand it and dead-end;
      * among equal-cost frontiers the earliest-discovered wins, so output is
        deterministic (segments are iterated in sorted order).

    Because it always expands the cheapest frontier first, the very first route
    it returns is the genuine shortest one for this order — so when a direct
    connection between two stops exists it is used, never detoured around.

    :meth:`find` returns ``(segments, cost)`` or ``(None, inf)`` if no simple
    route visits every stop in order.
    """

    def __init__(self, graph, points):
        self.graph = graph
        self.points = points

    def find(self, penalty):
        graph, points = self.graph, self.points
        point_set = set(points)
        last = len(points) - 1  # index of the final stop (the end)

        counter = itertools.count()
        # Heap entries: (cost, tie_breaker, node, reached, nodes, segments).
        # ``reached`` is how many entries of ``points`` we have hit so far; we
        # start already on the first one, so the next stop due is points[reached].
        heap = [(0.0, next(counter), points[0], 1, (points[0],), ())]
        explored = 0

        while heap:
            cost, _, node, reached, nodes, segments = heapq.heappop(heap)
            if reached > last:
                return list(segments), cost  # reached the final stop, in order

            explored += 1
            if explored > SEARCH_STATE_CAP:
                break

            target = points[reached]
            for segment in graph.incident(node):
                neighbour = segment.other(node)
                # The final step may land back on the start node (a round trip
                # where start == end); every other repeat is forbidden.
                revisits = neighbour in nodes
                if revisits and not (neighbour == target and reached == last):
                    continue
                # A required stop is only enterable as the current target.
                if neighbour in point_set and neighbour != target:
                    continue
                step = penalty.get(segment.id, 1.0)
                new_reached = reached + 1 if neighbour == target else reached
                heapq.heappush(
                    heap,
                    (cost + step, next(counter), neighbour, new_reached, nodes + (neighbour,), segments + (segment,)),
                )

        return None, float("inf")
