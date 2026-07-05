"""Graph construction and shortest-path search.

Routes are chains of place names. Consecutive places in a route form a
bidirectional edge. From those edges we build an undirected, unweighted graph
stored as an adjacency list. Path search is a BFS enumeration that yields the
top-k distinct simple paths, shortest first.
"""

from collections import deque


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


def k_shortest_paths(adjacency, start, end, k=3):
    """Return up to ``k`` distinct simple paths from ``start`` to ``end``.

    Paths are ordered shortest-first. Because the graph is unweighted, a BFS
    that expands partial paths in FIFO order discovers them in non-decreasing
    length order. We only extend to nodes not already on the current path, so
    every result is a simple (cycle-free) path.

    Edge cases:
      * ``start == end``           -> ``[[start]]`` (if the node exists)
      * ``start`` or ``end`` absent -> ``[]``
      * no connection              -> ``[]``
    """
    if start not in adjacency or end not in adjacency:
        return []
    if start == end:
        return [[start]]

    paths = []
    # Queue holds partial simple paths; start with just the origin.
    queue = deque([[start]])

    while queue and len(paths) < k:
        path = queue.popleft()
        last = path[-1]
        for neighbour in adjacency[last]:
            if neighbour in path:
                continue  # keep paths simple
            new_path = path + [neighbour]
            if neighbour == end:
                paths.append(new_path)
                if len(paths) >= k:
                    break
            else:
                queue.append(new_path)

    return paths
