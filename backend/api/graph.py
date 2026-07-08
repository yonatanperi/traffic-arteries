"""Graph construction and diverse alternative-route search.

Routes are chains of place names. Consecutive places in a route form a
bidirectional edge. From those edges we build an undirected graph stored as an
adjacency list.

Route search returns up to ``k`` *genuinely different* options (Waze-style
alternatives), not near-duplicates of the shortest path. See
:func:`k_shortest_paths` for the algorithm.
"""

import heapq
import itertools

# Above this many required stops the permutation count (n!) makes exhaustive
# order optimisation impractical, so we fall back to the caller's order.
MAX_OPTIMIZED_WAYPOINTS = 7

# With required stops we keep alternatives tight: a route may not exceed the
# best route through those stops by more than this factor. This is what stops
# an alternative from wandering off on a pointless detour when a short
# connection between two stops already exists.
WAYPOINT_MAX_STRETCH = 1.5

# Safety valve for the simple-path search: give up (return "no route") after
# exploring this many partial paths. The route graph is small and sparse, so
# this is never hit in practice; it only guards against pathological blow-ups.
SEARCH_STATE_CAP = 200_000


def build_adjacency(routes):
    """Build an adjacency list (dict place -> sorted list of neighbours).

    Each pair of *consecutive* places in a route becomes an undirected edge.
    Every place that appears is guaranteed a key, even if it ends up isolated.
    """
    adjacency = {}

    def ensure(place):
        if place not in adjacency:
            adjacency[place] = set()

    for route in routes:
        for place in route:
            ensure(place)
        for a, b in zip(route, route[1:]):
            if a == b:
                continue
            adjacency[a].add(b)
            adjacency[b].add(a)

    # Freeze to sorted lists for stable, JSON-friendly output.
    return {place: sorted(neighbours) for place, neighbours in adjacency.items()}


def all_places(adjacency):
    """Sorted list of every place in the graph (autocomplete source)."""
    return sorted(adjacency.keys())


def to_network(adjacency):
    """Shape the graph for react-force-graph-2d: {nodes, links}.

    Undirected edges are de-duplicated by ordering each pair so a link is only
    emitted once.
    """
    nodes = [{"id": place} for place in sorted(adjacency.keys())]

    seen = set()
    links = []
    for place, neighbours in adjacency.items():
        for neighbour in neighbours:
            key = tuple(sorted((place, neighbour)))
            if key in seen:
                continue
            seen.add(key)
            links.append({"source": key[0], "target": key[1]})

    return {"nodes": nodes, "links": links}


def _edge_key(a, b):
    """Order-independent key for an undirected edge."""
    return (a, b) if a <= b else (b, a)


def _edges(path):
    """The set of undirected edges that make up a path."""
    return {_edge_key(a, b) for a, b in zip(path, path[1:])}


def _shortest_path(adjacency, start, end, penalty):
    """Dijkstra from ``start`` to ``end`` over penalty-weighted edges.

    Every edge has base cost 1, multiplied by any accumulated penalty in
    ``penalty`` (an ``{edge_key: multiplier}`` dict). With no penalties this is
    just an unweighted shortest path; penalising the edges of already-chosen
    routes steers each subsequent search onto a different corridor.

    A monotonically increasing counter breaks cost ties in insertion order, so
    among equal-cost paths the one whose nodes come first (neighbours are
    iterated in sorted order) wins — stable, deterministic output.
    """
    counter = itertools.count()
    # Heap entries: (cost, tie_breaker, node, path_so_far).
    heap = [(0.0, next(counter), start, [start])]
    best_cost = {start: 0.0}

    while heap:
        cost, _, node, path = heapq.heappop(heap)
        if node == end:
            return path, cost
        if cost > best_cost.get(node, float("inf")):
            continue  # a cheaper route to this node was already settled
        for neighbour in adjacency[node]:
            if neighbour in path:
                continue  # keep the path simple (cycle-free)
            step = penalty.get(_edge_key(node, neighbour), 1.0)
            new_cost = cost + step
            if new_cost < best_cost.get(neighbour, float("inf")):
                best_cost[neighbour] = new_cost
                heapq.heappush(heap, (new_cost, next(counter), neighbour, path + [neighbour]))

    return None, float("inf")


def _dijkstra_costs(adjacency, source):
    """Unweighted single-source shortest-path costs from ``source``.

    Returns ``{node: cost}`` for every node reachable from ``source`` (each edge
    costs 1). Used to score candidate waypoint orderings cheaply, before running
    the real penalty-weighted search.
    """
    costs = {source: 0.0}
    heap = [(0.0, source)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > costs.get(node, float("inf")):
            continue
        for neighbour in adjacency[node]:
            new_cost = cost + 1.0
            if new_cost < costs.get(neighbour, float("inf")):
                costs[neighbour] = new_cost
                heapq.heappush(heap, (new_cost, neighbour))
    return costs


def _ordered_point_lists(adjacency, start, end, waypoints):
    """Candidate point sequences ``[start, *stops, end]``, cheapest order first.

    The visiting order of the required stops is a small travelling-salesman
    problem. We score every ordering by the base-cost distances between the key
    nodes (start, end, each stop) and return the reachable orderings sorted from
    cheapest to most expensive. The caller walks this list and keeps the first
    order that yields an actual (simple-path) route — the heuristic order is
    almost always feasible, but this stays correct when it is not.

    Beyond :data:`MAX_OPTIMIZED_WAYPOINTS` stops the permutation count explodes,
    so we consider only the caller's given order.
    """
    key_nodes = [start, end, *waypoints]
    costs = {node: _dijkstra_costs(adjacency, node) for node in key_nodes}

    def total(order):
        sequence = [start, *order, end]
        acc = 0.0
        for a, b in zip(sequence, sequence[1:]):
            step = costs[a].get(b)
            if step is None:
                return None  # a required leg is unreachable in the base graph
            acc += step
        return acc

    if len(waypoints) <= MAX_OPTIMIZED_WAYPOINTS:
        orders = itertools.permutations(waypoints)
    else:
        orders = [tuple(waypoints)]

    scored = []
    for order in orders:
        cost = total(order)
        if cost is not None:
            scored.append((cost, [start, *order, end]))
    scored.sort(key=lambda item: item[0])
    return [points for _, points in scored]


def _simple_path_via(adjacency, points, penalty):
    """Penalty-weighted shortest *simple* path visiting ``points`` in order.

    Real-world routing: the whole route is a simple path — no node is ever
    visited twice — that touches the required stops in the given order. It is a
    best-first search over partial simple paths:

      * a node already on the path is never re-entered (no revisits);
      * a required stop may only be entered when it is the *next* one due —
        stepping onto a later stop early would strand it and dead-end;
      * among equal-cost frontiers the earliest-discovered wins, so output is
        deterministic (neighbours are iterated in sorted order).

    Because it always expands the cheapest frontier first, the very first route
    it returns is the genuine shortest one for this order — so when a direct
    connection between two stops exists it is used, never detoured around.

    Returns ``(path, cost)`` or ``(None, inf)`` if no simple route visits every
    stop in order.
    """
    point_set = set(points)
    last = len(points) - 1  # index of the final stop (the end)

    counter = itertools.count()
    # Heap entries: (cost, tie_breaker, node, reached, path). ``reached`` is how
    # many entries of ``points`` we have hit so far; we start already on the
    # first one, so the next stop due is ``points[reached]``.
    heap = [(0.0, next(counter), points[0], 1, (points[0],))]
    explored = 0

    while heap:
        cost, _, node, reached, path = heapq.heappop(heap)
        if reached > last:
            return list(path), cost  # reached the final stop, in order

        explored += 1
        if explored > SEARCH_STATE_CAP:
            break

        target = points[reached]
        for neighbour in adjacency[node]:
            # The final step may land back on the start node (a round trip where
            # start == end); every other repeat is forbidden.
            revisits = neighbour in path
            if revisits and not (neighbour == target and reached == last):
                continue
            # A required stop is only enterable as the current target.
            if neighbour in point_set and neighbour != target:
                continue
            step = penalty.get(_edge_key(node, neighbour), 1.0)
            new_reached = reached + 1 if neighbour == target else reached
            heapq.heappush(
                heap,
                (cost + step, next(counter), neighbour, new_reached, path + (neighbour,)),
            )

    return None, float("inf")


def _collect_diverse(inner, k, penalty_factor, max_overlap, max_stretch):
    """Iterative edge-penalty search for up to ``k`` diverse routes.

    ``inner(penalty)`` returns ``(path, cost)`` for the current penalty map — it
    encapsulates *how* a single route is found (plain shortest path, or a simple
    path through required stops). This function is the shared diversity layer:
    it penalises the edges of each route it sees so the next search is pushed
    onto a different corridor, and keeps a candidate only if it is neither too
    similar to an accepted route (``max_overlap``) nor an excessive detour
    (``max_stretch``).
    """
    penalty = {}
    accepted = []
    accepted_edges = []  # edge set per accepted route, parallel to ``accepted``
    shortest_cost = None

    for _ in range(k * 8):
        if len(accepted) >= k:
            break

        path, cost = inner(penalty)
        if path is None:
            break

        edges = _edges(path)
        # Penalise this path's edges whether or not we keep it, so the next
        # search is pushed somewhere new either way.
        for edge in edges:
            penalty[edge] = penalty.get(edge, 1.0) * penalty_factor

        if any(path == p for p in accepted):
            continue

        if shortest_cost is None:
            shortest_cost = cost  # the first (unpenalised) path is the fastest
        elif cost > shortest_cost * max_stretch:
            continue  # too long a detour to be a useful alternative

        # Reject near-duplicates: too much of this route reuses one we kept.
        if any(
            len(edges & prior) / len(edges) > max_overlap for prior in accepted_edges
        ):
            continue

        accepted.append(path)
        accepted_edges.append(edges)

    # Present fastest-first; a stable sort preserves discovery order among ties.
    accepted.sort(key=lambda p: len(p))
    return accepted


def k_shortest_paths(
    adjacency,
    start,
    end,
    k=3,
    penalty_factor=3.0,
    max_overlap=0.6,
    max_stretch=2.5,
    via=None,
):
    """Return up to ``k`` *diverse* alternative routes from ``start`` to ``end``.

    The goal is Waze-style options: option 1 is the genuine shortest route, and
    each further option is a meaningfully different corridor rather than the
    shortest path with one node swapped.

    ``via`` is an optional list of *required stops* the route must pass through.
    When given, every returned route is a real-world simple path — **no node is
    ever visited twice** — that touches the stops in an optimised order, and
    alternatives are kept tight (see :data:`WAYPOINT_MAX_STRETCH`) so none of
    them detours around a connection that is already short. With no ``via`` the
    behaviour is exactly the classic diverse shortest-path search.

    Algorithm — the iterative edge-penalty method used by real routing engines:

      1. Find the shortest path.
      2. Multiply the weight of every edge on it by ``penalty_factor``.
      3. Search again; the penalty repels the next route away from edges the
         chosen routes already cover, so it takes a different corridor.
      4. Keep a candidate only if it is not too similar to an already-chosen
         route (``max_overlap``) and not an excessive detour (``max_stretch``).

    Tunables:
      * ``penalty_factor`` — how hard reused edges are pushed away (>1).
      * ``max_overlap``    — reject a candidate sharing more than this fraction
                             of its own edges with any accepted route (0..1).
      * ``max_stretch``    — reject alternatives longer than this multiple of
                             the shortest route's length.

    Edge cases:
      * ``start == end`` (no ``via``) -> ``[[start]]`` (if the node exists)
      * ``start``/``end``/``via`` absent from graph -> ``[]``
      * no connection / unreachable stop           -> ``[]``
    """
    # Normalise required stops: drop blanks, de-duplicate, and discard any that
    # coincide with start/end (already visited), preserving first-seen order.
    waypoints = []
    seen = {start, end}
    for stop in via or []:
        stop = stop.strip() if isinstance(stop, str) else stop
        if stop and stop not in seen:
            seen.add(stop)
            waypoints.append(stop)

    if start not in adjacency or end not in adjacency:
        return []
    if any(stop not in adjacency for stop in waypoints):
        return []

    # No required stops -> classic diverse shortest-path search (unchanged).
    if not waypoints:
        if start == end:
            return [[start]]
        inner = lambda penalty: _shortest_path(adjacency, start, end, penalty)
        return _collect_diverse(inner, k, penalty_factor, max_overlap, max_stretch)

    # Required stops -> strict simple paths, tightly bounded so no route wanders
    # off on a detour. Try candidate stop orders cheapest-first and keep the
    # first order that actually yields a simple route.
    stretch = min(max_stretch, WAYPOINT_MAX_STRETCH)
    for points in _ordered_point_lists(adjacency, start, end, waypoints):
        inner = lambda penalty, pts=points: _simple_path_via(adjacency, pts, penalty)
        accepted = _collect_diverse(inner, k, penalty_factor, max_overlap, stretch)
        if accepted:
            return accepted

    return []
